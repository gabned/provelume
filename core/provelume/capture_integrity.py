"""Pure, restart-time validation of Capture state and canonical acquisition bindings."""

import base64
import re

from .capture_adapter import CaptureAdapter
from .capture_authority import CaptureAuthority
from .capture_journal import CaptureJournalError, _safe
from .capture_quarantine import CaptureQuarantine


def capture_state_findings(store):
    manager = CaptureAdapter(store, authorize=lambda *args: None)
    try:
        manager.journal._read_ready()
        inventory = manager.journal._inventory()
        authority = CaptureAuthority(store).read()
        quarantine = CaptureQuarantine(store).read()
        receipts = {row["receipt"]["id"]: row for row in inventory.values()}
        root = store.paths.root / "state/capture-processing"
        _safe(root)
        if root.exists():
            for index, path in enumerate(root.iterdir()):
                _safe(path)
                if index >= 128 or not re.fullmatch(r"capture_[0-9a-f]{64}\.json", path.name):
                    raise CaptureJournalError("Invalid Capture processing inventory")
                scope = path.stem
                if scope not in receipts or not path.is_file():
                    raise CaptureJournalError("Capture processing has no submission")
                row = receipts[scope]
                manager._assure(
                    manager._record(f"state/capture-processing/{path.name}"),
                    row["receipt"],
                    base64.b64decode(row["payload_base64"], validate=True),
                )
        for scope in quarantine["items"]:
            if scope not in receipts or not (root / f"{scope}.json").is_file():
                raise CaptureJournalError("Capture quarantine has no acquired Original")
        for row in inventory.values():
            receipt = row["receipt"]
            if receipt["metadata"]["channel"] == "paired_pwa" and (
                authority is None or receipt["device_id"] not in authority["devices"]
            ):
                raise CaptureJournalError("Paired Capture has no retained device authority")
        manager.journal._read_ready()
    except (OSError, ValueError, TypeError, KeyError, RecursionError, CaptureJournalError) as exc:
        return [{"code": "capture_state_invalid", "path": "state/capture", "message": str(exc)}]
    return []
