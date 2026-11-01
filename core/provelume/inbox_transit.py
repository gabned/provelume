"""Explicit Inbox roles, revision-bound exit permits and observed input actions.

Folder observers, acquisition records and scheduler receipts keep their existing
owners. These records describe input policy/evidence, never another work queue.
"""

import os
import re
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from .action_center_model import digest, json_bytes
from .folder_sources import FolderSourceManager
from .index_evidence import publish_once
from .instance_lifecycle import InstanceLifecycleManager
from .maintenance_local_files import (
    MaintenanceTargetError,
    file_identity,
    open_local_directory,
    open_local_file,
    stream_digest,
)
from .operations import OperationLedger
from .producer_index_evidence import describe_contribution, resolve_index_contribution
from .review_decisions import (
    assert_review_readable,
    checked_path,
    read_json,
    receipt_identifier,
    validate_receipt,
)
from .review_effects import (
    ABSENT,
    PreparedEffect,
    PreparedWrite,
    ReviewDenied,
    ReviewStale,
    ReviewUnavailable,
    relative_path,
)
from .review_routing import _Inputs
from .review_routing_model import identifier
from .storage import utc_now

ROOT = "state/review/inbox_transit"
EXITS = "state/inbox-transit/exits"
ADMISSIONS = "state/inbox-transit/admissions"
MAX_INPUTS = 1000
MAX_BYTES = 25 * 1024 * 1024
POLICY_FIELDS = {"schema_version", "id", "revision", "mode", "source_revision",
                 "root_binding", "existing_inputs", "last_receipt", "principal", "updated_at"}


def policy_path(source_id):
    identifier(source_id, "source")
    return f"{ROOT}/policies/{source_id}.json"


def validate_policy(value):
    if (not isinstance(value, dict) or set(value) != POLICY_FIELDS
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or type(value["revision"]) is not int or not 1 <= value["revision"] <= 10000
            or value["mode"] not in {"transit", "keep"}
            or value["principal"] not in {"local_browser", "local_cli"}
            or re.fullmatch(r"[0-9a-f]{64}", str(value["source_revision"])) is None
            or re.fullmatch(r"(?:posix\.file-id\.v1:[0-9a-f]{32}|"
                            r"win32\.file-id\.v1:[0-9a-f]{48})",
                            str(value["root_binding"])) is None
            or re.fullmatch(r"review_[0-9a-f]{32}", str(value["last_receipt"])) is None
            or not isinstance(value["updated_at"], str)
            or datetime.fromisoformat(value["updated_at"]).tzinfo is None):
        raise ReviewUnavailable("Inbox policy has an invalid closed schema")
    identifier(value["id"], "source")
    if not isinstance(value["existing_inputs"], list) or len(value["existing_inputs"]) > MAX_INPUTS:
        raise ReviewUnavailable("Inbox conversion inventory exceeds its bound")
    for item in value["existing_inputs"]:
        validate_input(item)
    return value


def _source(store, source_id):
    from .folder_settings import FolderSettingsManager

    identifier(source_id, "source")
    manager = FolderSourceManager(store)
    source, config, folder = manager._configured(source_id)
    if folder["source_class"] != "local":
        raise ReviewDenied("Inbox exit requires an explicitly selected local folder")
    root = store.source_path(source_id)
    if root is None:
        raise ReviewUnavailable("Inbox folder is unavailable")
    manager.selected_for_read(root)
    managed = FolderSettingsManager(store).read().managed_path
    if root.resolve().is_relative_to(managed.resolve()) or managed.resolve().is_relative_to(
            root.resolve()):
        raise ReviewDenied("Inbox input cannot overlap managed acquisition copies")
    return root, digest({"source": source, "config": config}), folder


def _input(root, locator):
    relative_path(locator)
    path = root / Path(*locator.split("/"))
    with open_local_file(path) as handle:
        identity = file_identity(handle)
        if os.fstat(handle.fileno()).st_nlink != 1:
            raise ReviewDenied("Inbox input cannot alias another file through a hard link")
        checksum, size = stream_digest(handle, MAX_BYTES)
        if identity != file_identity(handle):
            raise ReviewStale("Inbox input changed during observation")
    return {"locator": locator, "identity": identity, "sha256": checksum, "size_bytes": size}


