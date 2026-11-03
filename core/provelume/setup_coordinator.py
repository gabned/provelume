"""K: explicit setup actions, revision-bound application and read-only resume.

Device progress holds references only. Submitted selections become bounded action
records; they do not authorize replay on reload. Existing producers retain their
own consent, transaction, evidence and recovery contracts.
"""

import hashlib
import os
import re
import sqlite3
import sys
import tempfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from .action_center_model import digest
from .index_evidence import publish_once
from .instance_lifecycle import InstanceLifecycleManager
from .maintenance_local_files import (
    absolute_local_path,
    open_local_directory,
    prepare_local_directory,
)
from .ocr_contract import require_ocr_available
from .operations import OperationLedger
from .review_effects import ReviewConflict, ReviewDenied, ReviewUnavailable
from .scheduler_model import schedule_payload
from .setup_progress import STEPS, SetupProgress, SetupProgressError
from .setup_source_scope import _baseline, _source_id, baseline_preview, install_baseline
from .setup_trial_authority import operation_id, read_record
from .setup_trials import SetupTrials
from .shell_settings import LANGUAGES

ROOT = "state/setup-actions"
ACTIVE = ROOT + "/active"
CHOICES = {"source_id", "language", "retention", "ocr", "languages", "automation", "login_startup"}
POLICY_CLOCKS = {"created_at", "updated_at", "last_evaluated_at", "next_nominal_at", "next_due_at"}


def _without(value, names):
    return None if value is None else {key: item for key, item in value.items() if key not in names}


def _policy(value):
    return _without(value, {"updated_at", "enabled_at", "last_receipt", "principal"})


def _permission_probe(root):
    with tempfile.NamedTemporaryFile(prefix=".provelume-setup-", dir=root) as probe:
        expected = b"Provelume synthetic permission probe\n"
        probe.write(expected)
        probe.flush()
        os.fsync(probe.fileno())
        probe.seek(0)
        if probe.read() != expected:
            raise ReviewUnavailable("setup_permission_failed")
        name = probe.name
    if Path(name).exists():
        raise ReviewUnavailable("setup_permission_failed")


def validate_choices(value):
    if (not isinstance(value, dict) or set(value) != CHOICES
            or value["language"] not in LANGUAGES or value["retention"] not in {"keep", "transit"}
            or type(value["ocr"]) is not bool
            or value["languages"] not in [["eng"], ["ita"], ["eng", "ita"]]
            or value["automation"] not in {"preserve", "manual", "automatic"}
            or type(value["login_startup"]) is not bool):
        raise ReviewDenied("setup_choices_invalid")
    _source_id(value["source_id"])
    return value


def startup_available():
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def startup_observed(enabled):
    """Read the actual HKCU value; a saved checkbox alone is not startup proof."""
    if not startup_available():
        return not enabled
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            value, kind = winreg.QueryValueEx(key, "Provelume")
    except FileNotFoundError:
        return not enabled
    return enabled and kind == winreg.REG_SZ and value == f'"{sys.executable}" --tray'


def assert_admission_ready(store, source_id):
    """A partial explicit Apply cannot release ordinary Source/AI admission."""
    value = read_record(store, f"{ACTIVE}/{_source_id(source_id)}.json")
    if value is None:
        return
    if (set(value) != {"schema", "source_id", "operation_id", "instance_id"}
            or value["schema"] != "setup-admission-barrier/v1"
            or value["source_id"] != source_id
            or value["instance_id"] != store.read_config()["instance"]["id"]):
        raise ReviewUnavailable("setup_apply_needs_review")
    op = OperationLedger(store).get(operation_id(value["operation_id"]))
    if op is None or op["kind"] != "setup.apply" or op["related"] != {"source_id": source_id}:
        raise ReviewUnavailable("setup_apply_needs_review")
    if op["status"] == "completed":
        return
    released = read_record(store, f"{ROOT}/releases/{op['id']}.json")
    if released is not None:
        validate_release(store, released)
        source = store.read_config()["sources"][source_id]
        from .scheduler import SchedulerStore

        policy = SchedulerStore(store).get_policy(source["folder"]["policy_id"])
        pause = OperationLedger(store).get(released["operation_id"])
        if (op["status"] == "completed_with_errors" and pause["status"] == "completed"
                and released["id"] == op["id"] and released["source_id"] == source_id
                and source["folder"]["lifecycle_state"] == "paused"
                and policy is not None and policy["state"] == "paused"):
            return
    if op["status"] != "completed":
        raise ReviewUnavailable("setup_apply_pending")


