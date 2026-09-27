"""Capture acknowledgement and acquisition survive independent failures."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event
from uuid import uuid4

import pytest
from pypdf import PdfWriter

from provelume import capture_adapter as module
from provelume.atomic_commit import AtomicCommitIntegrityError, replace_file
from provelume.capture_adapter import CaptureAdapter
from provelume.capture_journal import CaptureJournalError
from provelume.capture_payloads import capture_capabilities, validate_capture_payload
from provelume.capture_requests import CaptureRequestError
from provelume.extractors import ExtractionError
from provelume.instance_lifecycle import InstanceLifecycleBusy
from provelume.storage import InstanceStore

DEVICE = "dev_" + "a" * 32
CLIENT = "b5f127f9-1d95-4f6e-8c08-4c0729c775fa"
CHANNEL = "local_browser"


def metadata(**changes):
    return {
        "schema_version": 1,
        "client_submission_id": CLIENT,
        "captured_at": "2026-09-26T12:34:56+02:00",
        "mode": "text",
        "channel": CHANNEL,
        **changes,
    }


@pytest.fixture
def adapter(tmp_path):
    return CaptureAdapter(InstanceStore.initialise(tmp_path / "i"), authorize=lambda *a: None)


def submit(adapter, payload=b"Captured text", device=DEVICE, **changes):
    return adapter.submit(device, payload, metadata(**changes), channel=CHANNEL)


def process(adapter, device=DEVICE, client=CLIENT):
    return adapter.process(device, client, channel=CHANNEL)


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_submission_is_not_acquisition_and_reads_are_pure(adapter):
    submitted = submit(adapter)
    before = tree(adapter.store.paths.root.parent)
    detail = adapter.detail(DEVICE, CLIENT, channel=CHANNEL)
    assert detail == {"submission": submitted, "acquisition": None}
    assert tree(adapter.store.paths.root.parent) == before
    assert adapter.store.list_canonical("acquisitions") == []
    acquired = process(adapter)["receipt"]
    assert acquired["processing"]["status"] == "completed"
    assert acquired["received_at"] == submitted["received_at"]
    restarted = CaptureAdapter(adapter.store, authorize=lambda *a: None)
    before = tree(adapter.store.paths.root.parent)
    assert restarted.detail(DEVICE, CLIENT, channel=CHANNEL)["acquisition"] == acquired
    assert tree(adapter.store.paths.root.parent) == before
    assert process(restarted)["receipt"] == acquired
    assert len(adapter.store.list_canonical("acquisitions")) == 1
    assert submit(restarted) == submitted


def test_occurrences_and_devices_share_bytes_but_not_acquisition(adapter):
    submit(adapter)
    first = process(adapter)["receipt"]
    client = str(uuid4())
    submit(adapter, client_submission_id=client)
    second = process(adapter, client=client)["receipt"]
    other = "dev_" + "b" * 32
    submit(adapter, device=other)
    third = process(adapter, device=other)["receipt"]
    assert first["source_id"] == second["source_id"] != third["source_id"]
    assert len({r["acquisition_id"] for r in [first, second, third]}) == 3
    assert len({r["original_id"] for r in [first, second, third]}) == 1
    assert len(adapter.store.list_canonical("acquisitions")) == 3


def test_current_authority_required_for_replay_process_and_read(adapter):
    submit(adapter)
    process(adapter)

    def deny(*args):
        raise PermissionError("revoked")

    adapter.authorize = deny
    before = tree(adapter.store.paths.root.parent)
    for action in [
        lambda: submit(adapter),
        lambda: process(adapter),
        lambda: adapter.detail(DEVICE, CLIENT, channel=CHANNEL),
    ]:
        with pytest.raises(PermissionError, match="revoked"):
            action()
    assert tree(adapter.store.paths.root.parent) == before


def test_channel_cannot_claim_receipt(adapter):
    submit(adapter)
    with pytest.raises(PermissionError, match="channel"):
        adapter.process(DEVICE, CLIENT, channel="paired_pwa")
    with pytest.raises(PermissionError, match="channel"):
        adapter.detail(DEVICE, CLIENT, channel="paired_pwa")


def test_reference_existence_and_authority_are_guards(adapter, monkeypatch):
    reference = "area_" + "a" * 32
    with pytest.raises(CaptureJournalError, match="reference"):
        submit(adapter, area_id=reference)
    monkeypatch.setattr(module.HierarchyManager, "get_node", lambda *a: {"kind": "area"})

    def guard(device, channel, proposed):
        if proposed:
            raise PermissionError("reference denied")

    adapter.authorize = guard
    with pytest.raises(PermissionError, match="reference denied"):
        submit(adapter, area_id=reference)
    assert adapter.store.list_canonical("acquisitions") == []


def test_capacity_denial_preserves_historical_acknowledgement(adapter, monkeypatch):
    receipt = submit(adapter)
    monkeypatch.setattr(
        module.CapacityAdmission,
        "check_admission",
        lambda *a, **k: {"allowed": False, "reason": "manual_pause"},
    )
    assert submit(adapter) == receipt
    with pytest.raises(CaptureJournalError, match="capacity"):
        submit(adapter, client_submission_id=str(uuid4()))
    with pytest.raises(CaptureJournalError, match="capacity"):
        process(adapter)
    assert adapter.detail(DEVICE, CLIENT, channel=CHANNEL)["acquisition"] is None


def test_extraction_and_index_failure_do_not_rollback_original(adapter, monkeypatch):
    submit(adapter)

    def failed(*a):
        raise ExtractionError("unavailable")

    monkeypatch.setattr(module, "extract_capture_payload", failed)
    monkeypatch.setattr(module, "refresh_search_index", lambda *a: (_ for _ in ()).throw(OSError()))
    acquired = process(adapter)
    assert acquired["receipt"]["processing"]["status"] == "attention"
    assert acquired["search_index"] == "attention"
    assert len(adapter.store.list_canonical("acquisitions")) == 1
    assert process(adapter)["receipt"] == acquired["receipt"]


@pytest.mark.parametrize("point", ["prepared", "replaced", "committed"])
def test_interrupted_acquisition_recovers_without_losing_submission(adapter, monkeypatch, point):
    submitted = submit(adapter)
    factory = module.AtomicInstanceCommit

    def replace(source, target):
        if point == "replaced":
            replace_file(source, target)
        raise SystemExit()

    original_write = adapter.store._atomic_bytes

    def write(path, data):
        original_write(path, data)
        if path.name == "manifest.json" and b'"status": "committed"' in data:
            raise SystemExit()

    if point == "committed":
        monkeypatch.setattr(adapter.store, "_atomic_bytes", write)
    else:
        monkeypatch.setattr(
            module, "AtomicInstanceCommit", lambda *a, **k: factory(*a, **k, replace=replace)
        )
    with pytest.raises(SystemExit):
        process(adapter)
    monkeypatch.undo()
    before = tree(adapter.store.paths.root.parent)
    with pytest.raises(CaptureJournalError, match="recovery required"):
        adapter.detail(DEVICE, CLIENT, channel=CHANNEL)
    assert tree(adapter.store.paths.root.parent) == before
    acquired = process(adapter)["receipt"]
    assert acquired == process(adapter)["receipt"]
    assert submit(adapter) == submitted
    assert len(adapter.store.list_canonical("acquisitions")) == 1


@pytest.mark.parametrize("point", ["replaced", "committed"])
def test_process_death_releases_lock_and_retry_reconciles(adapter, point):
    submit(adapter)
    script = """
