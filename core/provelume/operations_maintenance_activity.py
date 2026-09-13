from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from .capacity_admission import CapacityAdmission
from .instance_lifecycle import InstanceLifecycleError
from .instance_repair import InstanceRepairManager
from .instance_repair_model import InstanceRepairError
from .operations_maintenance import OperationsMaintenance
from .scheduler import public_job_record
from .shell_activity import MutationNonces, _loopback_request
from .storage import InstanceStore

MAX_FORM_BYTES = 8 * 1024
OPERATION_ERRORS = (ValueError, OSError, InstanceRepairError, InstanceLifecycleError)
REPAIR_GUIDANCE = {
    "unsupported_artifact_path": "path",
    "unsupported_profile": "path",
    "missing_path": "missing",
    "unsafe_path": "unsafe",
    "unsupported_file": "unsafe",
    "artifact_not_identical": "different",
    "run_not_completed": "incomplete",
    "terminal_evidence_mismatch": "incomplete",
    "invalid_producer_evidence": "incomplete",
    "other_recovery_pending": "pending",
    "repair_recovery_pending": "pending",
    "known_invalid_repair_state": "pending",
    "writer_active": "busy",
    "snapshot_changed": "changed",
    "insufficient_space": "space",
    "unsupported_validation_findings": "findings",
}


class ReviewedMaintenancePlans:
    """Per-server reviewed previews, never a durable job/authority queue."""

    def __init__(self):
        self._rows: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, kind: str, payload: dict, display: dict) -> str:
        with self._lock:
            now = time.monotonic()
            self._expire(now)
            if len(self._rows) >= 128:
                raise ValueError("preview_capacity")
            key = secrets.token_hex(16)
            self._rows[key] = {
                "kind": kind,
                "payload": payload,
                "display": display,
                "request_id": secrets.token_hex(16),
                "created": now,
            }
            return key

    def _expire(self, now):
        while self._rows and next(iter(self._rows.values()))["created"] < now - 900:
            self._rows.popitem(last=False)

    def get(self, key: str) -> dict:
        with self._lock:
            self._expire(time.monotonic())
            if key not in self._rows:
                raise ValueError("preview_expired")
            return self._rows[key]