class SetupCoordinator:
    def __init__(self, instance, shell_manager):
        self.instance = instance
        self.store = instance.store
        self.shell = shell_manager
        self.progress = SetupProgress(
            shell_manager.path, self.store.read_config()["instance"]["id"])
        self.ledger = OperationLedger(self.store)

    def _current(self, expected):
        value = self.progress.read()
        if type(expected) is not int or value["revision"] != expected:
            raise SetupProgressError("setup_progress_stale")
        return value

    def _advance(self, current, step, *, operation=None, binding=None, complete=False):
        operations = dict(current["operations"])
        if operation is not None:
            operations[operation[0]] = operation[1]
        bindings = dict(current["configuration_revisions"])
        if binding is not None:
            bindings[step] = binding
        completed = set(current["completed"])
        if complete:
            completed.add(step)
        return self.progress.update(expected_revision=current["revision"], step=step,
                                    completed=[item for item in STEPS if item in completed],
                                    bindings=bindings, operations=operations)

    def draft_bindings(self, selection):
        source_id = selection["source_id"]
        source = self.store.read_config().get("sources", {}).get(source_id)
        policy = (self.instance.scheduler.journal.get_policy(source["folder"]["policy_id"])
                  if source and source.get("folder") else None)
        progress = self.progress.read()
        prepared = self.prepared()
        trial_id = progress["operations"].get("test")
        probes = SetupTrials(self.store).probe_history(trial_id) if trial_id and read_record(
            self.store, f"state/setup-trials/permits/{trial_id}.json") else []
        ocr = self.instance.ocr.configured_settings().as_record()
        inputs = {"source_id": source_id, "retention": selection["retention"],
                  "ocr": selection["ocr"], "languages": selection["languages"]}
        return {"space": digest({"instance": self.store.read_config()["instance"],
                                  "language": selection["language"],
                                  "revision": self.shell.load().settings.revision}),
                "folders": digest({"source": source, "prepared": prepared,
                                   "retention": selection["retention"]}),
                "ocr": digest({"source": source_id, "settings": ocr,
                               "ocr": selection["ocr"], "languages": selection["languages"]}),
                "automation": digest({"policy": _without(policy, POLICY_CLOCKS),
                                      "mode": selection["automation"],
                                      "login_startup": selection["login_startup"]}),
                "test": digest({"inputs": inputs, "source": source, "settings": ocr,
                                "operation": trial_id, "probe": probes[-1] if probes else None}),
                "summary": digest(selection)}

    def navigate(self, expected, step, *, selection=None, discard=False, finished=None):
        if step not in STEPS:
            raise ReviewDenied("setup_step_invalid")
        with InstanceLifecycleManager(self.store)._hold(purpose="setup-navigation"):
            current = self._current(expected)
            if discard:
                return self.progress.discard(expected_revision=expected)
            if selection is None:
                return self._advance(current, step)
            bindings = self.draft_bindings(selection)
            completed = [item for item in current["completed"]
                         if current["configuration_revisions"].get(item) == bindings[item]]
            if finished is not None:
                if finished not in STEPS or STEPS.index(step) != STEPS.index(finished) + 1:
                    raise ReviewDenied("setup_step_invalid")
                if STEPS.index(step) >= 2:
                    self.check_prepared(validate_choices(selection))
                if STEPS.index(step) >= 3 and selection["ocr"]:
                    require_ocr_available(self.instance.ocr.capability(replace(
                        self.instance.ocr.configured_settings(), mode="automatic",
                        languages=tuple(selection["languages"]))))
                if step == "summary":
                    self.preview(selection)
                completed = list(dict.fromkeys([*completed, finished]))
            return self.progress.update(expected_revision=expected, step=step, completed=completed,
                                        bindings=bindings)

    def finish_trial(self, expected, choices):
        with InstanceLifecycleManager(self.store)._hold(purpose="setup-test-readback"):
            current = self._current(expected)
            trial_id = current["operations"].get("test")
            if trial_id is None:
                raise ReviewUnavailable("setup_trial_required")
            trial = SetupTrials(self.store).observations(trial_id)
            permit = trial["permit"]
            if (not trial["complete"] or permit["selection"]["source_id"] != choices["source_id"]
                    or permit["retention"] != choices["retention"]
                    or permit["ocr_required"] != choices["ocr"]
                    or permit["languages"] != choices["languages"]):
                raise ReviewUnavailable("setup_trial_required")
            return self._advance(current, "test", binding=self.draft_bindings(choices)["test"],
                                 complete=True)

    def prepared(self):
        op_id = self.progress.read()["operations"].get("prepare")
        if op_id is None:
            return None
        value = read_record(self.store, f"{ROOT}/prepare/{operation_id(op_id)}.json")
        if value is None:
            return None
        validate_preparation(self.store, value)
        return value

    def defaults(self):
        settings = self.shell.load().settings
        prepared = self.prepared()
        sources = self.instance.folder_sources.list_public()
        source_id = prepared["source_id"] if prepared else (sources[0]["id"] if sources else None)
        ocr = self.instance.ocr_source_review.policy(source_id) if source_id else None
        inbox = self.instance.inbox_transit_review.policy(source_id) if source_id else None
        result = {"source_id": source_id, "language": settings.language,
                "retention": inbox["mode"] if inbox else (
                    "transit" if not source_id or prepared and prepared["new_source"] else "keep"),
                "ocr": bool(ocr and ocr["enabled"]),
                "languages": ocr["languages"] if ocr else ["eng", "ita"],
                "automation": "automatic" if prepared and prepared["new_source"] else "preserve",
                "login_startup": settings.login_startup}
        trial_id = self.progress.read()["operations"].get("test")
        submitted = None if trial_id is None else read_record(
            self.store, f"{ROOT}/trial-intents/{operation_id(trial_id)}.json")
        if submitted is not None:
            validate_trial_intent(self.store, submitted)
            if submitted["choices"]["source_id"] == source_id:
                result = deepcopy(submitted["choices"])
        return result

    def prepare(self, expected, *, path, name, source_id=None):
        # Only this named action may create directories, probe permissions or enroll.
        selected = absolute_local_path(path)
        managed = self.store.paths.root.absolute()
        if selected.is_relative_to(managed) or managed.is_relative_to(selected):
            raise ReviewDenied("setup_folder_overlap")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ReviewDenied("setup_name_invalid")
        with InstanceLifecycleManager(self.store)._hold(purpose="setup-prepare"):
            current = self._current(expected)
            for other in self.instance.folder_sources.list_public():
                other_path = Path(self.instance.folder_sources.local_view(other["id"])["path"])
                if other_path != selected and (selected.is_relative_to(other_path)
                                               or other_path.is_relative_to(selected)):
                    raise ReviewDenied("setup_folder_overlap")
            existing = self.instance.folder_sources.check_enrollment(selected, source_class="local")
            if source_id is not None and existing.existing_source_id != _source_id(source_id):
                raise ReviewConflict("setup_source_changed")
            chosen = existing.existing_source_id
            previous = self.prepared()
            selector = digest({"path": str(selected), "name": name.strip()})
            pending_id = current["operations"].get("prepare")
            pending = None if pending_id is None else read_record(
                self.store, f"{ROOT}/prepare-intents/{operation_id(pending_id)}.json")
            if previous and previous["selector_sha256"] == selector:
                op_id, chosen, new = previous["id"], previous["source_id"], previous["new_source"]
            elif pending and pending["selector_sha256"] == selector:
                validate_prepare_intent(self.store, pending)
                op_id, chosen, new = pending["id"], pending["source_id"], pending["new_source"]
                if existing.existing_source_id not in {None, chosen}:
                    raise ReviewConflict("setup_source_changed")
            else:
                chosen = chosen or "src_" + uuid4().hex
                new = existing.existing_source_id is None
                op_id = self.ledger.start("setup.prepare", "Prepare the explicitly selected Inbox",
                                          related={"source_id": chosen}).id
                pending = {"schema": "setup-prepare-intent/v1", "id": op_id,
                           "instance_id": self.store.read_config()["instance"]["id"],
                           "source_id": chosen, "new_source": new, "selector_sha256": selector}
                publish_once(self.store, f"{ROOT}/prepare-intents/{op_id}.json", pending)
                current = self._advance(current, "folders", operation=("prepare", op_id))
            with prepare_local_directory(selected, create=new) as (root, binding):
                # Creates/reads/removes only its own temporary permission probe.
                _permission_probe(root)
                configured = self.store.read_config().get("sources", {}).get(chosen)
                if new and (not configured or not configured.get("folder", {}).get("policy_id")):
                    self.instance._register_folder_source_locked(
                        root, name=name.strip(), lifecycle_state="paused", _registration_id=chosen)
                view = self.instance.folder_sources.local_view(chosen)
                if Path(view["path"]) != root:
                    raise ReviewConflict("setup_source_changed")
                record = {"schema": "setup-preparation/v1", "id": op_id,
                          "instance_id": self.store.read_config()["instance"]["id"],
                          "source_id": chosen, "new_source": new, "root_binding": binding,
                          "selector_sha256": selector, "can_transit": os.name == "nt"}
                publish_once(self.store, f"{ROOT}/prepare/{op_id}.json", record)
            op = self.ledger.get(op_id)
            if op["status"] == "running":
                self.ledger.close(op_id, status="completed",
                                  summary="Inbox permission probe verified")
            return self._advance(current, "folders", operation=("prepare", op_id),
                                 binding=digest(record))

    def preview_ocr(self, *, archive, receipt="", expected_sha256=""):
        from .ocr_kit import inspect_kit

        if bool(receipt) == bool(expected_sha256):
            raise ReviewDenied("setup_kit_authority_required")
        result = inspect_kit(absolute_local_path(archive),
                             receipt_path=absolute_local_path(receipt) if receipt else None,
                             expected_sha256=expected_sha256 or None)
        result["revision"] = digest(result)
        return result

    def install_ocr(self, expected, *, archive, receipt="", expected_sha256="", preview_revision):
        from .build_info import current_build_info
        from .ocr_kit import import_kit

        with InstanceLifecycleManager(self.store)._hold(purpose="setup-ocr-install"):
            current = self._current(expected)
            preview = self.preview_ocr(archive=archive, receipt=receipt,
                                       expected_sha256=expected_sha256)
            if preview["revision"] != preview_revision:
                raise ReviewConflict("setup_preview_stale")
            op = self.ledger.start("setup.ocr_install", "Prepare the official offline OCR kit")
            current = self._advance(current, "ocr", operation=("ocr_install", op.id))
            try:
                result = import_kit(
                    absolute_local_path(archive),
                    receipt_path=absolute_local_path(receipt) if receipt else None,
                    expected_sha256=expected_sha256 or None,
                    development=bool(expected_sha256 and
                                     current_build_info().get("official") is False))
            except (ValueError, OSError):
                self.ledger.close(op.id, status="failed", summary="OCR kit preparation failed",
                                  error_code="setup_ocr_install_failed")
                raise
            self.ledger.append(op.id, "setup.ocr.prepared", "Verified the offline OCR kit",
                               details={"sha256": result["kit"]["sha256"]})
            self.ledger.close(op.id, status="completed", summary="Offline OCR components prepared")
            return self._advance(current, "ocr")

    def check_prepared(self, choices):
        prepared = self.prepared()
        if prepared is None or prepared["source_id"] != choices["source_id"]:
            raise ReviewUnavailable("setup_prepare_required")
        root = self.store.source_path(choices["source_id"])
        with open_local_directory(root) as (_path, binding):
            if binding != prepared["root_binding"]:
                raise ReviewConflict("setup_source_changed")
        if choices["retention"] == "transit" and not prepared["can_transit"]:
            raise ReviewUnavailable("setup_transit_unavailable")
        return prepared

    def start_trial(self, expected, choices, *, request_key, fresh=False):
        validate_choices(choices)
        with InstanceLifecycleManager(self.store)._hold(purpose="setup-test"):
            current = self._current(expected)
            self.check_prepared(choices)
            previous = current["operations"].get("test")
            if previous is not None and not fresh:
                trials = SetupTrials(self.store)
                retained = read_record(self.store, f"state/setup-trials/permits/{previous}.json")
                pending = read_record(self.store, f"{ROOT}/trial-intents/{previous}.json")
                if retained is None and pending is not None:
                    validate_trial_intent(self.store, pending)
                    if pending["choices"] != choices:
                        raise ReviewConflict("setup_trial_required")
                    request_key = pending["request_key"]
                elif retained is not None:
                    permit = trials.authority.read(previous)
                    if (permit["selection"]["source_id"] == choices["source_id"]
                        and permit["retention"] == choices["retention"]
                        and permit["ocr_required"] == choices["ocr"]
                        and permit["languages"] == choices["languages"]):
                        trials.queue_locked(previous)
                        return self._advance(current, "test", binding=digest(choices))
                    raise ReviewConflict("setup_trial_required")

            def referenced(op_id):
                nonlocal current
                intent = {"schema": "setup-trial-intent/v1", "id": op_id,
                          "instance_id": self.store.read_config()["instance"]["id"],
                          "choices": deepcopy(choices), "request_key": request_key}
                publish_once(self.store, f"{ROOT}/trial-intents/{op_id}.json", intent)
                current = self._advance(current, "test", operation=("test", op_id),
                                        binding=digest(choices))

            result = SetupTrials(self.store).start_locked(
                choices["source_id"], retention=choices["retention"], ocr_required=choices["ocr"],
                languages=choices["languages"], request_key=request_key, _on_operation=referenced)
            if current["operations"].get("test") != result["operation_id"]:
                raise ReviewUnavailable("setup_trial_required")
            return current

    def _snapshot(self, source_id):
        config = self.store.read_config()
        selected = config["sources"][source_id]
        policy = self.instance.scheduler.journal.get_policy(selected["folder"]["policy_id"])
        other = deepcopy(config)
        other.pop("ocr", None)
        other["sources"].pop(source_id)
        return {"other": digest(other),
                "source": digest({"canonical": self.store.read_canonical("sources", source_id),
                                  "config": selected}),
                "schedule": digest(_without(policy, POLICY_CLOCKS)),
                "ocr": digest(self.instance.ocr.configured_settings().as_record()),
                "source_ocr": digest(_policy(self.instance.ocr_source_review.policy(source_id))),
                "inbox": digest(_policy(self.instance.inbox_transit_review.policy(source_id))),
                "authority": digest(self.instance.review_authority.read()),
                "shell": digest(self.shell.load().settings.as_payload()),
                "baseline": digest(_baseline(self.store, source_id))}

    def _grant(self, domain, source_id):
        authority = self.instance.review_authority
        if authority.resolve(domain, source_id, "save_policy")["mode"] == "confirm-each":
            return None
        before = authority.read()["grants"].get(domain)
        target = {"mode": "confirm-each", "scope": {
            "subjects": [source_id], "sources": [source_id], "actions": ["save_policy"]}}
        if before is not None:
            if before["scope"] == target["scope"]:
                return target
            scope = before["scope"]
            if (before["mode"] != "confirm-each" or scope["actions"] != ["save_policy"]
                    or scope["subjects"] != scope["sources"] or "*" in scope["subjects"]):
                raise ReviewDenied("setup_authority_needs_review")
            target["scope"]["subjects"] = sorted(set(scope["subjects"] + [source_id]))
            target["scope"]["sources"] = target["scope"]["subjects"][:]
        return target

    def preview(self, choices):
        validate_choices(choices)
        prepared = self.check_prepared(choices)
        progress = self.progress.read()
        trial_id = progress["operations"].get("test")
        if trial_id is None:
            raise ReviewUnavailable("setup_trial_required")
        trial = SetupTrials(self.store).observations(trial_id)
        permit = trial["permit"]
        if (not trial["complete"] or permit["selection"]["source_id"] != choices["source_id"]
                or permit["ocr_required"] != choices["ocr"]
                or permit["retention"] != choices["retention"]
                or permit["languages"] != choices["languages"]):
            raise ReviewUnavailable("setup_trial_required")
        if self.instance.folder_sources.observer(choices["source_id"])["active_run_id"] is not None:
            raise ReviewUnavailable("setup_source_busy")
        settings = self.instance.ocr.configured_settings()
        if choices["ocr"]:
            require_ocr_available(self.instance.ocr.capability(
                replace(settings, mode="automatic", languages=tuple(choices["languages"]))))
            if settings.mode != "automatic":
                for source in self.store.list_canonical("sources"):
                    policy = self.instance.ocr_source_review.policy(source["id"])
                    if source["id"] != choices["source_id"] and policy and policy["enabled"]:
                        raise ReviewDenied("setup_global_ocr_needs_review")
        saved = self.shell.load()
        if saved.warning == "settings_invalid_using_safe_defaults":
            raise ReviewUnavailable("setup_settings_invalid")
        if (choices["login_startup"] != saved.settings.login_startup and not startup_available()):
            raise ReviewUnavailable("setup_startup_unavailable")
        baseline = None
        if prepared["new_source"] and _baseline(self.store, choices["source_id"]) is None:
            baseline = baseline_preview(self.store, choices["source_id"])
        grants = {"inbox_transit": self._grant("inbox_transit", choices["source_id"]),
                  "ocr_sources": None}
        existing_ocr = self.instance.ocr_source_review.policy(choices["source_id"])
        if choices["ocr"] or existing_ocr is not None:
            grants["ocr_sources"] = self._grant("ocr_sources", choices["source_id"])
        inbox_preview = self.instance.inbox_transit_review.preview(
            choices["source_id"], "save_policy", {"mode": choices["retention"]})
        result = {"schema": "setup-apply-preview/v1", "choices": deepcopy(choices),
                  "instance_id": self.store.read_config()["instance"]["id"],
                  "prepare_id": prepared["id"], "trial_id": trial_id,
                  "trial_evidence": digest(SetupTrials(self.store).probe_history(trial_id)[-1]),
                  "before": self._snapshot(choices["source_id"]), "grants": grants,
                  "inbox_inventory": inbox_preview["evidence"]["backlog"],
                  "baseline": baseline, "progress_revision": progress["revision"]}
        result["revision"] = digest(result)
        return result

    def application(self):
        op_id = self.progress.read()["operations"].get("apply")
        if op_id is None:
            return None
        plan = read_record(self.store, f"{ROOT}/apply/{operation_id(op_id)}/plan.json",
                           maximum=2 * 1024 * 1024)
        if plan is None:
            return {"id": op_id, "complete": False, "pending": True, "stages": []}
        validate_application(self.store, plan)
        stages = []
        checkpoint = plan["preview"]["before"]
        for index, kind in enumerate(APPLY_STAGES):
            record = read_record(self.store, f"{ROOT}/apply/{op_id}/{index:02d}-result.json")
            if record is not None:
                validate_stage(record, op_id, kind, "result")
                intent = read_record(self.store, f"{ROOT}/apply/{op_id}/{index:02d}-intent.json",
                                     maximum=2 * 1024 * 1024)
                validate_stage(intent, op_id, kind, "intent")
                if (index != len(stages) or record["before"] != checkpoint
                        or record["before"] != intent["before"]
                        or record["after"] != intent["after"]
                        or record["intent_sha256"] != digest(intent)):
                    raise ReviewUnavailable("setup_apply_needs_review")
                checkpoint = record["after"]
                stages.append(record)
        op = self.ledger.get(op_id)
        try:
            current = self._snapshot(plan["preview"]["choices"]["source_id"])
        except (ValueError, OSError):
            current = None
        complete = (op["status"] == "completed" and len(stages) == len(APPLY_STAGES)
                    and self._completed_settings_current(plan, current, stages[-1]["after"])
                    and self._trial_material_current(plan["preview"])
                    and startup_observed(plan["preview"]["choices"]["login_startup"]))
        return {"id": op_id, "complete": complete, "pending": op["status"] == "running",
                "stages": stages, "plan": plan}

    def _completed_settings_current(self, plan, current, expected):
        """Unselected later preferences are not stale setup effects.

        In-flight application still compares the entire revision-bound snapshot.
        After its receipt, theme/interface/other Source changes must not demand
        a new trial for an unchanged selected Source and saved setup choices.
        """
        if current is None:
            return False
        choices = plan["preview"]["choices"]
        required = {"source", "source_ocr", "inbox", "baseline"}
        if choices["automation"] != "preserve":
            required.add("schedule")
        if choices["ocr"]:
            required.add("ocr")
        if any(current[key] != expected[key] for key in required):
            return False
        settings = self.shell.load().settings
        if (settings.language != choices["language"]
                or settings.login_startup != choices["login_startup"]):
            return False
        try:
            self.check_prepared(choices)
            for domain in (["inbox_transit", "ocr_sources"] if choices["ocr"]
                           else ["inbox_transit"]):
                if self.instance.review_authority.resolve(
                        domain, choices["source_id"], "save_policy")["mode"] != "confirm-each":
                    return False
        except (ValueError, OSError):
            return False
        return True

    def pause_and_review(self, expected):
        """Explicit supported reverse action: pause admission, retain all other effects."""
        with InstanceLifecycleManager(self.store)._hold(purpose="setup-pause-and-review"):
            current = self._current(expected)
            application = self.application()
            if not application or not application.get("plan"):
                raise ReviewUnavailable("setup_apply_needs_review")
            plan = application["plan"]
            source_id = plan["preview"]["choices"]["source_id"]
            barrier = read_record(self.store, f"{ACTIVE}/{source_id}.json")
            if barrier is None or barrier["operation_id"] != plan["id"]:
                raise ReviewConflict("setup_apply_needs_review")
            release_path = f"{ROOT}/releases/{plan['id']}.json"
            release = read_record(self.store, release_path)
            if release is None:
                op = self.ledger.start("setup.pause_apply", "Pause and review remaining setup",
                                       related={"source_id": source_id,
                                                "apply_operation_id": plan["id"]})
                release = {"schema": "setup-apply-release/v1", "id": plan["id"],
                           "instance_id": self.store.read_config()["instance"]["id"],
                           "source_id": source_id, "operation_id": op.id,
                           "plan_sha256": digest(plan)}
                publish_once(self.store, release_path, release)
            validate_release(self.store, release)
            self.instance._set_folder_source_state_locked(source_id, "paused")
            if self.ledger.get(release["operation_id"])["status"] == "running":
                self.ledger.close(release["operation_id"], status="completed",
                                  summary="Acquisition paused; other applied settings remain")
            if self.ledger.get(plan["id"])["status"] == "running":
                self.ledger.close(plan["id"], status="completed_with_errors",
                                  summary="Applied effects retained; review remaining settings")
            return self.progress.update(expected_revision=current["revision"], step="folders",
                                        completed=[], bindings={})

    def apply(self, expected, *, choices, preview_revision):
        validate_choices(choices)
        with (InstanceLifecycleManager(self.store)._hold(purpose="setup-apply"),
              open_local_directory(self.store.source_path(choices["source_id"]))):
            current = self._current(expected)
            self.check_prepared(choices)
            # Explicit Apply/resume uses the registered recovery owner for any
            # already confirmed review transaction. GET never invokes it.
            self.instance.review_decisions.mutation_guard(self.store)
            previous = self.application()
            if previous and previous.get("plan") and previous["pending"]:
                plan = previous["plan"]
                if (plan["preview"]["choices"] != choices
                        or plan["preview"]["revision"] != preview_revision):
                    raise ReviewConflict("setup_apply_needs_review")
                op_id = plan["id"]
            elif (previous and previous["complete"]
                    and previous["plan"]["preview"]["choices"] == choices
                    and previous["plan"]["preview"]["revision"] == preview_revision):
                return self._advance(current, "summary", complete=True)
            else:
                preview = self.preview(choices)
                if preview["revision"] != preview_revision:
                    raise ReviewConflict("setup_preview_stale")
                op_id = self.ledger.start("setup.apply", "Apply the displayed remaining settings",
                                          related={"source_id": choices["source_id"]}).id
                plan = {"schema": "setup-application/v1", "id": op_id, "preview": preview}
                publish_once(self.store, f"{ROOT}/apply/{op_id}/plan.json", plan)
                current = self._advance(current, "summary", operation=("apply", op_id))
            # Reestablish a missing restriction after a crash before its write.
            # It creates no job or observer and never authorizes admission.
            import json

            from .review_decisions import checked_path
            from .storage import InstanceStore

            barrier = {"schema": "setup-admission-barrier/v1",
                       "source_id": choices["source_id"], "operation_id": op_id,
                       "instance_id": plan["preview"]["instance_id"]}
            target = checked_path(self.store, f"{ACTIVE}/{choices['source_id']}.json")
            existing = read_record(self.store, f"{ACTIVE}/{choices['source_id']}.json")
            if existing and existing["operation_id"] != op_id:
                assert_admission_ready(self.store, choices["source_id"])
            target.parent.mkdir(parents=True, exist_ok=True)
            InstanceStore._atomic_text(target, json.dumps(barrier, sort_keys=True) + "\n")
            _permission_probe(self.store.source_path(choices["source_id"]))
            checkpoint = plan["preview"]["before"]
            for index, kind in enumerate(APPLY_STAGES):
                base = f"{ROOT}/apply/{op_id}/{index:02d}"
                result = read_record(self.store, base + "-result.json")
                if result is not None:
                    validate_stage(result, op_id, kind, "result")
                    if result["before"] != checkpoint:
                        raise ReviewUnavailable("setup_apply_needs_review")
                    checkpoint = result["after"]
                    continue
                intent = read_record(self.store, base + "-intent.json", maximum=2 * 1024 * 1024)
                if intent is None:
                    if self._snapshot(choices["source_id"]) != checkpoint:
                        raise ReviewConflict("setup_preview_stale")
                    intent = self._stage_intent(plan, kind, checkpoint)
                    publish_once(self.store, base + "-intent.json", intent)
                validate_stage(intent, op_id, kind, "intent")
                if intent["before"] != checkpoint:
                    raise ReviewUnavailable("setup_apply_needs_review")
                observed = self._snapshot(choices["source_id"])
                if observed == intent["before"]:
                    if self._stage_intent(plan, kind, checkpoint) != intent:
                        raise ReviewConflict("setup_apply_needs_review")
                    if observed != intent["after"]:
                        self._execute_stage(plan, intent)
                elif (kind == "activation" and intent["parameters"] == {"state": "enabled"}
                      and observed == {**intent["before"],
                                       "schedule": intent["after"]["schedule"]}):
                    # The linked policy may have committed before the observer
                    # write failed. Finish that same service transition once.
                    self.instance.folder_sources.set_state(choices["source_id"], "enabled")
                elif observed != intent["after"]:
                    raise ReviewConflict("setup_apply_needs_review")
                after = self._snapshot(choices["source_id"])
                if after != intent["after"]:
                    raise ReviewUnavailable("setup_apply_readback_failed")
                result = {"schema": "setup-stage-result/v1", "id": op_id, "kind": kind,
                          "before": checkpoint, "after": after,
                          "intent_sha256": digest(intent)}
                publish_once(self.store, base + "-result.json", result)
                self.ledger.append(op_id, "setup.applied." + kind,
                                   "Verified the selected setup setting", details={"stage": kind})
                checkpoint = after
            if self._snapshot(choices["source_id"]) != checkpoint:
                raise ReviewConflict("setup_apply_readback_failed")
            if not startup_observed(choices["login_startup"]):
                raise ReviewUnavailable("setup_startup_readback_failed")
            if not self._trial_material_current(plan["preview"]):
                raise ReviewUnavailable("setup_trial_required")
            self.ledger.close(op_id, status="completed",
                              summary="Selected setup settings read back")
            return self._advance(current, "summary", binding=digest(checkpoint), complete=True)

    def _stage_intent(self, plan, kind, before):
        choices, preview, op_id = plan["preview"]["choices"], plan["preview"], plan["id"]
        source_id = choices["source_id"]
        after, parameters, review = dict(before), None, None
        if kind == "baseline" and preview["baseline"] is not None:
            parameters = preview["baseline"]
            baseline = {"schema": "setup-source-baseline/v1", **parameters,
                        "instance_id": preview["instance_id"], "operation_id": op_id}
            after["baseline"] = digest(baseline)
        elif kind == "ocr" and choices["ocr"]:
            selected = replace(self.instance.ocr.configured_settings(), mode="automatic")
            parameters = selected.as_record()
            after["ocr"] = digest(parameters)
        elif kind == "schedule" and choices["automation"] != "preserve":
            source = self.instance.folder_sources.public_view(source_id)
            policy = self.instance.scheduler.journal.get_policy(source["policy_id"])
            schedule = schedule_payload(mode="interval", timezone="UTC", interval_seconds=60) if (
                choices["automation"] == "automatic") else schedule_payload(
                    mode="manual", timezone="UTC")
            if policy["schedule"] != schedule:
                parameters = {"policy_id": policy["id"], "schedule": schedule}
                after["schedule"] = digest({**_without(policy, POLICY_CLOCKS), "schedule": schedule,
                                            "revision": policy["revision"] + 1})
        elif kind == "activation" and choices["automation"] != "preserve":
            config = self.store.read_config()["sources"][source_id]
            policy = self.instance.scheduler.journal.get_policy(config["folder"]["policy_id"])
            if config["folder"]["lifecycle_state"] != "enabled" or policy["state"] != "enabled":
                parameters = {"state": "enabled"}
                config = {**config, "folder": {**config["folder"], "lifecycle_state": "enabled"}}
                after["source"] = digest({
                    "canonical": self.store.read_canonical("sources", source_id), "config": config})
                after["schedule"] = digest({**_without(policy, POLICY_CLOCKS), "state": "enabled",
                                            "revision": policy["revision"] + 1})
        elif kind.startswith("grant_"):
            domain = kind.removeprefix("grant_")
            parameters = preview["grants"][domain]
            if parameters is not None:
                if parameters != self._grant(domain, source_id):
                    raise ReviewDenied("setup_authority_needs_review")
                state = self.instance.review_authority.read()
                after["authority"] = digest({**state, "generation": state["generation"] + 1,
                                             "grants": {**state["grants"], domain: parameters}})
                review = self.instance.review_decisions.preview(
                    "capabilities", domain, "configure", parameters)
        elif kind in {"source_ocr", "inbox"}:
            domain = "ocr_sources" if kind == "source_ocr" else "inbox_transit"
            parameters = {"enabled": choices["ocr"], "languages": choices["languages"]} if (
                kind == "source_ocr") else {"mode": choices["retention"]}
            provider = (self.instance.ocr_source_review if kind == "source_ocr"
                        else self.instance.inbox_transit_review)
            existing = provider.policy(source_id)
            if kind == "source_ocr" and not choices["ocr"] and existing is None:
                return {"schema": "setup-stage-intent/v1", "id": op_id, "kind": kind,
                        "before": before, "after": after, "parameters": None, "review": None}
            # Avoid unnecessary consent revisions, while rebinds after explicit
            # global/Source setting changes still use the ordinary review owner.
            proposal = provider.preview(source_id, "save_policy", parameters)
            if (kind == "inbox" and proposal["evidence"]["backlog"] != preview["inbox_inventory"]):
                raise ReviewConflict("setup_preview_stale")
            target = proposal["after"]
            unchanged = existing is not None and all(
                existing.get(key) == value for key, value in target.items() if key != "revision")
            if unchanged:
                parameters = None
            else:
                review = self.instance.review_decisions.preview(domain, source_id,
                                                               "save_policy", parameters)
                after[kind] = digest(_policy(target))
        elif kind == "shell":
            settings = self.shell.load().settings
            if (settings.language != choices["language"]
                    or settings.login_startup != choices["login_startup"]):
                parameters = {"language": choices["language"],
                              "login_startup": choices["login_startup"],
                              "expected_revision": settings.revision}
                after["shell"] = digest(replace(
                    settings, language=choices["language"], login_startup=choices["login_startup"],
                    revision=settings.revision + 1).as_payload())
        return {"schema": "setup-stage-intent/v1", "id": op_id, "kind": kind,
                "before": before, "after": after, "parameters": parameters, "review": review}

    def _execute_stage(self, plan, intent):
        kind, params = intent["kind"], intent["parameters"]
        source_id = plan["preview"]["choices"]["source_id"]
        if params is None:
            return
        if kind == "baseline":
            install_baseline(self.store, plan["id"], params)
        elif kind == "ocr":
            self.instance.ocr.configure(replace(self.instance.ocr.configured_settings(),
                                                mode="automatic"))
        elif kind == "schedule":
            self.instance.scheduler.journal.update_policy(
                params["policy_id"], schedule=params["schedule"])
        elif kind == "activation":
            self.instance._set_folder_source_state_locked(source_id, params["state"])
        elif kind == "shell":
            arguments = dict(params)
            if self.shell.load().settings.login_startup == params["login_startup"]:
                arguments.pop("login_startup")
            self.shell.set_preferences(**arguments)
        elif intent["review"] is not None:
            review = intent["review"]
            self.instance.review_decisions._confirm_locked(
                review["domain"], review["subject"], review["action"], review["parameters"],
                expected_plan_revision=review["plan_revision"],
                expected_authority_revision=review["authority_revision"],
                request_id=f"setup_{plan['id']}_{kind}")


    def _trial_material_current(self, preview):
        """Observe the accepted trial after Apply, never authorize future work.

        The completed trial receipt was consumed before settings changed. The old
        permit becomes stale for new producer/exit effects; Original bytes,
        selected contribution and content search still need current readback.
        """
        from .markdown_viewer import DocumentContentError
        from .producer_index_evidence import describe_contribution
        from .review_decisions import checked_path

        try:
            trials = SetupTrials(self.store)
            permit = trials.authority.read(preview["trial_id"], current=False)
            probes = trials.probe_history(preview["trial_id"])
            if (not probes or digest(probes[-1]) != preview["trial_evidence"]
                    or not probes[-1]["settled"] or not probes[-1]["record"]["success"]):
                return False
            for selected, acquisition in zip(permit["selection"]["inputs"],
                                             trials.acquisitions(preview["trial_id"]), strict=True):
                if acquisition is None:
                    return False
                original = self.instance.document_original(acquisition["document_id"])
                if (original["version"]["id"] != acquisition["version_id"]
                        or hashlib.sha256(original["data"]).hexdigest()
                        != selected["input"]["sha256"]):
                    return False
                contribution = describe_contribution(self.store, acquisition["document_id"],
                                                     acquisition["version_id"])[0]
                if (contribution["original_sha256"] != acquisition["content_hash"]
                        or contribution["profile"] != (
                            "embedded" if selected["fixture"] == "native" else "ocr-complete")):
                    return False
                tokens = ["LUMENATIVE731"] if selected["fixture"] == "native" else [
                    "LUMESCANENGLISH953" if lang == "eng" else "LUMESCANITALIA842"
                    for lang in permit["languages"]]
                path = checked_path(self.store, "indexes/search.sqlite3")
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
                    if not all(connection.execute(
                            "SELECT document_id, version_id FROM search WHERE search MATCH ? "
                            "AND document_id = ? AND version_id = ?",
                            ("content:" + token, acquisition["document_id"],
                             acquisition["version_id"])).fetchall() == [(
                                 acquisition["document_id"], acquisition["version_id"])]
                               for token in tokens):
                        return False
            return True
        except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, DocumentContentError):
            return False