import os, sys
from provelume import capture_adapter as module
from provelume.atomic_commit import replace_file
from provelume.storage import InstanceStore
store = InstanceStore(sys.argv[1])
adapter = module.CaptureAdapter(store, authorize=lambda *a: None)
factory = module.AtomicInstanceCommit
def replace(source, target):
    replace_file(source, target)
    os._exit(73)
original = store._atomic_bytes
def write(path, data):
    original(path, data)
    if path.name == 'manifest.json' and b'"status": "committed"' in data:
        os._exit(73)
if sys.argv[2] == 'replaced':
    module.AtomicInstanceCommit = lambda *a, **k: factory(*a, **k, replace=replace)
else:
    store._atomic_bytes = write
adapter.process(sys.argv[3], sys.argv[4], channel='local_browser')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(adapter.store.paths.root), point, DEVICE, CLIENT],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        timeout=30,
    )
    assert result.returncode == 73
    assert process(adapter)["receipt"] == process(adapter)["receipt"]
    assert len(adapter.store.list_canonical("acquisitions")) == 1


def test_concurrent_processing_is_busy_then_idempotent(adapter, monkeypatch):
    submit(adapter)
    entered, release = Event(), Event()
    extract = module.extract_capture_payload

    def blocking(*args):
        entered.set()
        assert release.wait(5)
        return extract(*args)

    monkeypatch.setattr(module, "extract_capture_payload", blocking)
    with ThreadPoolExecutor(1) as pool:
        writer = pool.submit(process, adapter)
        assert entered.wait(5)
        try:
            with pytest.raises(InstanceLifecycleBusy):
                process(adapter)
        finally:
            release.set()
        receipt = writer.result()["receipt"]
    assert process(adapter)["receipt"] == receipt