def attach_operations_maintenance_routes(
    app: FastAPI,
    instance: Any,
    templates: Any,
    context_factory: Any,
    *,
    recovery_store: InstanceStore | None = None,
) -> None:
    store = instance.store if instance is not None else recovery_store
    if store is None:
        raise ValueError("an explicitly selected Instance is required")
    instance_id = str(store.read_config()["instance"]["id"])
    model = OperationsMaintenance(store)
    repair = InstanceRepairManager(store)
    capacity = CapacityAdmission(store)
    token = secrets.token_urlsafe(32)
    nonces = MutationNonces()
    previews = ReviewedMaintenancePlans()

    def page(request, name, *, status_code=200, **values):
        context = context_factory(request, instance, **values)
        editable = _loopback_request(request)
        context.update(
            editable=editable,
            csrf_token=token if editable else None,
            mutation_nonce=nonces.issue() if editable else None,
            selected_instance_id=instance_id,
            recovery_only=instance is None,
        )
        return templates.TemplateResponse(
            request=request, name=name, context=context, status_code=status_code
        )

    def denied(request, code="operation_unavailable", status_code=409, *, repair_reason=None):
        return page(
            request,
            "cura/maintenance_result.html",
            status_code=status_code,
            result=None,
            error=code,
            repair_reason=repair_reason,
        )

    async def fields(request: Request, required: set[str]):
        if not _loopback_request(request):
            raise HTTPException(403, "maintenance mutations require the local browser")
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip()
            != "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "unsupported maintenance form")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_FORM_BYTES:
                raise HTTPException(413, "maintenance form exceeds its bound")
        try:
            raw = parse_qs(
                body.decode("utf-8"), keep_blank_values=True, strict_parsing=True, max_num_fields=16
            )
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(400, "invalid maintenance form") from exc
        allowed = required | {"csrf_token", "mutation_nonce", "instance_id"}
        if set(raw) != allowed or any(len(v) != 1 for v in raw.values()):
            raise HTTPException(400, "incomplete or unsupported maintenance fields")
        result = {k: v[0] for k, v in raw.items()}
        if not hmac.compare_digest(result["csrf_token"], token):
            raise HTTPException(403, "invalid maintenance token")
        if result["instance_id"] != instance_id:
            raise HTTPException(409, "maintenance Instance changed")
        if not nonces.consume(result["mutation_nonce"]):
            raise HTTPException(409, "maintenance form expired or already submitted")
        return result

    def reviewed(request, kind, payload, display):
        allowed = {
            "action",
            "action_id",
            "job_id",
            "scope",
            "authority",
            "estimate",
            "ready",
            "plan_revision",
            "revision",
            "profile",
            "relative_path",
            "affected_files",
            "quarantine_path",
            "recovery_backup_scope",
            "required_bytes",
            "free_bytes",
            "reversible",
            "resulting_validation_status",
            "effect",
            "receipt_id",
            "impact",
            "archive_sha256",
            "archive_path",
            "backup_id",
            "size_bytes",
            "files",
            "target_ref",
            "target_revision",
            "instance_id",
            "plan_id",
            "input_revision",
            "plan_ref",
            "categories",
            "member_count",
            "estimated_bytes",
            "coverage",
            "observed_at",
            "mode",
            "running_jobs_stopped",
            "automatic_deletion",
            "verified_backup",
            "destination",
            "purpose",
            "files_deleted",
            "phase",
            "operation",
        }
        display = {k: v for k, v in display.items() if k in allowed}
        key = previews.put(kind, payload, display)
        return page(
            request,
            "cura/maintenance_confirm.html",
            preview_id=key,
            preview=display,
            command_kind=kind,
        )

    @app.get("/maintenance/overview")
    def overview(request: Request, offset: int = 0):
        if instance is None:
            return RedirectResponse("/maintenance/repair", status_code=303)
        try:
            observation = model.snapshot(offset=offset)
            catalog = instance.maintenance.catalog(include_explicit=True)
            policy = capacity.status()
            return page(
                request,
                "cura/maintenance_overview.html",
                observation=observation,
                catalog=catalog,
                capacity=policy,
                sources=instance.folder_sources.list_public(),
            )
        except OPERATION_ERRORS:
            return denied(request, "evidence_unavailable")

    @app.get("/api/v1/maintenance/overview")
    def overview_api(limit: int = 100, offset: int = 0):
        if instance is None:
            raise HTTPException(409, "recovery mode has no operational runtime")
        try:
            return model.snapshot(limit=limit, offset=offset)
        except (ValueError, OSError) as exc:
            raise HTTPException(409, "maintenance evidence unavailable") from exc

    @app.get("/maintenance/jobs/{job_id}")
    def job_detail(request: Request, job_id: str):
        if instance is None:
            return denied(request)
        try:
            job = model.job(job_id)
            if job is None:
                raise HTTPException(404, "job not found")
            capabilities = instance.scheduler.job_capabilities(job_id)
            return page(request, "cura/maintenance_job.html", job=job, capabilities=capabilities)
        except OPERATION_ERRORS:
            return denied(request, "evidence_unavailable")

    @app.get("/maintenance/jobs/{job_id}/preview/{action}")
    def job_preview(request: Request, job_id: str, action: str):
        if instance is None:
            return denied(request)
        try:
            plan = instance.scheduler.preview_job_control(job_id, action)
            return reviewed(
                request,
                "job_control",
                plan,
                {
                    "action": action,
                    "job_id": job_id,
                    "scope": plan["job"]["scope"],
                    "impact": plan["impact"],
                    "revision": plan["revision"],
                    "reversible": plan["reversible"],
                },
            )
        except OPERATION_ERRORS:
            return denied(request, "preview_unavailable")

    @app.post("/maintenance/plan")
    async def maintenance_plan(request: Request):
        values = await fields(request, {"action_id", "source_id"})
        if instance is None:
            return denied(request)
        try:
            params = {"source_id": values["source_id"]} if values["source_id"] else None
            plan = instance.maintenance.plan_action(values["action_id"], parameters=params)
            return reviewed(
                request,
                "maintenance_run",
                {"action_id": values["action_id"], "parameters": params, "plan": plan},
                plan,
            )
        except OPERATION_ERRORS:
            return denied(request, "preview_unavailable")

    @app.get("/maintenance/backup")
    def backup_page(request: Request):
        return page(request, "cura/maintenance_tools.html", tool="backup")

    @app.post("/maintenance/backup")
    async def backup_plan(request: Request):
        values = await fields(request, {"archive_path"})
        if instance is None:
            return denied(request)
        from .maintenance_targets import LocalTargetRegistry

        try:
            target = LocalTargetRegistry(store).register_archive(values["archive_path"])
            parameters = {k: target[k] for k in ("target_ref", "target_revision")}
            plan = instance.maintenance.plan_action(
                "maintenance.backup_verify", parameters=parameters
            )
            return reviewed(
                request,
                "maintenance_run",
                {"action_id": "maintenance.backup_verify", "parameters": parameters, "plan": plan},
                {**plan, **plan["plan"], "archive_path": values["archive_path"]},
            )
        except OPERATION_ERRORS:
            return denied(request, "backup_target_unavailable")

    @app.get("/maintenance/diagnostics")
    def diagnostic_page(request: Request):
        return page(request, "cura/maintenance_tools.html", tool="diagnostics")

    @app.post("/maintenance/diagnostics")
    async def diagnostic_preview(request: Request):
        values = await fields(request, {"destination"})
        if instance is None:
            return denied(request)
        from .maintenance_diagnostics import DiagnosticExportService
        from .maintenance_targets import LocalTargetRegistry

        try:
            target = LocalTargetRegistry(store).register_output(values["destination"])
            plan = DiagnosticExportService(store).preview()
            return reviewed(
                request,
                "diagnostic_export",
                {"target": target, "plan": plan},
                {**plan, "destination": values["destination"]},
            )
        except OPERATION_ERRORS:
            return denied(request, "diagnostics_unavailable")

    @app.get("/maintenance/repair")
    def repair_page(request: Request):
        pending = repair.preview_pending_recovery()
        return page(request, "cura/maintenance_tools.html", tool="repair", pending=pending)

    @app.get("/maintenance/repair/reconcile")
    def pending_repair_preview(request: Request):
        plan = repair.preview_pending_recovery()
        if plan["status"] != "eligible":
            return denied(request, "recovery_unavailable")
        return reviewed(request, "repair_reconcile", plan, plan)

    @app.get("/maintenance/selections")
    def retained_selections(request: Request):
        if instance is None:
            return denied(request)
        from .maintenance_diagnostics import DiagnosticExportService
        from .maintenance_targets import LocalTargetRegistry

        try:
            return page(
                request,
                "cura/maintenance_selections.html",
                targets=LocalTargetRegistry(store).status(),
                plans=DiagnosticExportService(store).status(),
            )
        except OPERATION_ERRORS:
            return denied(request, "evidence_unavailable")

    @app.post("/maintenance/selections/preview")
    async def selection_preview(request: Request):
        values = await fields(request, {"kind", "reference", "revision"})
        if instance is None:
            return denied(request)
        from .maintenance_diagnostics import DiagnosticExportService
        from .maintenance_targets import LocalTargetRegistry

        try:
            if values["kind"] == "target_revoke":
                rows = LocalTargetRegistry(store).status()["targets"]
                ref, revision, action = "target_ref", "target_revision", "revoke"
            elif values["kind"] == "diagnostic_forget":
                rows = DiagnosticExportService(store).status()["plans"]
                ref, revision, action = "plan_ref", "revision", "forget"
            else:
                return denied(request, "preview_unavailable")
            row = next(
                (
                    r
                    for r in rows
                    if r[ref] == values["reference"] and r[revision] == values["revision"]
                ),
                None,
            )
            if row is None:
                return denied(request, "preview_unavailable")
            return reviewed(
                request,
                values["kind"],
                values,
                {**row, "action": action, "files_deleted": False},
            )
        except OPERATION_ERRORS:
            return denied(request, "preview_unavailable")

    @app.post("/maintenance/repair")
    async def repair_preview(request: Request):
        values = await fields(request, {"relative_path"})
        try:
            plan = repair.preview(
                "repair.maintenance_redundant_atomic_artifact", values["relative_path"]
            )
            if plan["status"] != "eligible":
                return denied(
                    request,
                    "repair_unsupported",
                    repair_reason=REPAIR_GUIDANCE.get(plan.get("reason"), "unreadable"),
                )
            return reviewed(request, "repair_backup", plan, plan)
        except OPERATION_ERRORS:
            return denied(request, "repair_unavailable")

    @app.get("/maintenance/repair/rollback/{receipt_id}")
    def repair_rollback(request: Request, receipt_id: str):
        try:
            plan = repair.preview_rollback(receipt_id)
            if plan["status"] != "eligible":
                return denied(request, "rollback_unavailable")
            return reviewed(request, "repair_rollback", plan, plan)
        except OPERATION_ERRORS:
            return denied(request, "rollback_unavailable")

    @app.post("/maintenance/capacity")
    async def capacity_plan(request: Request):
        if instance is None:
            return denied(request)
        values = await fields(request, {"mode", "revision"})
        try:
            revision = int(values["revision"])
            current = capacity.status()
            if (
                values["mode"] not in {"observe_only", "pause_on_critical", "paused"}
                or revision != current["revision"]
            ):
                return denied(request, "capacity_policy_stale")
            return reviewed(
                request,
                "capacity_policy",
                {"mode": values["mode"], "revision": revision},
                {
                    "mode": values["mode"],
                    "scope": "new_intake_admission",
                    "running_jobs_stopped": False,
                    "automatic_deletion": False,
                },
            )
        except OPERATION_ERRORS:
            return denied(request, "capacity_unavailable")

    @app.post("/maintenance/confirm")
    async def execute_reviewed(request: Request):
        values = await fields(request, {"preview_id", "confirmed"})
        if values["confirmed"] != "yes":
            raise HTTPException(400, "explicit confirmation is required")
        try:
            selected = previews.get(values["preview_id"])
            payload, key, kind = selected["payload"], selected["request_id"], selected["kind"]
            if kind == "job_control" and instance is not None:
                result = instance.scheduler.control_job(
                    payload["job_id"],
                    payload["action"],
                    expected_revision=payload["revision"],
                    request_id=key,
                    expected_checkpoint=payload["checkpoint"],
                )
            elif kind == "maintenance_run" and instance is not None:
                plan = payload["plan"]
                parameters = payload["parameters"]
                source_id = parameters.get("source_id") if parameters else None
                result = instance.queue_maintenance_action(
                    payload["action_id"],
                    request_key=key,
                    source_id=source_id,
                    parameters=parameters,
                    expected_plan_revision=plan.get("plan_revision", plan.get("revision")),
                )
            elif kind == "diagnostic_export" and instance is not None:
                from .maintenance_diagnostics import DiagnosticExportService

                plan, target = payload["plan"], payload["target"]
                result = DiagnosticExportService(store).export(
                    plan["plan_ref"],
                    plan["revision"],
                    target["target_ref"],
                    target["target_revision"],
                    confirm=True,
                    request_key=key,
                )
            elif kind == "repair_backup":
                backup = repair.prepare_backup(payload, key)
                return reviewed(
                    request,
                    "repair_apply",
                    backup,
                    {**selected["display"], "verified_backup": backup},
                )
            elif kind == "repair_apply":
                result = repair.apply(
                    payload["backup_id"],
                    payload["input_revision"],
                    key,
                    payload["archive_sha256"],
                    confirm=True,
                )
            elif kind == "repair_rollback":
                result = repair.rollback(
                    payload["receipt_id"], payload["input_revision"], key, confirm=True
                )
            elif kind == "repair_reconcile":
                result = repair.recover_pending_reviewed(
                    payload["input_revision"], key, confirm=True
                )
            elif kind == "capacity_policy" and instance is not None:
                result = capacity.configure(
                    payload["mode"], expected_revision=payload["revision"], request_id=key
                )
            elif kind == "target_revoke" and instance is not None:
                from .maintenance_targets import LocalTargetRegistry

                result = LocalTargetRegistry(store).revoke(
                    payload["reference"], payload["revision"]
                )
            elif kind == "diagnostic_forget" and instance is not None:
                from .maintenance_diagnostics import DiagnosticExportService

                result = DiagnosticExportService(store).forget(
                    payload["reference"], payload["revision"], confirm=True
                )
            else:
                return denied(request)
            if isinstance(result, dict):
                result = dict(result)
                for key in ("job", "successor"):
                    if isinstance(result.get(key), dict):
                        result[key] = public_job_record(result[key])
            return page(request, "cura/maintenance_result.html", result=result, error=None)
        except OPERATION_ERRORS:
            # Closed UI error, never arbitrary exception text or a successful no-op.
            return denied(request, "operation_changed_or_unavailable")