APPLY_STAGES = ("baseline", "ocr", "schedule", "activation", "grant_ocr_sources",
                "grant_inbox_transit", "source_ocr", "inbox", "shell")


def validate_preparation(store, value):
    if (not isinstance(value, dict) or set(value) != {
            "schema", "id", "instance_id", "source_id", "new_source", "root_binding",
            "selector_sha256", "can_transit"}
            or value["schema"] != "setup-preparation/v1"
            or type(value["new_source"]) is not bool or type(value["can_transit"]) is not bool
            or value["instance_id"] != store.read_config()["instance"]["id"]
            or re.fullmatch(r"[0-9a-f]{64}", str(value["selector_sha256"])) is None):
        raise ReviewUnavailable("setup_preparation_invalid")
    from .setup_trial_inputs import ROOT_ID

    if ROOT_ID.fullmatch(str(value["root_binding"])) is None:
        raise ReviewUnavailable("setup_preparation_invalid")
    _source_id(value["source_id"])
    op = OperationLedger(store).get(operation_id(value["id"]))
    if (op is None or op["kind"] != "setup.prepare"
            or op["related"] != {"source_id": value["source_id"]}):
        raise ReviewUnavailable("setup_preparation_invalid")
    return value


def validate_prepare_intent(store, value):
    if (not isinstance(value, dict) or set(value) != {
            "schema", "id", "instance_id", "source_id", "new_source", "selector_sha256"}
            or value["schema"] != "setup-prepare-intent/v1"
            or type(value["new_source"]) is not bool
            or value["instance_id"] != store.read_config()["instance"]["id"]
            or re.fullmatch(r"[0-9a-f]{64}", str(value["selector_sha256"])) is None):
        raise ReviewUnavailable("setup_preparation_invalid")
    _source_id(value["source_id"])
    op = OperationLedger(store).get(operation_id(value["id"]))
    if (op is None or op["kind"] != "setup.prepare"
            or op["related"] != {"source_id": value["source_id"]}):
        raise ReviewUnavailable("setup_preparation_invalid")
    return value