def validate_input(value):
    if (not isinstance(value, dict) or set(value) != {
            "locator", "identity", "sha256", "size_bytes"}
            or re.fullmatch(r"[0-9a-f]{64}", str(value["sha256"])) is None
            or type(value["size_bytes"]) is not int or not 0 <= value["size_bytes"] <= MAX_BYTES
            or not isinstance(value["identity"], dict) or set(value["identity"]) != {
                "device", "inode", "size_bytes", "mtime_ns", "ctime_ns"}
            or any(type(v) is not int or v < 0 for v in value["identity"].values())
            or value["identity"]["size_bytes"] != value["size_bytes"]):
        raise ReviewUnavailable("Inbox input binding is invalid")
    relative_path(value["locator"])
    return value


def inventory(root):
    """Bound traversal before materializing/sorting; aliases are refused, not followed."""
    result, pending, entries, size = [], [root], 0, 0
    while pending:
        directory = pending.pop()
        with open_local_directory(directory), os.scandir(directory) as children:
            for entry in children:
                entries += 1
                if entries > MAX_INPUTS:
                    raise ReviewUnavailable("Inbox preview exceeds its 1000-entry bound")
                path = Path(entry.path)
                if path.is_symlink() or path.is_junction():
                    raise ReviewDenied("Inbox preview cannot traverse a linked entry")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    item = _input(root, path.relative_to(root).as_posix())
                    size += item["size_bytes"]
                    if size > MAX_BYTES:
                        raise ReviewUnavailable("Inbox preview exceeds its 25 MiB bound")
                    result.append(item)
                else:
                    raise ReviewDenied("Inbox input must be a regular file")
    return sorted(result, key=lambda row: row["locator"])


