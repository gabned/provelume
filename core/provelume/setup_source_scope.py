"""Restrictions on the existing folder observer, never new ingestion authority.

Trial-owned names cannot enter ordinary Source/AI processing. A newly prepared
Source can admit future arrivals without importing its existing backlog. Neither
record creates a watcher, queue, Source consent or permission to remove an input.
"""

import os
import re
import stat

from .folder_source_model import FolderSourceError
from .index_evidence import publish_once
from .maintenance_local_files import open_local_directory
from .operations import OperationLedger
from .review_decisions import checked_path
from .review_effects import ReviewDenied, ReviewUnavailable, relative_path
from .setup_trial_authority import ROOT, operation_id, read_record
from .setup_trial_inputs import FIXTURES, ROOT_ID

BASELINES = "state/setup-source-baselines"
CLAIMS = ROOT + "/source-claims"
BASELINE_BYTES = 512 * 1024


def _baseline(store, source_id):
    return read_record(store, f"{BASELINES}/{_source_id(source_id)}.json",
                       maximum=BASELINE_BYTES)


def _source_id(value):
    if not isinstance(value, str) or re.fullmatch(r"src_[0-9a-f]{32}", value) is None:
        raise ReviewUnavailable("The setup Source reference is invalid")
    return value


def _identity(path):
    observed = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(observed.st_mode):
        raise ReviewUnavailable("Only regular input metadata may enter the setup baseline")
    return {"device": observed.st_dev, "inode": observed.st_ino,
            "size_bytes": observed.st_size, "mtime_ns": observed.st_mtime_ns,
            "ctime_ns": observed.st_ctime_ns}


def validate_claim(store, value):
    if (not isinstance(value, dict) or set(value) != {
            "schema", "id", "instance_id", "source_id", "root_binding", "resources"}
            or value["schema"] != "setup-trial-source-claim/v1"
            or value["instance_id"] != store.read_config()["instance"]["id"]
            or ROOT_ID.fullmatch(str(value["root_binding"])) is None
            or not isinstance(value["resources"], list) or not 1 <= len(value["resources"]) <= 2):
        raise ReviewUnavailable("The trial Source claim has an invalid closed schema")
    _source_id(value["source_id"])
    operation = OperationLedger(store).get(operation_id(value["id"]))
    if (operation is None or operation["kind"] != "setup.trial"
            or operation["related"] != {"source_id": value["source_id"]}):
        raise ReviewUnavailable("The trial input names have no owning operation")
    kinds, locators = [], []
    for row in value["resources"]:
        if (not isinstance(row, dict) or set(row) != {"fixture", "locator", "sha256", "size_bytes"}
                or not isinstance(row["fixture"], str) or row["fixture"] not in FIXTURES
                or row["sha256"] != FIXTURES[row["fixture"]]["sha256"]
                or type(row["size_bytes"]) is not int
                or row["size_bytes"] != FIXTURES[row["fixture"]]["size_bytes"]):
            raise ReviewUnavailable("The trial name claim selects another resource")
        relative_path(row["locator"])
        suffix = FIXTURES[row['fixture']]['name']
        expected_name = f"setup-{value['id'].removeprefix('op_')}-{suffix}"
        if row["locator"] != expected_name:
            raise ReviewDenied("The trial cannot reserve another input name")
        kinds.append(row["fixture"])
        locators.append(row["locator"])
    if kinds != sorted(set(kinds)) or kinds[0] != "native" or len(set(locators)) != len(locators):
        raise ReviewUnavailable("The trial resource name selection is invalid")
    return value


def claim_trial_names(store, op_id, source_id, binding, named):
    value = {"schema": "setup-trial-source-claim/v1", "id": op_id,
             "instance_id": store.read_config()["instance"]["id"], "source_id": source_id,
             "root_binding": binding,
             "resources": [{"fixture": kind, "locator": locator,
                            "sha256": FIXTURES[kind]["sha256"],
                            "size_bytes": FIXTURES[kind]["size_bytes"]}
                           for kind, locator in sorted(named.items())]}
    validate_claim(store, value)
    relative = f"{CLAIMS}/{_source_id(source_id)}/{operation_id(op_id)}.json"
    publish_once(store, relative, value)
    return value