def validate_trial_intent(store, value):
    if (not isinstance(value, dict) or set(value) != {
            "schema", "id", "instance_id", "choices", "request_key"}
            or value["schema"] != "setup-trial-intent/v1"
            or value["instance_id"] != store.read_config()["instance"]["id"]
            or re.fullmatch(r"[A-Za-z0-9_-]{16,100}", str(value["request_key"])) is None):
        raise ReviewUnavailable("setup_trial_intent_invalid")
    validate_choices(value["choices"])
    op = OperationLedger(store).get(operation_id(value["id"]))
    if (op is None or op["kind"] != "setup.trial"
            or op["related"] != {"source_id": value["choices"]["source_id"]}):
        raise ReviewUnavailable("setup_trial_intent_invalid")
    return value


def validate_release(store, value):
    if (not isinstance(value, dict) or set(value) != {
            "schema", "id", "instance_id", "source_id", "operation_id", "plan_sha256"}
            or value["schema"] != "setup-apply-release/v1"
            or value["instance_id"] != store.read_config()["instance"]["id"]):
        raise ReviewUnavailable("setup_apply_needs_review")
    op = OperationLedger(store).get(operation_id(value["operation_id"]))
    if (op is None or op["kind"] != "setup.pause_apply"
            or op["related"] != {"source_id": _source_id(value["source_id"]),
                                 "apply_operation_id": operation_id(value["id"])}):
        raise ReviewUnavailable("setup_apply_needs_review")
    plan = read_record(store, f"{ROOT}/apply/{value['id']}/plan.json", maximum=2 * 1024 * 1024)
    if plan is None or value["plan_sha256"] != digest(plan):
        raise ReviewUnavailable("setup_apply_needs_review")
    if plan["preview"]["choices"]["source_id"] != value["source_id"]:
        raise ReviewUnavailable("setup_apply_needs_review")
    return value


