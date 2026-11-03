"""Durable authority for one explicitly submitted synthetic setup operation.

This record is distinct from Source consent. Producers revalidate its exact
Instance, Source, root, resources and settings; a setup-progress reference alone
cannot authorize work. No global capability or Source policy is changed here.
"""

import re
from dataclasses import replace
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from .action_center_model import digest
from .inbox_transit import _source
from .index_evidence import publish_once
from .maintenance_local_files import open_local_directory
from .ocr_contract import ocr_settings_from_config, settings_fingerprint
from .operations import OperationLedger
from .review_decisions import decode_json, read_bytes, read_json
from .review_effects import ReviewDenied, ReviewStale, ReviewUnavailable
from .setup_trial_inputs import revalidate_selection, validate_selection
from .storage import utc_now

ROOT = "state/setup-trials"
PERMITS = ROOT + "/permits"
FIELDS = {"schema", "id", "instance_id", "selection", "retention", "ocr_required",
          "languages", "baseline_settings", "source_consents", "principal", "recorded_at"}


def operation_id(value):
    if not isinstance(value, str) or re.fullmatch(r"op_[0-9a-f]{32}", value) is None:
        raise ReviewUnavailable("The setup operation reference is invalid")
    return value


def permit_path(value):
    return f"{PERMITS}/{operation_id(value)}.json"


def read_record(store, relative, *, maximum=16384):
    raw = read_bytes(store, relative, maximum=maximum)
    try:
        return None if raw is None else decode_json(raw)
    except RecursionError as exc:
        raise ReviewUnavailable("The trial record exceeds its nesting bound") from exc


def ingestion_run_id(value):
    operation_id(value)
    return "run_" + uuid5(NAMESPACE_URL, "provelume:setup-trial:" + value).hex


def acquisition_id(value, locator):
    run_id = ingestion_run_id(value)
    return "acq_" + uuid5(
        NAMESPACE_URL, f"provelume:ingestion-acquisition:{run_id}:{locator}").hex


def validate_permit(value):
    try:
        if (not isinstance(value, dict) or set(value) != FIELDS
                or value["schema"] != "setup-trial-permit/v1"
                or value["retention"] not in {"transit", "keep"}
                or type(value["ocr_required"]) is not bool
                or value["principal"] not in {"local_browser", "local_cli"}
                or value["languages"] not in [["eng"], ["ita"], ["eng", "ita"]]
                or re.fullmatch(r"[0-9a-f]{64}", str(value["baseline_settings"])) is None
                or re.fullmatch(r"[0-9a-f]{64}", str(value["source_consents"])) is None
                or not isinstance(value["recorded_at"], str)
                or datetime.fromisoformat(value["recorded_at"]).tzinfo is None):
            raise ValueError("permit schema")
        operation_id(value["id"])
        validate_selection(value["selection"])
        if (value["instance_id"] != value["selection"]["instance_id"]
                or len(value["selection"]["inputs"]) != (2 if value["ocr_required"] else 1)):
            raise ValueError("permit resource scope")
    except (TypeError, KeyError, ValueError) as exc:
        raise ReviewUnavailable("The synthetic trial permit is invalid") from exc
    return value