class InboxTransitReview:
    domain = "inbox_transit"
    actions = ("save_policy", "release")

    def __init__(self, store):
        self.store = store
        self.instance_id = store.read_config()["instance"]["id"]

    def history_record(self, receipt_id, inputs=None):
        if re.fullmatch(r"review_[0-9a-f]{32}", str(receipt_id)) is None:
            raise ReviewUnavailable("Invalid Inbox decision identity")
        inputs = inputs or _Inputs(self.store)
        receipt = inputs.record(f"state/review/receipts/{receipt_id}.json")
        validate_receipt(receipt, instance_id=self.instance_id)
        path = f"{ROOT}/history/{receipt['subject']}/{receipt_id}.json"
        row = inputs.record(path)
        if (receipt["domain"] != self.domain or receipt["history_ref"] != path
                or receipt["history_sha256"] != inputs.hashes[path]
                or set(row) != {"schema_version", "domain", "subject", "action", "before",
                                "after", "execution", "request_id", "principal", "recorded_at"}
                or row["schema_version"] != 1 or row["action"] not in self.actions
                or any(row[k] != receipt[k] for k in
                       ("domain", "subject", "action", "request_id", "principal", "recorded_at"))
                or receipt["result"] != {"policy": row["after"], "execution": row["execution"]}):
            raise ReviewUnavailable("Inbox decision differs from its committed review receipt")
        for policy in (row["before"], row["after"]):
            if policy is not None:
                validate_policy(policy)
                if policy["id"] != row["subject"]:
                    raise ReviewUnavailable("Inbox history changes another Source")
        if row["action"] == "save_policy":
            if row["execution"] is not None or row["after"]["last_receipt"] != receipt_id:
                raise ReviewUnavailable("Inbox conversion cannot release existing inputs")
        elif row["before"] != row["after"] or not isinstance(row["execution"], dict):
            raise ReviewUnavailable("Inbox release cannot change policy")
        return row, receipt

    def policy(self, source_id, inputs=None):
        assert_review_readable(self.store)
        inputs = inputs or _Inputs(self.store)
        value = inputs.record(policy_path(source_id), optional=True)
        current, seen = value, set()
        while current is not None:
            validate_policy(current)
            if current["last_receipt"] in seen or len(seen) >= 10000:
                raise ReviewUnavailable("Inbox policy history is cyclic or exceeds its bound")
            seen.add(current["last_receipt"])
            row, _ = self.history_record(current["last_receipt"], inputs)
            previous = row["before"]
            if (row["action"] != "save_policy" or row["subject"] != source_id
                    or row["after"] != current
                    or current["revision"] != (
                        1 if previous is None else previous["revision"] + 1)):
                raise ReviewUnavailable("Inbox policy has no confirmed revision chain")
            current = previous
        assert_review_readable(self.store)
        return value

    def current(self, source_id):
        policy = self.policy(source_id)
        root, source_revision, folder = _source(self.store, source_id)
        if policy is None or policy["source_revision"] != source_revision:
            raise ReviewStale("Inbox Source configuration changed; review the policy again")
        with open_local_directory(root) as opened:
            if opened[1] != policy["root_binding"]:
                raise ReviewStale("Inbox root was replaced or restored")
        return policy, root, folder

    def release_input(self, source_id, selected):
        if not isinstance(selected, dict) or set(selected) != {
                "acquisition_id", "producer", "job_id"}:
            raise ReviewDenied("Select an acquisition and its exact index producer/job")
        for key, prefix in (("acquisition_id", "acq"), ("job_id", "job")):
            if re.fullmatch(prefix + r"_[0-9a-f]{32}", str(selected[key])) is None:
                raise ReviewDenied("Invalid Inbox acquisition or job identity")
        acquisition = read_json(
            self.store, f"knowledge/acquisitions/{selected['acquisition_id']}.json")
        policy, root, folder = self.current(source_id)
        if (policy["mode"] != "transit" or folder["lifecycle_state"] != "enabled"
                or acquisition is None or acquisition["source_id"] != source_id
                or acquisition["outcome"] not in {
                    "created", "version_created", "version_reused", "extraction_recovered",
                    "unchanged"}):
            raise ReviewDenied("Select a preserved acquisition in an enabled transit Inbox")
        contribution, _row = describe_contribution(
            self.store, acquisition["document_id"], acquisition["version_id"])
        if (acquisition["content_hash"] != contribution["original_sha256"]
                or contribution["source_id"] != source_id):
            raise ReviewStale("Acquisition no longer selects its preserved Original")
        proof = resolve_index_contribution(self.store, selected["producer"], selected["job_id"],
                                           acquisition["document_id"])
        from .ocr_sources import SourceOcrReview
        from .scheduler import SchedulerStore

        admission = read_json(self.store, f"{ADMISSIONS}/{acquisition['id']}.json")
        ocr_policy = SourceOcrReview(self.store).policy(source_id)
        version = read_json(self.store, f"knowledge/versions/{acquisition['version_id']}.json")
        ocr_required = (version["media_type"] == "application/pdf" and (
            (ocr_policy is not None and ocr_policy["enabled"])
            or (admission is not None and admission["ocr_required"])))
        if ocr_required and SchedulerStore(self.store).get_job(selected["job_id"])[
                "job_kind"] != "ocr.execute":
            raise ReviewUnavailable("The required OCR stage has no exact terminal proof")
        observed = _input(root, acquisition["locator"])
        if (observed["sha256"] != contribution["original_sha256"]
                or observed["size_bytes"] != contribution["original_size_bytes"]):
            raise ReviewStale("Inbox input differs from its preserved Original")
        return {"selection": selected, "policy": policy, "acquisition": acquisition,
                "input": observed, "contribution": contribution, "proof": proof}

    def preview(self, subject, action, parameters):
        inputs = _Inputs(self.store)
        before = self.policy(subject, inputs)
        root, source_revision, _folder = _source(self.store, subject)
        with open_local_directory(root) as opened:
            root_binding = opened[1]
            files = inventory(root)
        after, execution = before, None
        if action == "save_policy":
            if FolderSourceManager(self.store).observer(subject)["active_run_id"] is not None:
                raise ReviewUnavailable("Reconcile the folder's owned run before conversion")
            if set(parameters) != {"mode"} or parameters["mode"] not in {"transit", "keep"}:
                raise ReviewDenied("Choose transit or keep for this Inbox")
            if before is None and len(inputs.inventory(f"{ROOT}/policies", 128)) >= 128:
                raise ReviewUnavailable("Inbox policy inventory is full")
            after = {"schema_version": 1, "id": subject,
                     "revision": 1 if before is None else before["revision"] + 1,
                     "mode": parameters["mode"], "source_revision": source_revision,
                     "root_binding": root_binding, "existing_inputs": files}
        elif action == "release":
            if (set(parameters) != {"items"} or not isinstance(parameters["items"], list)
                    or not 1 <= len(parameters["items"]) <= 100):
                raise ReviewDenied("Review between 1 and 100 exact Inbox inputs")
            selected = [self.release_input(subject, row) for row in parameters["items"]]
            if len({row["input"]["locator"] for row in selected}) != len(selected):
                raise ReviewDenied("An Inbox release cannot select an input twice")
            execution = {"source_id": subject, "inventory_sha256": digest(files),
                         "items": selected}
        else:
            raise ReviewDenied("Unsupported Inbox action")
        observation = {"source_revision": source_revision, "root_binding": root_binding,
                       "files": files, "before": before, "execution": execution}
        return {"input_revision": digest(observation), "before": before, "after": after,
                "execution": execution, "preimage": inputs.hashes[policy_path(subject)],
                "evidence": {"mode": parameters.get("mode"), "files_present": len(files),
                             "backlog": files, "selected": execution,
                             "existing_inputs_released": False},
                "reason": "Explicit Inbox role and exact input exit consent",
                "confidence": None,
                "impact": "Exit only unchanged input copies after current per-Version proof",
                "reversibility": "Keep stops future exits; consumed copies are not recreated"}

    def allowed_paths(self, plan, request_id):
        receipt = receipt_identifier(self.instance_id, request_id)
        paths = {f"{ROOT}/history/{plan['subject']}/{receipt}.json"}
        if plan["action"] == "save_policy":
            paths.add(policy_path(plan["subject"]))
        return frozenset(paths)

    def prepare(self, plan, *, request_id, principal, recorded_at):
        if principal not in {"local_browser", "local_cli"}:
            raise ReviewDenied("Inbox decisions require explicit local confirmation")
        data = plan["provider"]
        receipt = receipt_identifier(self.instance_id, request_id)
        after, writes = data["after"], []
        if plan["action"] == "save_policy":
            after = {**after, "last_receipt": receipt, "principal": principal,
                     "updated_at": recorded_at}
            validate_policy(after)
            writes.append(PreparedWrite(policy_path(plan["subject"]), data["preimage"],
                                        json_bytes(after)))
        path = f"{ROOT}/history/{plan['subject']}/{receipt}.json"
        row = {"schema_version": 1, "domain": self.domain, "subject": plan["subject"],
               "action": plan["action"], "before": data["before"], "after": after,
               "execution": data["execution"], "request_id": request_id,
               "principal": principal, "recorded_at": recorded_at}
        writes.append(PreparedWrite(path, ABSENT, json_bytes(row), immutable=True))
        return PreparedEffect(self.domain, plan["action"], tuple(writes),
                              {"policy": after, "execution": data["execution"]}, path,
                              data["impact"], data["reversibility"])