def validate_baseline(store, value):
    if (not isinstance(value, dict) or set(value) != {
            "schema", "source_id", "instance_id", "operation_id", "root_binding", "inputs"}
            or value["schema"] != "setup-source-baseline/v1"
            or value["instance_id"] != store.read_config()["instance"]["id"]
            or ROOT_ID.fullmatch(str(value["root_binding"])) is None
            or not isinstance(value["inputs"], list) or len(value["inputs"]) > 1000):
        raise ReviewUnavailable("The future-input baseline has an invalid closed schema")
    _source_id(value["source_id"])
    operation = OperationLedger(store).get(operation_id(value["operation_id"]))
    if (operation is None or operation["kind"] != "setup.apply"
            or operation["related"] != {"source_id": value["source_id"]}):
        raise ReviewUnavailable("The baseline has no corresponding explicit setup application")
    locators = []
    for row in value["inputs"]:
        if (not isinstance(row, dict) or set(row) != {"locator", "identity"}
                or not isinstance(row["identity"], dict) or set(row["identity"]) != {
                    "device", "inode", "size_bytes", "mtime_ns", "ctime_ns"}
                or any(type(v) is not int or v < 0 for v in row["identity"].values())
                or not row["identity"]["inode"]):
            raise ReviewUnavailable("The baseline input metadata is invalid")
        relative_path(row["locator"])
        locators.append(row["locator"])
    if locators != sorted(set(locators)):
        raise ReviewUnavailable("The baseline input names are not unique and ordered")
    return value


def baseline_preview(store, source_id):
    from .folder_sources import FolderSourceManager
    from .ingest import _iter_files
    from .source_exclusions import policy_for_source

    manager = FolderSourceManager(store)
    _source, _config, folder = manager._configured(source_id)
    if folder["lifecycle_state"] != "paused":
        raise ReviewDenied("A new Source must remain paused until its baseline is confirmed")
    root = store.source_path(source_id)
    with open_local_directory(root) as (_path, binding):
        inputs = [{"locator": locator, "identity": _identity(path)} for locator, path in
                  _iter_files(root, folder["max_files"], policy_for_source(store, source_id))]
    return {"source_id": source_id, "root_binding": binding,
            "inputs": sorted(inputs, key=lambda row: row["locator"])}


def install_baseline(store, op_id, preview):
    source_id = _source_id(preview["source_id"])
    existing = _baseline(store, source_id)
    if existing is not None:
        return validate_baseline(store, existing)
    if baseline_preview(store, source_id) != preview:
        raise ReviewDenied("The new Source inputs changed after the activation preview")
    value = validate_baseline(store, {"schema": "setup-source-baseline/v1", **preview,
                                     "instance_id": store.read_config()["instance"]["id"],
                                     "operation_id": op_id})
    publish_once(store, f"{BASELINES}/{source_id}.json", value)
    return value


def eligible_inputs(store, source_id, root, files):
    """Restrict the existing observer/ingestion selection; inspect no file content."""
    from .setup_coordinator import assert_admission_ready

    if re.fullmatch(r"src_[0-9a-f]{32}", source_id) is None:
        # Historical Sources outside the setup profile retain normal intake.
        return files
    try:
        assert_admission_ready(store, source_id)
    except ValueError as exc:
        raise FolderSourceError("The explicit setup application needs recovery") from exc
    baseline_path = f"{BASELINES}/{source_id}.json"
    claims_path = f"{CLAIMS}/{source_id}"
    if (not checked_path(store, baseline_path).exists()
            and not checked_path(store, claims_path).exists()):
        return files
    try:
        baseline = _baseline(store, source_id)
        if baseline is not None:
            validate_baseline(store, baseline)
            if baseline["source_id"] != source_id:
                raise ReviewUnavailable("The baseline belongs to another Source")
        claimed = set()
        with open_local_directory(root) as (_path, binding):
            if baseline is not None and binding != baseline["root_binding"]:
                raise ReviewDenied("The setup Source root changed before observation")
            directory = checked_path(store, claims_path)
            if directory.exists():
                for index, path in enumerate(directory.iterdir()):
                    if index >= 1000 or path.suffix != ".json":
                        raise ReviewUnavailable("The trial Source claim inventory is too large")
                    claim = validate_claim(store, read_record(
                        store, f"{claims_path}/{operation_id(path.stem)}.json"))
                    if claim["source_id"] != source_id:
                        raise ReviewDenied("The trial claim belongs to another Source")
                    if claim["root_binding"] == binding:
                        claimed.update(row["locator"] for row in claim["resources"])
            previous = {} if baseline is None else {
                row["locator"]: row["identity"] for row in baseline["inputs"]}
            return [(locator, path) for locator, path in files if locator not in claimed
                    and (locator not in previous or _identity(path) != previous[locator])]
    except (ValueError, KeyError, OSError, TypeError) as exc:
        raise FolderSourceError("The scoped setup Source selection needs review") from exc


def baseline_findings(store):
    findings = []
    try:
        root = checked_path(store, BASELINES)
        if root.exists():
            for index, path in enumerate(root.iterdir()):
                if index >= 128 or path.suffix != ".json":
                    raise ReviewUnavailable("The setup baseline inventory exceeds its bound")
                source_id = _source_id(path.stem)
                value = validate_baseline(store, _baseline(store, source_id))
                if value["source_id"] != source_id:
                    raise ReviewUnavailable("The setup baseline path has another Source identity")
    except (ValueError, KeyError, OSError, TypeError) as exc:
        findings.append({"code": "setup_source_baseline_invalid", "path": BASELINES,
                         "message": str(exc)})
    return findings