class SetupTrialAuthority:
    def __init__(self, store):
        self.store = store

    def consents(self, source_id):
        from .inbox_transit import InboxTransitReview
        from .ocr_sources import SourceOcrReview
        from .review_authority import ReviewAuthority
        from .review_integrity import CAPABILITIES

        return digest({"ocr": SourceOcrReview(self.store).policy(source_id),
                       "inbox": InboxTransitReview(self.store).policy(source_id),
                       "ocr_authority": ReviewAuthority(self.store, CAPABILITIES).resolve(
                           "ocr_sources", source_id, "save_policy")["revision"],
                       "inbox_authority": ReviewAuthority(self.store, CAPABILITIES).resolve(
                           "inbox_transit", source_id, "save_policy")["revision"]})

    def issue(self, op_id, selection, *, retention, ocr_required, languages,
              principal="local_browser"):
        """Caller holds lifecycle and is executing the explicit Start trial action."""
        revalidate_selection(self.store, selection)
        operation = OperationLedger(self.store).get(operation_id(op_id))
        if (operation is None or operation["kind"] != "setup.trial"
                or operation["status"] != "running"
                or operation["related"] != {"source_id": selection["source_id"]}):
            raise ReviewDenied("The selected setup operation cannot authorize this trial")
        existing = read_record(self.store, permit_path(op_id))
        value = validate_permit({
            "schema": "setup-trial-permit/v1", "id": op_id,
            "instance_id": selection["instance_id"], "selection": selection,
            "retention": retention, "ocr_required": ocr_required,
            "languages": sorted(set(languages)),
            "baseline_settings": settings_fingerprint(ocr_settings_from_config(
                self.store.read_config())),
            "source_consents": self.consents(selection["source_id"]),
            "principal": principal,
            "recorded_at": existing["recorded_at"] if existing else utc_now(),
        })
        publish_once(self.store, permit_path(op_id), value)
        confirmations = [event for event in operation["events"]
                         if event["code"] == "setup.trial.authorized"]
        if not confirmations:
            OperationLedger(self.store).append(
                op_id, "setup.trial.authorized",
                "Only the displayed synthetic resources were authorized",
                details={"permit_sha256": digest(value)})
        elif len(confirmations) != 1 or confirmations[0]["details"] != {
                "permit_sha256": digest(value)}:
            raise ReviewDenied("This operation already has a different trial authorization")
        return self.read(op_id, check_inputs=True)

    def retained(self, op_id):
        """Validate history, including a crash before explicit confirmation finalized."""
        value = validate_permit(read_record(self.store, permit_path(op_id)))
        if value["id"] != op_id or value["instance_id"] != self.store.read_config()[
                "instance"]["id"]:
            raise ReviewDenied("The trial permit belongs to another operation or space")
        operation = OperationLedger(self.store).get(op_id)
        confirmations = [] if operation is None else [event for event in operation["events"]
                                                     if event["code"] == "setup.trial.authorized"]
        if (operation is None or operation["kind"] != "setup.trial"
                or operation["related"] != {"source_id": value["selection"]["source_id"]}
                or len(confirmations) > 1
                or (confirmations and confirmations[0]["details"] != {
                    "permit_sha256": digest(value)})
                or (not confirmations and operation["status"] != "running")):
            raise ReviewDenied("The trial has no matching explicit authorization record")
        return value, bool(confirmations)

    def read(self, op_id, *, current=True, check_inputs=False):
        value, confirmed = self.retained(op_id)
        if not confirmed:
            raise ReviewDenied("The trial authorization needs explicit submission recovery")
        if current:
            selection = value["selection"]
            root, revision, _folder = _source(self.store, selection["source_id"])
            with open_local_directory(root) as (_path, binding):
                if revision != selection["source_revision"] or binding != selection["root_binding"]:
                    raise ReviewStale("The selected Source or Inbox root changed")
            if (self.consents(selection["source_id"]) != value["source_consents"]
                    or settings_fingerprint(ocr_settings_from_config(self.store.read_config()))
                    != value["baseline_settings"]):
                raise ReviewStale("Source consent or OCR settings changed after the trial preview")
            if check_inputs:
                revalidate_selection(self.store, selection)
        return value

    def settings(self, op_id):
        permit = self.read(op_id)
        return replace(ocr_settings_from_config(self.store.read_config()), mode="automatic",
                       languages=tuple(permit["languages"]))

    def ocr_authorization(self, source_id, version_id, permit, acquisition):
        from .ocr_sources import version_input
        from .review_routing import _Inputs

        if (not isinstance(permit, dict) or set(permit) != {"kind", "id", "sha256"}
                or permit["kind"] != "setup-trial"):
            raise ReviewDenied("Select a typed bounded trial permit")
        value = self.read(permit["id"])
        if digest(value) != permit["sha256"] or source_id != value["selection"]["source_id"]:
            raise ReviewDenied("The trial permit does not select this Source")
        if not isinstance(acquisition, dict):
            raise ReviewDenied("The trial needs its exact committed acquisition")
        matching = [row for row in value["selection"]["inputs"]
                    if row["input"]["locator"] == acquisition.get("locator")]
        if (len(matching) != 1 or acquisition.get("source_id") != source_id
                or acquisition.get("version_id") != version_id
                or acquisition.get("id") != acquisition_id(value["id"], acquisition["locator"])
                or acquisition.get("content_hash") != matching[0]["input"]["sha256"]
                or read_json(self.store, f"knowledge/acquisitions/{acquisition['id']}.json")
                != acquisition):
            raise ReviewDenied("The trial cannot authorize another acquisition or Original")
        inputs = _Inputs(self.store)
        binding = version_input(inputs, source_id, version_id)
        inputs.record(f"knowledge/sources/{source_id}.json")
        if (binding["size_bytes"] != matching[0]["input"]["size_bytes"]
                or (matching[0]["fixture"] == "scan" and not value["ocr_required"])):
            raise ReviewDenied("The requested Original is outside the displayed trial")
        return {"source_id": source_id, "version": binding, "consent": digest(value),
                "permit": permit, "acquisition": acquisition,
                "settings_sha256": settings_fingerprint(self.settings(value["id"])),
                "source_sha256": inputs.hashes[f"knowledge/sources/{source_id}.json"],
                "languages": value["languages"]}