class InboxTransit:
    def __init__(self, store):
        self.store = store
        self.review = InboxTransitReview(store)

    def _authority(self, source_id, action):
        from .review_authority import ReviewAuthority
        from .review_integrity import CAPABILITIES

        authority = ReviewAuthority(self.store, CAPABILITIES).resolve(
            self.review.domain, source_id, action)
        if authority["mode"] != "confirm-each":
            raise ReviewDenied("Current local Inbox authority is disabled")
        return authority

    def admit(self, acquisition):
        """Freeze future-work consent at ingestion, never infer it from a rescan."""
        from .ocr_contract import settings_fingerprint
        from .ocr_sources import SourceOcrReview, settings

        source_id = acquisition["source_id"]
        policy = self.review.policy(source_id)
        if (policy is None or policy["mode"] != "transit"
                or acquisition["outcome"] == "unchanged"
                or datetime.fromisoformat(acquisition["observed_at"])
                < datetime.fromisoformat(policy["updated_at"])):
            return None
        policy, root, folder = self.review.current(source_id)
        if folder["lifecycle_state"] != "enabled":
            return None
        self._authority(source_id, "save_policy")
        observed = _input(root, acquisition["locator"])
        if observed in policy["existing_inputs"]:
            return None
        if observed["sha256"] != acquisition["content_hash"]:
            raise ReviewStale("Inbox input changed after preservation")
        value = {"schema": "inbox-admission/v1", "instance_id": self.review.instance_id,
                 "acquisition": acquisition, "policy": policy, "input": observed,
                 "ocr_required": bool(
                     (ocr_policy := SourceOcrReview(self.store).policy(source_id))
                     and ocr_policy["enabled"] and self.store.read_canonical(
                         "versions", acquisition["version_id"])["media_type"] == "application/pdf"),
                 "ocr_policy_revision": digest(SourceOcrReview(self.store).policy(source_id)),
                 "ocr_settings_revision": settings_fingerprint(settings(self.store))}
        publish_once(self.store, f"{ADMISSIONS}/{acquisition['id']}.json", value)
        return value

    def after_job_locked(self, job):
        """Existing scheduler owner invokes this only after its terminal receipt.

        No new watcher, job, retry authority or scheduling queue is introduced.
        An absent/changed proof leaves an input pending for explicit recovery.
        """
        from .ocr_contract import settings_fingerprint
        from .ocr_sources import SourceOcrReview, settings

        if job["status"] != "succeeded" or job["job_kind"] not in {
                "source.refresh", "ocr.execute", "processing.execute",
                "search.reindex", "search.reindex.incremental"}:
            return []
        producer = "maintenance" if job["job_kind"].startswith("search.") else "processing"
        results = []
        root = checked_path(self.store, ADMISSIONS)
        if not root.exists():
            return results
        for count, path in enumerate(root.iterdir(), 1):
            if count > 10000:
                raise ReviewUnavailable("Inbox admission history exceeds its 10000-record bound")
            admission = read_json(self.store, f"{ADMISSIONS}/{path.name}")
            validate_admission(admission, path.stem, self.review.instance_id)
            acquisition = admission["acquisition"]
            source_id = acquisition["source_id"]
            if job["scope"]["kind"] == "source" and job["scope"]["id"] != source_id:
                continue
            try:
                self._authority(source_id, "save_policy")
                policy, _root, _folder = self.review.current(source_id)
                if (policy != admission["policy"] or policy["mode"] != "transit"
                        or digest(SourceOcrReview(self.store).policy(source_id))
                        != admission["ocr_policy_revision"]
                        or settings_fingerprint(settings(self.store))
                        != admission["ocr_settings_revision"]):
                    continue
                selected = {"acquisition_id": acquisition["id"], "producer": producer,
                            "job_id": job["id"]}
                item = self.review.release_input(source_id, selected)
                if item["input"] != admission["input"]:
                    continue
                key = digest({"receipt": policy["last_receipt"], "item": item})
                existing = read_json(self.store, f"{EXITS}/{key}/result.json")
                if existing is not None:
                    _validate_exit_result(existing, key)
                    continue
                results.append(self._exit(key, item, policy["last_receipt"],
                                          authority_action="save_policy"))
            except (ValueError, OSError):
                # Preservation/processing success is independent from input exit.
                # The retained admission/intent remains visible to status/recovery.
                continue
        return results

    def release(self, receipt_id):
        with InstanceLifecycleManager(self.store)._hold(purpose="inbox-input-exit"):
            row, receipt = self.review.history_record(receipt_id)
            if row["action"] != "release":
                raise ReviewDenied("Policy conversion does not release the existing backlog")
            execution = row["execution"]
            source_id = row["subject"]
            self._authority(source_id, "release")
            # Revalidate the entire preview before the first effect. Resumption
            # excludes only exact actions with a retained successful result.
            pending, results = [], []
            for item in execution["items"]:
                key = digest({"receipt": receipt["id"], "item": item})
                result = read_json(self.store, f"{EXITS}/{key}/result.json")
                if result is not None:
                    _validate_exit_result(result, key)
                    results.append(result)
                else:
                    pending.append((key, item))
            if not pending:
                return results
            policy, root, _folder = self.review.current(source_id)
            if policy != row["after"]:
                raise ReviewStale("Inbox policy changed after the release preview")
            current_inventory = inventory(root)
            original_inventory = [*current_inventory]
            for item in execution["items"]:
                key = digest({"receipt": receipt["id"], "item": item})
                if any(r["id"] == key and r["outcome"] == "input_exited" for r in results):
                    original_inventory.append(item["input"])
            if digest(sorted(original_inventory, key=lambda r: r["locator"])) != execution[
                    "inventory_sha256"]:
                raise ReviewStale("Inbox inventory changed; request a fresh release preview")
            for _key, item in pending:
                if self.review.release_input(source_id, item["selection"]) != item:
                    raise ReviewStale("Inbox release evidence is no longer current")
            for key, item in pending:
                results.append(self._exit(key, item, receipt["id"]))
            return results

    def _exit(self, key, item, receipt_id, *, authority_action="release"):
        from .inbox_exit_files import guarded_input_exit, remove_empty_directory

        source_id = item["acquisition"]["source_id"]
        policy, root, _folder = self.review.current(source_id)
        if policy != item["policy"]:
            raise ReviewStale("Inbox policy changed before exit")
        path = root / item["input"]["locator"]
        directory = f"{EXITS}/{key}"
        ledger = OperationLedger(self.store)
        intent = read_json(self.store, f"{directory}/intent.json")
        if intent is None:
            operation = ledger.start("inbox.exit", "Exit a completed Inbox input",
                                     related={"source_id": source_id,
                                              "acquisition_id": item["acquisition"]["id"]})
            intent = {"schema": "inbox-exit-intent/v1", "id": key,
                      "receipt_id": receipt_id, "operation_id": operation.id,
                      "item": item}
            publish_once(self.store, f"{directory}/intent.json", intent)
        _validate_exit_intent(intent, key)
        if intent["item"] != item or intent["receipt_id"] != receipt_id:
            raise ReviewUnavailable("Another exact input owns this exit intent")
        directories, removed = [], 0
        with ExitStack() as stack:
            opened = stack.enter_context(open_local_directory(root))
            if opened[1] != policy["root_binding"]:
                raise ReviewStale("Inbox root changed before exit")
            # Pin the Original and active index against external replacement or
            # writes on Windows, in addition to the application's lifecycle lock.
            original = read_json(self.store,
                                 f"knowledge/originals/{item['contribution']['original_id']}.json")
            for relative in sorted(_evidence_paths(self.store, item) | {
                    original["storage_ref"], "indexes/search.sqlite3", "provelume.yml"}):
                stack.enter_context(open_local_file(checked_path(self.store, relative)))
            parent = path.parent
            while parent != root:
                with open_local_directory(parent) as opened_parent:
                    directories.append((parent, opened_parent[1]))
                parent = parent.parent
            with guarded_input_exit(path, item["input"]["identity"]) as (handle, remove):
                if stream_digest(handle, MAX_BYTES) != (item["input"]["sha256"],
                                                        item["input"]["size_bytes"]):
                    raise ReviewStale("The guarded input bytes changed")
                # Input is held exclusively: avoid reopening it in this last check.
                proof = resolve_index_contribution(self.store, item["selection"]["producer"],
                                                   item["selection"]["job_id"],
                                                   item["acquisition"]["document_id"])
                contribution = describe_contribution(
                    self.store, item["acquisition"]["document_id"],
                    item["acquisition"]["version_id"])[0]
                if proof != item["proof"] or contribution != item["contribution"]:
                    raise ReviewStale("Final index evidence changed before exit")
                self._authority(source_id, authority_action)
                if self.review.current(source_id)[0] != policy:
                    raise ReviewStale("Final Inbox policy changed before exit")
                remove()
            for parent, binding in directories:
                try:
                    remove_empty_directory(parent, binding)
                except (MaintenanceTargetError, OSError):
                    break
                removed += 1
        if path.exists():
            # A new entry or unconfirmed close is not removed by a second action.
            raise ReviewUnavailable("Input disposition outcome requires reconciliation")
        result = {"schema": "inbox-exit-result/v1", "id": key,
                  "operation_id": intent["operation_id"], "outcome": "input_exited",
                  "recorded_at": utc_now(), "empty_directories_removed": removed}
        publish_once(self.store, f"{directory}/result.json", result)
        operation = ledger.get(intent["operation_id"])
        if operation["status"] == "running":
            ledger.close(intent["operation_id"], status="completed",
                         summary="Verified completed input exited; Original remains preserved",
                         metrics={"inputs_exited": 1})
        return result

    def status(self, source_id):
        policy = self.review.policy(source_id)
        root, _revision, _folder = _source(self.store, source_id)
        files = inventory(root)
        actions = []
        exits = checked_path(self.store, EXITS)
        if exits.exists():
            for count, directory in enumerate(exits.iterdir(), 1):
                if count > 10000:
                    raise ReviewUnavailable("Inbox action history exceeds its bound")
                intent = read_json(self.store, f"{EXITS}/{directory.name}/intent.json")
                _validate_exit_intent(intent, directory.name)
                if intent["item"]["acquisition"]["source_id"] != source_id:
                    continue
                result = read_json(self.store, f"{EXITS}/{directory.name}/result.json")
                if result is not None:
                    _validate_exit_result(result, directory.name)
                present = any(r["locator"] == intent["item"]["input"]["locator"] for r in files)
                actions.append({"id": intent["id"], "operation_id": intent["operation_id"],
                                "acquisition_id": intent["item"]["acquisition"]["id"],
                                "outcome": ("input_exited" if result is not None else
                                            "input_retained" if present else "outcome_unknown")})
        return {"source_id": source_id, "role": "folder" if policy is None else "inbox",
                "mode": "keep" if policy is None else policy["mode"],
                "files_present": len(files), "files": files,
                "exit_actions": sorted(actions, key=lambda a: a["id"]),
                "exit_supported": os.name == "nt", "policy": policy}