def validate_application(store, value):
    if (not isinstance(value, dict) or set(value) != {"schema", "id", "preview"}
            or value["schema"] != "setup-application/v1" or not isinstance(value["preview"], dict)):
        raise ReviewUnavailable("setup_application_invalid")
    preview = value["preview"]
    if (set(preview) != {"schema", "choices", "instance_id", "prepare_id", "trial_id",
                         "trial_evidence", "before", "grants", "baseline", "progress_revision",
                         "revision", "inbox_inventory"}
            or preview["schema"] != "setup-apply-preview/v1"
            or preview["instance_id"] != store.read_config()["instance"]["id"]
            or digest(_without(preview, {"revision"})) != preview["revision"]):
        raise ReviewUnavailable("setup_application_invalid")
    validate_choices(preview["choices"])
    from .inbox_transit import validate_input

    inventory = preview["inbox_inventory"]
    if not isinstance(inventory, list) or len(inventory) > 1000:
        raise ReviewUnavailable("setup_application_invalid")
    for item in inventory:
        validate_input(item)
    locators = [item["locator"] for item in inventory]
    if locators != sorted(set(locators)):
        raise ReviewUnavailable("setup_application_invalid")
    validate_preparation(store, read_record(
        store, f"{ROOT}/prepare/{operation_id(preview['prepare_id'])}.json"))
    operation_id(preview["trial_id"])
    if (type(preview["progress_revision"]) is not int
            or not 0 <= preview["progress_revision"] <= 10000
            or re.fullmatch(r"[0-9a-f]{64}", str(preview["trial_evidence"])) is None
            or not isinstance(preview["grants"], dict)
            or set(preview["grants"]) != {"ocr_sources", "inbox_transit"}):
        raise ReviewUnavailable("setup_application_invalid")
    for domain, grant in preview["grants"].items():
        if grant is not None:
            from .review_authority import ReviewAuthority
            from .review_integrity import CAPABILITIES

            ReviewAuthority(store, CAPABILITIES)._grant(domain, grant)
    op = OperationLedger(store).get(operation_id(value["id"]))
    if (op is None or op["kind"] != "setup.apply"
            or op["related"] != {"source_id": preview["choices"]["source_id"]}):
        raise ReviewUnavailable("setup_application_invalid")
    return value


