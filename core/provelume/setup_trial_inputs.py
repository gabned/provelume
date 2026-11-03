"""Exact synthetic trial inputs; observing them grants no processing authority.

The ingestion, OCR and Inbox producers must independently consume the durable
trial permit. These bindings never enable a Source or enumerate its folder.
"""

from __future__ import annotations

import os
import re

from .action_center_model import digest
from .inbox_transit import _source, validate_input
from .maintenance_local_files import (
    directory_binding,
    file_identity,
    open_local_directory,
    open_local_file,
    stream_digest,
)
from .review_effects import ReviewDenied, ReviewStale, ReviewUnavailable, relative_path

# Public recipe 6573511376, independently reconstructed in 6573536197.
# Tokens occur in content only. The unrelated sentinel is never an allowed input.
FIXTURES = {
    "native": {"name": "native-text.pdf", "size_bytes": 880,
               "sha256": "3c04a38cad5c5ddcf98f1b8686bd8a2139f0a38b0682f048236a8cdf4a72414b"},
    "scan": {"name": "scan-it-en.pdf", "size_bytes": 38576,
             "sha256": "ed049286e2f8d89aa60f6dca1f86c0343dc8fb251bfd9cfa551bebe76982cf6d"},
}
SCHEMA = "setup-trial-inputs/v1"
FIELDS = {"schema", "instance_id", "source_id", "source_revision", "root_binding", "inputs"}
ROOT_ID = re.compile(r"(?:posix\.file-id\.v1:[0-9a-f]{32}|win32\.file-id\.v1:[0-9a-f]{48})\Z")


def validate_selection(value):
    if (not isinstance(value, dict) or set(value) != FIELDS or value["schema"] != SCHEMA
            or re.fullmatch(r"inst_[0-9a-f]{32}", str(value["instance_id"])) is None
            or re.fullmatch(r"src_[0-9a-f]{32}", str(value["source_id"])) is None
            or re.fullmatch(r"[0-9a-f]{64}", str(value["source_revision"])) is None
            or ROOT_ID.fullmatch(str(value["root_binding"])) is None
            or not isinstance(value["inputs"], list) or not 1 <= len(value["inputs"]) <= 2):
        raise ReviewUnavailable("The synthetic trial input selection is invalid")
    kinds, locators = [], []
    for row in value["inputs"]:
        if (not isinstance(row, dict) or set(row) != {"fixture", "input"}
                or not isinstance(row["fixture"], str) or row["fixture"] not in FIXTURES):
            raise ReviewUnavailable("The trial contains an unknown synthetic resource")
        item = validate_input(row["input"])
        expected = FIXTURES[row["fixture"]]
        if item["size_bytes"] != expected["size_bytes"] or item["sha256"] != expected["sha256"]:
            raise ReviewDenied("Only the displayed synthetic resource bytes may enter the trial")
        kinds.append(row["fixture"])
        locators.append(item["locator"])
    if (kinds != sorted(set(kinds)) or kinds[0] != "native"
            or len(locators) != len(set(locators))):
        raise ReviewUnavailable("The trial needs one native input and at most one scan")
    return value


def observe_selection(store, source_id, named_inputs):
    """Bind only explicitly named synthetic files, without scanning the Source."""
    if (not isinstance(named_inputs, dict) or not named_inputs
            or not set(named_inputs) <= set(FIXTURES) or "native" not in named_inputs):
        raise ReviewDenied("Select the displayed native resource and optional scan")
    root, revision, _folder = _source(store, source_id)
    rows = []
    with open_local_directory(root) as descriptor:
        binding = directory_binding(descriptor)
        for kind, locator in sorted(named_inputs.items()):
            relative_path(locator)
            expected = FIXTURES[kind]
            with open_local_file(root.joinpath(*locator.split("/"))) as stream:
                before = file_identity(stream)
                if (before["size_bytes"] != expected["size_bytes"]
                        or os.fstat(stream.fileno()).st_nlink != 1):
                    raise ReviewDenied("A trial input has different bytes or aliases another file")
                checksum, size = stream_digest(stream, expected["size_bytes"])
                if before != file_identity(stream):
                    raise ReviewStale("The synthetic input changed during observation")
            rows.append({"fixture": kind, "input": {"locator": locator, "identity": before,
                         "sha256": checksum, "size_bytes": size}})
        if directory_binding(descriptor) != binding:
            raise ReviewStale("The selected Inbox root changed")
    return validate_selection({"schema": SCHEMA,
                               "instance_id": store.read_config()["instance"]["id"],
                               "source_id": source_id, "source_revision": revision,
                               "root_binding": binding, "inputs": rows})


def revalidate_selection(store, selection):
    validate_selection(selection)
    if selection["instance_id"] != store.read_config()["instance"]["id"]:
        raise ReviewDenied("The trial input selection belongs to another space")
    current = observe_selection(store, selection["source_id"], {
        row["fixture"]: row["input"]["locator"] for row in selection["inputs"]})
    if digest(current) != digest(selection):
        raise ReviewStale("The selected Source, root or synthetic input changed")
    return current