def validate_admission(value, acquisition_id, instance_id):
    if (not isinstance(value, dict) or set(value) != {
            "schema", "instance_id", "acquisition", "policy", "input",
            "ocr_policy_revision", "ocr_settings_revision", "ocr_required"}
            or value["schema"] != "inbox-admission/v1" or value["instance_id"] != instance_id
            or re.fullmatch(r"acq_[0-9a-f]{32}", str(acquisition_id)) is None
            or value["acquisition"]["id"] != acquisition_id
            or value["policy"]["id"] != value["acquisition"]["source_id"]
            or value["input"]["sha256"] != value["acquisition"]["content_hash"]):
        raise ReviewUnavailable("Inbox admission has an invalid closed identity")
    validate_policy(value["policy"])
    validate_input(value["input"])
    if type(value["ocr_required"]) is not bool:
        raise ReviewUnavailable("Inbox admission has an invalid required-stage binding")
    for key in ("ocr_policy_revision", "ocr_settings_revision"):
        if re.fullmatch(r"[0-9a-f]{64}", str(value[key])) is None:
            raise ReviewUnavailable("Inbox admission has an invalid policy revision")
    return value


def _evidence_paths(store, item):
    """Pin the exact selected proof/text/identity records through final disposition."""
    from .index_evidence import ROOTS
    from .ocr_contract import OCR_ARTIFACT_KIND
    from .ocr_selection import selection_path

    acquisition = item["acquisition"]
    paths = {f"knowledge/acquisitions/{acquisition['id']}.json",
             f"knowledge/sources/{acquisition['source_id']}.json",
             f"knowledge/documents/{acquisition['document_id']}.json",
             f"knowledge/versions/{acquisition['version_id']}.json",
             f"knowledge/originals/{item['contribution']['original_id']}.json",
             policy_path(acquisition["source_id"]),
             f"state/scheduler/receipts/{item['proof']['receipt_id']}.json",
             f"state/scheduler/jobs/{item['selection']['job_id']}.json"}
    producer, job_id = item["selection"]["producer"], item["selection"]["job_id"]
    paths.add(f"{ROOTS[producer]}/{job_id}/publication_a"
              f"{item['proof']['publication']['attempt']}.json")
    pending = [item["proof"], item["contribution"]]
    count = 0
    while pending:
        value = pending.pop()
        count += 1
        if count > 10000:
            raise ReviewUnavailable("Selected exit evidence exceeds its traversal bound")
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith("_ref") and isinstance(child, str):
                    if not child.startswith(("state/", "originals/", "knowledge/")):
                        raise ReviewUnavailable("Selected proof has an unsupported reference")
                    paths.add(child)
                if key in {"id", "artifact_id"} and re.fullmatch(
                        r"derived_[0-9a-f]{32}", str(child)):
                    paths.add(f"state/derived/artifacts/{child}.json")
                pending.append(child)
            if value.get("kind") == OCR_ARTIFACT_KIND and isinstance(value.get("storage_ref"), str):
                pending.append(read_json(store, value["storage_ref"]))
        elif isinstance(value, list):
            pending.extend(value)
    if item["contribution"]["profile"] in {
            "embedded", "ocr-complete", "ocr-accepted", "limited-metadata"}:
        paths.add(selection_path(acquisition["version_id"]))
    return paths