def setup_action_findings(store):
    from .review_decisions import checked_path

    findings = []
    try:
        root = checked_path(store, ROOT)
        if not root.exists():
            return findings
        allowed = {"prepare", "prepare-intents", "trial-intents", "apply", "active", "releases"}
        count, total = 0, 0
        for directory in root.iterdir():
            if directory.name not in allowed or not directory.is_dir() or directory.is_symlink():
                raise ReviewUnavailable("Unknown setup action state")
            for path in directory.rglob("*"):
                count += 1
                if count > 10000 or path.is_symlink() or path.is_junction():
                    raise ReviewUnavailable("Setup action history is unsafe or too large")
                parts = path.relative_to(root).parts
                if path.is_dir():
                    if directory.name != "apply" or len(parts) != 2:
                        raise ReviewUnavailable("Unknown setup action directory")
                    operation_id(path.name)
                    continue
                if path.suffix != ".json" or len(parts) > 3:
                    raise ReviewUnavailable("Unknown setup action entry")
                total += path.stat().st_size
                if total > 32 * 1024 * 1024:
                    raise ReviewUnavailable("Setup action history exceeds its byte bound")
                value = read_record(store, path.relative_to(store.paths.root).as_posix(),
                                    maximum=2 * 1024 * 1024)
                if directory.name == "apply":
                    if len(parts) != 3:
                        raise ReviewUnavailable("Invalid setup application path")
                    op_id = operation_id(parts[1])
                    plan = validate_application(store, read_record(
                        store, f"{ROOT}/apply/{op_id}/plan.json", maximum=2 * 1024 * 1024))
                    if path.name == "plan.json":
                        if plan["id"] != op_id:
                            raise ReviewUnavailable("Setup plan has another operation identity")
                        continue
                    match = re.fullmatch(r"(0[0-8])-(intent|result)\.json", path.name)
                    if match is None:
                        raise ReviewUnavailable("Unknown setup stage file")
                    number, category = int(match[1]), match[2]
                    validate_stage(value, op_id, APPLY_STAGES[number], category)
                    intent = read_record(store, f"{ROOT}/apply/{op_id}/{number:02d}-intent.json",
                                         maximum=2 * 1024 * 1024)
                    validate_stage(intent, op_id, APPLY_STAGES[number], "intent")
                    if category == "result" and (
                            value["intent_sha256"] != digest(intent)
                            or value["before"] != intent["before"]
                            or value["after"] != intent["after"]):
                        raise ReviewUnavailable("Setup readback does not match its intent")
                    prior = plan["preview"]["before"] if number == 0 else read_record(
                        store, f"{ROOT}/apply/{op_id}/{number - 1:02d}-result.json")
                    if prior is None or value["before"] != (
                            prior if number == 0 else prior["after"]):
                        raise ReviewUnavailable("Setup readback history is incomplete")
                elif len(parts) != 2:
                    raise ReviewUnavailable("Invalid setup action path")
                elif directory.name == "active":
                    source_id = _source_id(path.stem)
                    if (not isinstance(value, dict) or set(value) != {
                            "schema", "source_id", "instance_id", "operation_id"}
                            or value["schema"] != "setup-admission-barrier/v1"
                            or value["source_id"] != source_id
                            or value["instance_id"] != store.read_config()["instance"]["id"]):
                        raise ReviewUnavailable("Invalid setup admission barrier")
                    op = OperationLedger(store).get(operation_id(value["operation_id"]))
                    if (op is None or op["kind"] != "setup.apply"
                            or op["related"] != {"source_id": source_id}):
                        raise ReviewUnavailable("Setup barrier has another owner")
                else:
                    {"prepare": validate_preparation, "prepare-intents": validate_prepare_intent,
                     "releases": validate_release,
                     "trial-intents": validate_trial_intent}[directory.name](store, value)
                    if value["id"] != operation_id(path.stem):
                        raise ReviewUnavailable("Setup action has another operation identity")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        findings.append({"code": "setup_action_invalid", "path": ROOT, "message": str(exc)})
    return findings


def validate_stage(value, op_id, kind, category):
    fields = {"schema", "id", "kind", "before", "after"}
    fields |= {"parameters", "review"} if category == "intent" else {"intent_sha256"}
    if (not isinstance(value, dict) or set(value) != fields
            or value["schema"] != f"setup-stage-{category}/v1"
            or value["id"] != op_id or value["kind"] != kind):
        raise ReviewUnavailable("setup_stage_invalid")
    keys = {"other", "source", "schedule", "ocr", "source_ocr", "inbox", "authority", "shell",
            "baseline"}
    for snapshot in (value["before"], value["after"]):
        if (not isinstance(snapshot, dict) or set(snapshot) != keys
                or any(re.fullmatch(r"[0-9a-f]{64}", str(v)) is None for v in snapshot.values())):
            raise ReviewUnavailable("setup_stage_invalid")
    return value
