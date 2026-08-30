from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from .derived import provenance_edge
from .domain import DerivedArtifact
from .ocr_contract import (
    OCR_CONTRACT_SCHEMA_VERSION,
    OCR_ERROR_MESSAGES,
    OCR_RELIABLE_TEXT_GENERATORS,
    OcrAdapterCapability,
    OcrContractError,
    OcrPageRequest,
    OcrRendererCapability,
    OcrSettings,
    OcrSourcePageIdentity,
    OcrUnavailableError,
    ocr_capability_report,
    ocr_document_derivation_key,
    ocr_settings_from_config,
    reliable_text_metrics,
    require_ocr_available,
    settings_fingerprint,
    should_schedule_ocr,
    validate_page_selection,
)
from .ocr_renderer import PdfiumPillowRenderer
from .ocr_tesseract import TesseractCliAdapter
from .paths import safe_instance_path
from .scheduler import SchedulerCoordinator, schedule_payload
from .scheduler_model import idempotency_digest
from .storage import InstanceStore, utc_now

OCR_BUNDLE_SCHEMA_VERSION = 1
OCR_JOB_KIND = "ocr.execute"
OCR_ARTIFACT_KIND = "ocr_document_bundle"
OCR_BUNDLE_GENERATOR = "provelume.local_ocr"
OCR_BUNDLE_GENERATOR_VERSION = "1"


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _signature(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(16)


def _closed_tree_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    if root.is_symlink() or not root.is_dir():
        raise OcrContractError(
            "ocr_internal_error", "Canonical knowledge root is invalid"
        )
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise OcrContractError(
                "ocr_internal_error", "Canonical knowledge contains a symbolic link"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        file_digest, size = _sha256_file(path)
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(file_digest))
    return digest.hexdigest()


class OcrJobManager:
    """Durable, local-only OCR planning, execution and removable bundle lifecycle."""

    def __init__(
        self,
        store: InstanceStore,
        *,
        renderer_factory: Callable[[OcrSettings, Path], Any] | None = None,
        adapter_factory: Callable[[OcrSettings, OcrRendererCapability, Path], Any]
        | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.store = store
        self.scheduler = SchedulerCoordinator(store)
        self.root = store.paths.state / "ocr"
        self.requests = self.root / "requests"
        self.runs = self.root / "runs"
        self.work = self.root / "work"
        self.cancellations = self.root / "cancellations"
        self.removals = self.root / "removals"
        self.bundles = store.paths.state / "derived" / "ocr-bundles"
        self.temporary_root = store.paths.state / "tmp" / "ocr"
        self.renderer_factory = renderer_factory or (
            lambda settings, temporary: PdfiumPillowRenderer(settings, temporary)
        )
        self.adapter_factory = adapter_factory or (
            lambda settings, renderer, temporary: TesseractCliAdapter(
                settings,
                renderer,
                temporary,
            )
        )
        self.clock = clock

    def _ensure_directories(self) -> None:
        for path in (
            self.root,
            self.requests,
            self.runs,
            self.work,
            self.cancellations,
            self.removals,
            self.bundles,
            self.temporary_root,
        ):
            if path.exists() and (path.is_symlink() or not path.is_dir()):
                raise OcrContractError(
                    "ocr_internal_error", "OCR state directory is invalid"
                )
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "posix" and path in {self.work, self.temporary_root}:
                os.chmod(path, 0o700)

    def configure(self, settings: OcrSettings) -> dict[str, Any]:
        config = self.store.read_config()
        config["ocr"] = settings.as_record()
        self.store.write_config(config)
        self.store.validate()
        return settings.as_record()

    def configured_settings(self) -> OcrSettings:
        return ocr_settings_from_config(self.store.read_config())

    def _components(
        self, settings: OcrSettings
    ) -> tuple[Any, OcrRendererCapability, Any, OcrAdapterCapability]:
        self._ensure_directories()
        renderer = self.renderer_factory(settings, self.temporary_root)
        renderer_capability = renderer.capability()
        adapter = self.adapter_factory(settings, renderer_capability, self.temporary_root)
        adapter_capability = adapter.capability()
        return renderer, renderer_capability, adapter, adapter_capability

    def capability(self, settings: OcrSettings | None = None) -> dict[str, Any]:
        selected = settings or self.configured_settings()
        if selected.mode == "disabled":
            return ocr_capability_report(selected)
        renderer, _renderer_capability, adapter, _adapter_capability = self._components(
            selected
        )
        return ocr_capability_report(selected, adapter, renderer)

    def _version_source(
        self, version_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
        version = self.store.read_canonical("versions", version_id)
        if version is None:
            raise OcrContractError(
                "ocr_unsupported_input", "OCR DocumentVersion was not found"
            )
        document = self.store.read_canonical("documents", version["document_id"])
        original = self.store.read_canonical("originals", version["original_id"])
        if document is None or original is None:
            raise OcrContractError(
                "ocr_corrupt_input", "OCR source identity is incomplete"
            )
        original_path = safe_instance_path(
            self.store.paths.root, str(original["storage_ref"])
        )
        self._verify_original(version, original, original_path)
        return version, document, original, original_path

    @staticmethod
    def _verify_original(
        version: Mapping[str, Any], original: Mapping[str, Any], path: Path
    ) -> str:
        if path.is_symlink() or not path.is_file():
            raise OcrContractError("ocr_corrupt_input", "OCR Original is unavailable")
        digest, size = _sha256_file(path)
        if (
            digest != version.get("content_hash")
            or digest != original.get("sha256")
            or size != int(version.get("size_bytes", -1))
            or size != int(original.get("size_bytes", -1))
        ):
            raise OcrContractError(
                "ocr_corrupt_input", "OCR Original identity verification failed"
            )
        return digest

    def _reliable_text(self, version_id: str) -> tuple[int, float, str | None]:
        artifacts = sorted(
            (
                artifact
                for artifact in self.store.list_derived_artifacts()
                if artifact.get("version_id") == version_id
                and artifact.get("kind") == "extracted_text"
            ),
            key=lambda item: str(item.get("id", "")),
        )
        if not artifacts:
            return 0, 0.0, None
        trusted = [
            artifact
            for artifact in artifacts
            if artifact.get("generator") in OCR_RELIABLE_TEXT_GENERATORS
        ]
        if not trusted:
            return 0, 0.0, str(artifacts[0].get("generator", ""))
        evidence = []
        for artifact in trusted:
            generator = str(artifact["generator"])
            try:
                characters, ratio = reliable_text_metrics(
                    self.store.read_derived_text(artifact), generator=generator
                )
            except (OSError, UnicodeError):
                characters, ratio = 0, 0.0
            evidence.append((characters, ratio, generator))
        return max(evidence)

    def _policy(self) -> dict[str, Any]:
        existing = [
            policy
            for policy in self.scheduler.journal.list_policies()
            if policy["job_kind"] == OCR_JOB_KIND
        ]
        if len(existing) > 1:
            raise OcrContractError(
                "ocr_internal_error", "Multiple OCR scheduler policies are present"
            )
        if existing:
            return existing[0]
        instance_id = str(self.store.read_config()["instance"]["id"])
        return self.scheduler.journal.create_policy(
            job_kind=OCR_JOB_KIND,
            scope={"kind": "instance", "id": instance_id},
            state="disabled",
            schedule=schedule_payload(mode="manual", timezone="UTC"),
        )

    def queue(
        self,
        version_id: str,
        *,
        mode: str | None = None,
        languages: Sequence[str] | None = None,
        pages: Sequence[int] = (),
        rebuild_nonce: str | None = None,
    ) -> dict[str, Any]:
        configured = self.configured_settings()
        selected = replace(
            configured,
            mode=configured.mode if mode is None else mode,
            languages=(
                configured.languages
                if languages is None
                else tuple(sorted(set(languages)))
            ),
        )
        reliable_characters, printable_ratio, reliable_generator = self._reliable_text(
            version_id
        )
        if selected.mode == "disabled":
            report = ocr_capability_report(selected)
            require_ocr_available(report)
        if (
            rebuild_nonce is None
            and selected.mode == "automatic"
            and not should_schedule_ocr(
                selected,
                reliable_text_characters=reliable_characters,
                printable_ratio=printable_ratio,
            )
        ):
            return {
                "scheduled": False,
                "reason": "reliable-text-present",
                "mode": selected.mode,
                "reliable_text_characters": reliable_characters,
                "printable_ratio": printable_ratio,
                "reliable_text_generator": reliable_generator,
                "network_used": False,
                "canonical_mutation": False,
            }
        version, document, original, original_path = self._version_source(version_id)
        if int(original["size_bytes"]) > selected.limits.max_input_bytes:
            raise OcrContractError(
                "ocr_input_too_large", "OCR Original exceeds the configured byte limit"
            )
        renderer, renderer_capability, adapter, adapter_capability = self._components(
            selected
        )
        report = ocr_capability_report(selected, adapter, renderer)
        require_ocr_available(report)
        with tempfile.TemporaryDirectory(
            prefix="ocr-plan-", dir=self.temporary_root
        ) as directory:
            temporary = Path(directory)
            if os.name == "posix":
                os.chmod(temporary, 0o700)
            plan = renderer.inspect(
                original_path,
                media_type=str(version["media_type"]),
                suffix=Path(str(document["locator"])).suffix,
                signature=_signature(original_path),
                input_bytes=int(original["size_bytes"]),
                work_directory=temporary,
            )
        if selected.mode == "selected-page":
            selected_pages = validate_page_selection(
                pages,
                page_count=plan.page_count,
                max_pages=selected.limits.max_pages,
            )
        else:
            if pages:
                raise OcrContractError(
                    "ocr_invalid_selection",
                    "Explicit pages require selected-page mode",
                )
            selected_pages = tuple(range(1, plan.page_count + 1))
        derivation = ocr_document_derivation_key(
            original_sha256=str(original["sha256"]),
            version_id=version_id,
            pages=selected_pages,
            settings=selected,
            capability=adapter_capability,
            renderer=renderer_capability,
        )
        policy = self._policy()
        request_identity = derivation
        if rebuild_nonce is not None:
            request_identity = f"{derivation}:{rebuild_nonce}"
        scheduler_key = idempotency_digest(
            "manual",
            str(policy["id"]),
            str(policy["revision"]),
            request_identity,
        )
        request = {
            "schema_version": OCR_BUNDLE_SCHEMA_VERSION,
            "scheduler_key": scheduler_key,
            "derivation_key": derivation,
            "version_id": version_id,
            "document_id": document["id"],
            "original_id": original["id"],
            "original_sha256": original["sha256"],
            "source_media_type": version["media_type"],
            "source_suffix": Path(str(document["locator"])).suffix.casefold(),
            "pages": list(selected_pages),
            "page_plan": [asdict(page) for page in plan.pages],
            "settings": selected.as_record(),
            "settings_sha256": settings_fingerprint(selected),
            "adapter": adapter_capability.as_record(),
            "renderer": renderer_capability.as_record(),
            "automatic_evidence": {
                "reliable_text_characters": reliable_characters,
                "printable_ratio": printable_ratio,
                "reliable_text_generator": reliable_generator,
            },
            "rebuild_nonce": rebuild_nonce,
            "network_used": False,
            "runtime_downloads": False,
            "remote_fallback": False,
        }
        self.store._atomic_json(self.requests / f"{scheduler_key}.json", request)
        queued = self.scheduler.journal.run_now(
            str(policy["id"]), request_key=request_identity
        )
        if queued["job"]["idempotency_key"] != scheduler_key:
            raise OcrContractError(
                "ocr_internal_error", "OCR scheduler identity does not match its request"
            )
        return {
            "scheduled": True,
            "created": queued["created"],
            "job": queued["job"],
            "request": request,
            "capability": report,
        }

    @staticmethod
    def _capabilities_from_request(
        request: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        adapter = request.get("adapter")
        renderer = request.get("renderer")
        if not isinstance(adapter, dict) or not isinstance(renderer, dict):
            raise OcrContractError(
                "ocr_contract_violation", "OCR request component identity is invalid"
            )
        return adapter, renderer

    def _request_for_job(self, job: Mapping[str, Any]) -> dict[str, Any]:
        path = self.requests / f"{job['idempotency_key']}.json"
        if path.is_symlink() or not path.is_file():
            raise OcrContractError(
                "ocr_contract_violation", "Durable OCR request is missing"
            )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OcrContractError(
                "ocr_contract_violation", "Durable OCR request is unreadable"
            ) from exc
        if not isinstance(value, dict) or value.get("scheduler_key") != job[
            "idempotency_key"
        ]:
            raise OcrContractError(
                "ocr_contract_violation", "Durable OCR request identity is invalid"
            )
        return value

    def _cancelled(self, job_id: str) -> bool:
        return (self.cancellations / f"{job_id}.request").is_file()

    def _write_run(
        self,
        job: Mapping[str, Any],
        request: Mapping[str, Any],
        *,
        state: str,
        error_code: str | None,
        committed_pages: Sequence[int],
        bundle_ref: str | None,
        canonical_before: str,
        canonical_after: str,
        original_before: str,
        original_after: str,
    ) -> dict[str, Any]:
        value = {
            "schema_version": OCR_BUNDLE_SCHEMA_VERSION,
            "job_id": job["id"],
            "derivation_key": request["derivation_key"],
            "version_id": request["version_id"],
            "state": state,
            "error": (
                None
                if error_code is None
                else {
                    "code": error_code,
                    "messages": dict(OCR_ERROR_MESSAGES[error_code]),
                }
            ),
            "committed_pages": list(committed_pages),
            "bundle_ref": bundle_ref,
            "original_sha256_before": original_before,
            "original_sha256_after": original_after,
            "canonical_fingerprint_before": canonical_before,
            "canonical_fingerprint_after": canonical_after,
            "network_used": False,
            "runtime_downloads": False,
            "remote_fallback": False,
            "canonical_mutation": False,
        }
        self.store._atomic_json(self.runs / f"{job['id']}.json", value)
        return value

    def _completed_work_pages(
        self, work_directory: Path, request: Mapping[str, Any]
    ) -> dict[int, bytes]:
        checkpoint = work_directory / "checkpoint.json"
        if not checkpoint.exists():
            return {}
        if checkpoint.is_symlink() or not checkpoint.is_file():
            raise OcrContractError("ocr_internal_error", "OCR checkpoint is invalid")
        try:
            value = json.loads(checkpoint.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OcrContractError(
                "ocr_internal_error", "OCR checkpoint is unreadable"
            ) from exc
        if (
            not isinstance(value, dict)
            or value.get("derivation_key") != request["derivation_key"]
            or not isinstance(value.get("pages"), dict)
        ):
            raise OcrContractError("ocr_internal_error", "OCR checkpoint identity is invalid")
        completed: dict[int, bytes] = {}
        for page_text, digest in value["pages"].items():
            try:
                page_number = int(page_text)
            except (TypeError, ValueError) as exc:
                raise OcrContractError(
                    "ocr_internal_error", "OCR checkpoint page is invalid"
                ) from exc
            page_path = work_directory / "pages" / f"{page_number:06d}.json"
            if page_path.is_symlink() or not page_path.is_file():
                raise OcrContractError(
                    "ocr_internal_error", "OCR checkpoint output is missing"
                )
            data = page_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise OcrContractError(
                    "ocr_internal_error", "OCR checkpoint output identity changed"
                )
            completed[page_number] = data
        return completed

    def _checkpoint_work_page(
        self,
        work_directory: Path,
        request: Mapping[str, Any],
        page_number: int,
        page_record: Mapping[str, Any],
    ) -> bytes:
        pages = work_directory / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        data = _json_bytes(page_record)
        self.store._atomic_bytes(pages / f"{page_number:06d}.json", data)
        checkpoint_path = work_directory / "checkpoint.json"
        current = {
            "schema_version": OCR_BUNDLE_SCHEMA_VERSION,
            "derivation_key": request["derivation_key"],
            "pages": {},
        }
        if checkpoint_path.is_file():
            current = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        current["pages"][str(page_number)] = hashlib.sha256(data).hexdigest()
        current["pages"] = dict(
            sorted(current["pages"].items(), key=lambda item: int(item[0]))
        )
        self.store._atomic_json(checkpoint_path, current)
        return data

    def _promote_bundle(
        self,
        job: Mapping[str, Any],
        request: Mapping[str, Any],
        page_records: Mapping[int, bytes],
    ) -> tuple[str, bytes, bool]:
        derivation = str(request["derivation_key"])
        relative_root = (
            f"state/derived/ocr-bundles/{request['version_id']}/{derivation}"
        )
        final = safe_instance_path(self.store.paths.root, relative_root)
        final.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".ocr-bundle-", dir=final.parent))
        try:
            pages_directory = staging / "pages"
            pages_directory.mkdir()
            entries = []
            for page_number, data in sorted(page_records.items()):
                page_path = pages_directory / f"{page_number:06d}.json"
                page_path.write_bytes(data)
                record = json.loads(data)
                text = str(record["result"]["text"])
                text_data = text.encode("utf-8")
                text_path = pages_directory / f"{page_number:06d}.txt"
                text_path.write_bytes(text_data)
                entries.append(
                    {
                        "page_number": page_number,
                        "source_page": record["result"]["source_page"],
                        "result_ref": f"{relative_root}/pages/{page_number:06d}.json",
                        "result_sha256": hashlib.sha256(data).hexdigest(),
                        "text_ref": f"{relative_root}/pages/{page_number:06d}.txt",
                        "text_sha256": hashlib.sha256(text_data).hexdigest(),
                        "text_status": record["result"]["text_status"],
                        "warning_count": len(record["result"]["warnings"]),
                    }
                )
            manifest = {
                "schema_version": OCR_BUNDLE_SCHEMA_VERSION,
                "contract_schema_version": OCR_CONTRACT_SCHEMA_VERSION,
                "kind": OCR_ARTIFACT_KIND,
                "job": {"id": job["id"], "state": "succeeded"},
                "derivation_key": derivation,
                "document_id": request["document_id"],
                "version_id": request["version_id"],
                "original": {
                    "id": request["original_id"],
                    "sha256": request["original_sha256"],
                },
                "settings": request["settings"],
                "settings_sha256": request["settings_sha256"],
                "adapter": request["adapter"],
                "renderer": request["renderer"],
                "pages": entries,
                "warnings": [
                    warning
                    for data in page_records.values()
                    for warning in json.loads(data)["result"]["warnings"]
                ],
                "observations_are_separate_from_text": True,
                "text_is_verified": False,
                "authoritative": False,
                "derived": True,
                "removable": True,
                "rebuildable": True,
                "network_used": False,
                "runtime_downloads": False,
                "remote_fallback": False,
            }
            manifest_bytes = _json_bytes(manifest)
            (staging / "manifest.json").write_bytes(manifest_bytes)
            if final.exists():
                existing = final / "manifest.json"
                if not existing.is_file() or existing.is_symlink():
                    raise OcrContractError(
                        "ocr_internal_error", "Existing OCR bundle identity conflicts"
                    )
                existing_bytes = existing.read_bytes()
                if json.loads(existing_bytes).get("derivation_key") != derivation:
                    raise OcrContractError(
                        "ocr_internal_error", "Existing OCR bundle identity conflicts"
                    )
                return f"{relative_root}/manifest.json", existing_bytes, False
            else:
                os.replace(staging, final)
            return f"{relative_root}/manifest.json", manifest_bytes, True
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def execute(
        self,
        job: Mapping[str, Any],
        *,
        checkpoint: Callable[[dict[str, int]], Mapping[str, Any]],
    ) -> dict[str, int]:
        self._ensure_directories()
        request = self._request_for_job(job)
        settings = ocr_settings_from_config({"ocr": request["settings"]})
        version, _document, original, original_path = self._version_source(
            str(request["version_id"])
        )
        original_before = self._verify_original(version, original, original_path)
        canonical_before = _closed_tree_fingerprint(self.store.paths.knowledge)
        committed_pages: list[int] = []
        bundle_ref: str | None = None
        bundle_created = False
        artifact_id: str | None = None
        provenance_id: str | None = None
        work_directory = self.work / str(request["derivation_key"])
        work_directory.mkdir(parents=True, exist_ok=True)
        if work_directory.is_symlink():
            raise OcrContractError("ocr_internal_error", "OCR work directory is invalid")
        if os.name == "posix":
            os.chmod(work_directory, 0o700)
        error_code: str | None = None
        deadline = self.clock() + settings.limits.max_total_seconds

        def remaining_seconds() -> int:
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise OcrContractError(
                    "ocr_deadline_exceeded", "OCR job exceeded its total deadline"
                )
            return max(
                1,
                min(settings.limits.max_seconds_per_page, int(remaining)),
            )

        try:
            renderer, renderer_capability, adapter, adapter_capability = self._components(
                settings
            )
            expected_adapter, expected_renderer = self._capabilities_from_request(request)
            if (
                adapter_capability.as_record() != expected_adapter
                or renderer_capability.as_record() != expected_renderer
            ):
                raise OcrContractError(
                    "ocr_version_incompatible",
                    "OCR component identity changed after the job was queued",
                )
            report = ocr_capability_report(settings, adapter, renderer)
            require_ocr_available(report)
            remaining_seconds()
            with tempfile.TemporaryDirectory(
                prefix="ocr-execute-", dir=self.temporary_root
            ) as inspection_directory:
                inspection = Path(inspection_directory)
                if os.name == "posix":
                    os.chmod(inspection, 0o700)
                plan = renderer.inspect(
                    original_path,
                    media_type=str(request["source_media_type"]),
                    suffix=str(request["source_suffix"]),
                    signature=_signature(original_path),
                    input_bytes=int(original["size_bytes"]),
                    work_directory=inspection,
                    deadline_seconds=remaining_seconds(),
                )
            remaining_seconds()
            if [asdict(page) for page in plan.pages] != request["page_plan"]:
                raise OcrContractError(
                    "ocr_corrupt_input", "OCR page plan changed before execution"
                )
            pages = tuple(int(page) for page in request["pages"])
            validate_page_selection(
                pages,
                page_count=plan.page_count,
                max_pages=settings.limits.max_pages,
            )
            completed = self._completed_work_pages(work_directory, request)
            committed_pages = sorted(set(completed) & set(pages))
            current_processed = int(job["progress"]["processed"])
            current_skipped = int(job["progress"]["skipped"])
            current_errors = int(job["progress"]["errors"])
            while current_processed < len(committed_pages):
                current_processed += 1
                checkpoint(
                    {
                        "processed": current_processed,
                        "skipped": current_skipped,
                        "errors": current_errors,
                    }
                )
            newly_processed = 0
            for page_number in pages:
                if self._cancelled(str(job["id"])):
                    raise OcrContractError("ocr_cancelled", "OCR job was cancelled")
                if page_number in completed:
                    continue
                with tempfile.TemporaryDirectory(
                    prefix=f"ocr-page-{page_number:06d}-",
                    dir=self.temporary_root,
                ) as page_directory:
                    temporary = Path(page_directory)
                    if os.name == "posix":
                        os.chmod(temporary, 0o700)
                    rendered = renderer.render(
                        original_path,
                        plan,
                        page_number,
                        work_directory=temporary,
                        cancelled=lambda: self._cancelled(str(job["id"])),
                        deadline_seconds=remaining_seconds(),
                    )
                    source_page = OcrSourcePageIdentity(
                        original_sha256=str(request["original_sha256"]),
                        version_id=str(request["version_id"]),
                        page_number=page_number,
                        page_image_sha256=rendered.sha256,
                        source_media_type=str(request["source_media_type"]),
                    )
                    page_request = OcrPageRequest(
                        source_page=source_page,
                        staged_media_type="image/png",
                        page_width=rendered.width,
                        page_height=rendered.height,
                        settings_sha256=str(request["settings_sha256"]),
                        languages=settings.languages,
                        deadline_seconds=remaining_seconds(),
                        max_output_chars=settings.limits.max_output_chars_per_page,
                    )
                    if hasattr(adapter, "cancelled"):
                        adapter.cancelled = lambda: self._cancelled(str(job["id"]))
                    result = adapter.recognise_page(page_request, rendered.path)
                    remaining_seconds()
                    record = {
                        "schema_version": OCR_BUNDLE_SCHEMA_VERSION,
                        "derivation_key": request["derivation_key"],
                        "page_request": page_request.as_record(),
                        "result": result.as_record(),
                    }
                    completed[page_number] = self._checkpoint_work_page(
                        work_directory, request, page_number, record
                    )
                committed_pages.append(page_number)
                committed_pages.sort()
                newly_processed += 1
                current_processed += 1
                checkpoint(
                    {
                        "processed": current_processed,
                        "skipped": current_skipped,
                        "errors": current_errors,
                    }
                )
                self._verify_original(version, original, original_path)
                if _closed_tree_fingerprint(self.store.paths.knowledge) != canonical_before:
                    raise OcrContractError(
                        "ocr_internal_error", "OCR changed canonical knowledge"
                    )
            bundle_ref, manifest_bytes, bundle_created = self._promote_bundle(
                job,
                request,
                {page: completed[page] for page in pages},
            )
            artifact_key = f"{request['version_id']}:{request['derivation_key']}"
            artifact_id = f"derived_{uuid5(NAMESPACE_URL, artifact_key).hex}"
            artifact = DerivedArtifact(
                id=artifact_id,
                version_id=str(request["version_id"]),
                kind=OCR_ARTIFACT_KIND,
                generator=OCR_BUNDLE_GENERATOR,
                generator_version=OCR_BUNDLE_GENERATOR_VERSION,
                storage_ref=bundle_ref,
                checksum=hashlib.sha256(manifest_bytes).hexdigest(),
                created_at=utc_now(),
            )
            self.store.write_derived_artifact(artifact)
            edge = provenance_edge(
                "version",
                str(request["version_id"]),
                "ocr_derived_to",
                "derived_artifact",
                artifact.id,
            )
            provenance_id = edge.id
            self.store.write_derived_provenance(edge)
            if (
                self._verify_original(version, original, original_path)
                != original_before
                or _closed_tree_fingerprint(self.store.paths.knowledge)
                != canonical_before
            ):
                raise OcrContractError(
                    "ocr_internal_error",
                    "OCR changed the Original or canonical knowledge",
                )
            return {"processed": newly_processed, "skipped": 0, "errors": 0}
        except (OcrContractError, OcrUnavailableError) as exc:
            error_code = exc.code
            if provenance_id is not None:
                (self.store.paths.derived_provenance / f"{provenance_id}.json").unlink(
                    missing_ok=True
                )
            if artifact_id is not None:
                (self.store.paths.derived_artifacts / f"{artifact_id}.json").unlink(
                    missing_ok=True
                )
            if bundle_created and bundle_ref is not None:
                promoted = safe_instance_path(self.store.paths.root, bundle_ref)
                shutil.rmtree(promoted.parent, ignore_errors=True)
            bundle_ref = None
            raise
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            error_code = "ocr_internal_error"
            if provenance_id is not None:
                (self.store.paths.derived_provenance / f"{provenance_id}.json").unlink(
                    missing_ok=True
                )
            if artifact_id is not None:
                (self.store.paths.derived_artifacts / f"{artifact_id}.json").unlink(
                    missing_ok=True
                )
            if bundle_created and bundle_ref is not None:
                promoted = safe_instance_path(self.store.paths.root, bundle_ref)
                shutil.rmtree(promoted.parent, ignore_errors=True)
            bundle_ref = None
            raise OcrContractError(
                "ocr_internal_error", "OCR execution encountered an internal error"
            ) from exc
        finally:
            original_after = self._verify_original(version, original, original_path)
            canonical_after = _closed_tree_fingerprint(self.store.paths.knowledge)
            if original_after != original_before or canonical_after != canonical_before:
                error_code = "ocr_internal_error"
            self._write_run(
                job,
                request,
                state=(
                    "succeeded"
                    if error_code is None and bundle_ref is not None
                    else "cancelled"
                    if error_code == "ocr_cancelled"
                    else "failed"
                ),
                error_code=error_code,
                committed_pages=committed_pages,
                bundle_ref=bundle_ref,
                canonical_before=canonical_before,
                canonical_after=canonical_after,
                original_before=original_before,
                original_after=original_after,
            )
            if error_code is None and bundle_ref is not None:
                shutil.rmtree(work_directory, ignore_errors=True)

    def cancel(self, job_id: str) -> dict[str, Any]:
        self._ensure_directories()
        job = self.scheduler.journal.get_job(job_id)
        if job is None or job["job_kind"] != OCR_JOB_KIND:
            raise OcrContractError("ocr_contract_violation", "OCR job was not found")
        if job["status"] == "running":
            self.store._atomic_text(
                self.cancellations / f"{job_id}.request", "cancel\n"
            )
            return {"job": job, "cancellation_requested": True}
        return {
            "job": self.scheduler.journal.cancel(job_id),
            "cancellation_requested": False,
        }

    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.runs.exists():
            return []
        values = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in self.runs.glob("*.json")
            if path.is_file() and not path.is_symlink()
        ]
        return sorted(values, key=lambda item: str(item["job_id"]), reverse=True)[
            : min(max(limit, 0), 500)
        ]

    def get_run(self, job_id: str) -> dict[str, Any] | None:
        path = self.runs / f"{job_id}.json"
        if path.is_symlink() or not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None

    def list_bundles(self, version_id: str | None = None) -> list[dict[str, Any]]:
        result = []
        for artifact in self.store.list_derived_artifacts():
            if artifact.get("kind") != OCR_ARTIFACT_KIND:
                continue
            if version_id is not None and artifact.get("version_id") != version_id:
                continue
            path = safe_instance_path(self.store.paths.root, artifact["storage_ref"])
            if not path.is_file() or path.is_symlink():
                continue
            manifest_bytes = path.read_bytes()
            if hashlib.sha256(manifest_bytes).hexdigest() != artifact["checksum"]:
                raise OcrContractError(
                    "ocr_internal_error", "OCR bundle manifest checksum changed"
                )
            result.append(
                {"artifact": artifact, "manifest": json.loads(manifest_bytes)}
            )
        return sorted(
            result,
            key=lambda item: (
                str(item["artifact"]["version_id"]),
                str(item["manifest"]["derivation_key"]),
            ),
        )

    def remove(self, version_id: str) -> dict[str, Any]:
        version, _document, original, original_path = self._version_source(version_id)
        original_before = self._verify_original(version, original, original_path)
        canonical_before = _closed_tree_fingerprint(self.store.paths.knowledge)
        selected = self.list_bundles(version_id)
        if selected:
            latest = selected[-1]["manifest"]
            self.store._atomic_json(
                self.removals / f"{version_id}.json",
                {
                    "schema_version": OCR_BUNDLE_SCHEMA_VERSION,
                    "version_id": version_id,
                    "settings": latest["settings"],
                    "pages": [page["page_number"] for page in latest["pages"]],
                    "removed_at": utc_now(),
                },
            )
        removed_ids = []
        for item in selected:
            artifact = item["artifact"]
            manifest = item["manifest"]
            manifest_path = safe_instance_path(
                self.store.paths.root, artifact["storage_ref"]
            )
            shutil.rmtree(manifest_path.parent)
            (self.store.paths.derived_artifacts / f"{artifact['id']}.json").unlink(
                missing_ok=True
            )
            for edge in self.store.list_derived_provenance():
                if edge.get("to_id") == artifact["id"]:
                    (self.store.paths.derived_provenance / f"{edge['id']}.json").unlink(
                        missing_ok=True
                    )
            shutil.rmtree(
                self.work / str(manifest["derivation_key"]), ignore_errors=True
            )
            removed_ids.append(artifact["id"])
        original_after = self._verify_original(version, original, original_path)
        canonical_after = _closed_tree_fingerprint(self.store.paths.knowledge)
        if original_after != original_before or canonical_after != canonical_before:
            raise OcrContractError(
                "ocr_internal_error", "OCR removal changed canonical knowledge"
            )
        return {
            "version_id": version_id,
            "removed_artifact_ids": removed_ids,
            "original_sha256_before": original_before,
            "original_sha256_after": original_after,
            "canonical_fingerprint_before": canonical_before,
            "canonical_fingerprint_after": canonical_after,
            "canonical_mutation": False,
        }

    def rebuild(self, version_id: str) -> dict[str, Any]:
        selected = self.list_bundles(version_id)
        settings_record: Mapping[str, Any] | None = None
        pages: Sequence[int] = ()
        if selected:
            manifest = selected[-1]["manifest"]
            settings_record = manifest["settings"]
            pages = tuple(page["page_number"] for page in manifest["pages"])
        else:
            receipt = self.removals / f"{version_id}.json"
            if receipt.is_file() and not receipt.is_symlink():
                value = json.loads(receipt.read_text(encoding="utf-8"))
                settings_record = value["settings"]
                pages = tuple(value["pages"])
        if settings_record is None:
            raise OcrContractError(
                "ocr_contract_violation", "No prior OCR derivation can be rebuilt"
            )
        settings = ocr_settings_from_config({"ocr": settings_record})
        removal = self.remove(version_id)
        queued = self.queue(
            version_id,
            mode=settings.mode,
            languages=settings.languages,
            pages=pages if settings.mode == "selected-page" else (),
            rebuild_nonce=uuid4().hex,
        )
        return {"removal": removal, "queued": queued}


__all__ = [
    "OCR_ARTIFACT_KIND",
    "OCR_BUNDLE_GENERATOR",
    "OCR_BUNDLE_SCHEMA_VERSION",
    "OCR_JOB_KIND",
    "OcrJobManager",
]