def _validate_exit_intent(value, key):
    if (not isinstance(value, dict) or set(value) != {
            "schema", "id", "receipt_id", "operation_id", "item"}
            or value["schema"] != "inbox-exit-intent/v1" or value["id"] != key
            or key != digest({"receipt": value["receipt_id"], "item": value["item"]})
            or re.fullmatch(r"op_[0-9a-f]{32}", str(value["operation_id"])) is None):
        raise ReviewUnavailable("Inbox exit intent is invalid")


def _validate_exit_result(value, key):
    if (not isinstance(value, dict) or set(value) != {
            "schema", "id", "operation_id", "outcome", "recorded_at",
            "empty_directories_removed"}
            or value["schema"] != "inbox-exit-result/v1" or value["id"] != key
            or value["outcome"] != "input_exited"
            or type(value["empty_directories_removed"]) is not int
            or not 0 <= value["empty_directories_removed"] <= MAX_INPUTS
            or re.fullmatch(r"op_[0-9a-f]{32}", str(value["operation_id"])) is None
            or not isinstance(value["recorded_at"], str)
            or datetime.fromisoformat(value["recorded_at"]).tzinfo is None):
        raise ReviewUnavailable("Inbox exit result is invalid")


def inbox_transit_findings(store):
    findings = []
    try:
        review = InboxTransitReview(store)
        for source_id in _Inputs(store).inventory(f"{ROOT}/policies", 128):
            review.policy(source_id)
        admissions = checked_path(store, ADMISSIONS)
        if admissions.exists():
            for count, path in enumerate(admissions.iterdir(), 1):
                if count > 10000 or path.suffix != ".json":
                    raise ReviewUnavailable("Invalid Inbox admission inventory")
                validate_admission(read_json(store, f"{ADMISSIONS}/{path.name}"), path.stem,
                                   review.instance_id)
        root = checked_path(store, EXITS)
        if root.exists():
            for count, directory in enumerate(root.iterdir(), 1):
                if count > 10000 or re.fullmatch(r"[0-9a-f]{64}", directory.name) is None:
                    raise ReviewUnavailable("Inbox exit inventory is invalid or exceeds its bound")
                relative = f"{EXITS}/{directory.name}"
                for index, path in enumerate(checked_path(store, relative).iterdir()):
                    if index >= 2 or path.name not in {"intent.json", "result.json"}:
                        raise ReviewUnavailable("Unknown Inbox exit evidence")
                intent = read_json(store, f"{relative}/intent.json")
                _validate_exit_intent(intent, directory.name)
                history, _receipt = review.history_record(intent["receipt_id"])
                item = intent["item"]
                validate_input(item["input"])
                validate_policy(item["policy"])
                if history["action"] == "release":
                    if item not in history["execution"]["items"]:
                        raise ReviewUnavailable("Inbox exit has no exact reviewed permit")
                else:
                    acquisition = item["acquisition"]
                    admission = read_json(store, f"{ADMISSIONS}/{acquisition['id']}.json")
                    validate_admission(admission, acquisition["id"], review.instance_id)
                    if (history["after"] != item["policy"]
                            or admission["policy"] != item["policy"]
                            or admission["acquisition"] != acquisition
                            or admission["input"] != item["input"]):
                        raise ReviewUnavailable("Inbox exit has no exact future-work consent")
                operation = OperationLedger(store).get(intent["operation_id"])
                if operation is None or operation["kind"] != "inbox.exit" or operation[
                        "related"] != {"source_id": item["acquisition"]["source_id"],
                                       "acquisition_id": item["acquisition"]["id"]}:
                    raise ReviewUnavailable("Inbox exit has no corresponding operation")
                result = read_json(store, f"{relative}/result.json")
                if result is not None:
                    _validate_exit_result(result, directory.name)
                    if result["operation_id"] != intent["operation_id"]:
                        raise ReviewUnavailable("Inbox exit result selects another operation")
    except (ValueError, TypeError, KeyError, OSError, MaintenanceTargetError) as exc:
        findings.append({"code": "inbox_transit_invalid", "path": ROOT, "message": str(exc)})
    return findings