def test_corrupt_original_is_not_repaired_by_replay(adapter):
    submit(adapter)
    receipt = process(adapter)["receipt"]
    digest = receipt["payload_sha256"]
    path = adapter.store.paths.root / f"originals/sha256/{digest[:2]}/{digest}"
    path.write_bytes(b"changed")
    with pytest.raises(CaptureJournalError, match="Original"):
        process(adapter)
    assert path.read_bytes() == b"changed"


def test_acquisition_identity_collision_fails_without_overwriting(adapter, monkeypatch):
    submit(adapter)
    first = process(adapter)["receipt"]
    client = str(uuid4())
    submitted = submit(adapter, client_submission_id=client)
    coordinates = adapter._coordinates

    def collision(*args):
        return {**coordinates(*args), "acquisition_id": first["acquisition_id"]}

    monkeypatch.setattr(adapter, "_coordinates", collision)
    with pytest.raises(AtomicCommitIntegrityError):
        process(adapter, client=client)
    assert len(adapter.store.list_canonical("acquisitions")) == 1
    assert adapter.journal.lookup(DEVICE, client, authorize=lambda d: None) == submitted


def test_interrupted_routing_cannot_rollback_acquisition(adapter, monkeypatch):
    submitted = submit(adapter)

    def interrupted(*a):
        raise SystemExit()

    monkeypatch.setattr(module, "route_committed_acquisitions_locked", interrupted)
    with pytest.raises(SystemExit):
        process(adapter)
    acquired = adapter.detail(DEVICE, CLIENT, channel=CHANNEL)["acquisition"]
    monkeypatch.undo()
    assert process(adapter)["receipt"] == acquired
    assert submit(adapter) == submitted
    assert len(adapter.store.list_canonical("acquisitions")) == 1


def test_foreign_recovery_target_is_rejected(adapter, monkeypatch):
    submit(adapter)
    factory = module.AtomicInstanceCommit

    def stop(*a):
        raise SystemExit()

    monkeypatch.setattr(
        module, "AtomicInstanceCommit", lambda *a, **k: factory(*a, **k, replace=stop)
    )
    with pytest.raises(SystemExit):
        process(adapter)
    monkeypatch.undo()
    manifest = next(
        (adapter.journal.lifecycle.control_root / "transactions").glob(
            "capture-acquisition-*/manifest.json"
        )
    )
    value = json.loads(manifest.read_bytes())
    value["entries"][0]["relative"] = "instance.yaml"
    manifest.write_text(json.dumps(value))
    before = tree(adapter.store.paths.root)
    with pytest.raises((CaptureJournalError, AtomicCommitIntegrityError)):
        process(adapter)
    assert tree(adapter.store.paths.root) == before


@pytest.mark.parametrize(
    "payload,changes",
    [
        (b"\xff", {}),
        (b"a\x00b", {}),
        (b"a" * (512 * 1024 + 1), {}),
        (b"x", {"mode": "photo"}),
        (b"x", {"mode": "file", "filename": "a.html"}),
        (b"x", {"declared_mime": "application/pdf"}),
        (b"%PDF-1.7\n%%EOF", {"mode": "pdf"}),
        (b"javascript:alert(1)", {"mode": "url"}),
        (b"https://user:secret@example.test/", {"mode": "url"}),
        (b"https://example.test\\evil/", {"mode": "url"}),
        (b"https://example.test/ a", {"mode": "url"}),
    ],
    ids=lambda value: "bytes" if isinstance(value, bytes) else "metadata",
)
def test_rejected_payload_is_never_acknowledged(adapter, payload, changes):
    with pytest.raises(CaptureRequestError):
        submit(adapter, payload, **changes)
    assert adapter.journal.list_receipts(DEVICE, authorize=lambda d: None) == []


def test_declared_capabilities_match_text_url_and_pdf_validation():
    matrix = capture_capabilities()
    assert matrix["paired_transport"] == "unavailable"
    assert matrix["modes"]["url"]["fetch"] is False
    assert validate_capture_payload(b"https://example.test/", metadata(mode="url"))
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    assert validate_capture_payload(output.getvalue(), metadata(mode="pdf")).media_type == (
        "application/pdf"
    )
