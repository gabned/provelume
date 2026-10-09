"""Durable submissions are separate from acquisition and transport acceptance."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from uuid import uuid4

import pytest

from provelume import atomic_commit
from provelume import capture_journal as module
from provelume.capture_journal import CaptureJournal, CaptureJournalError
from provelume.instance_lifecycle import InstanceLifecycleBusy
from provelume.storage import InstanceStore

DEVICE = "dev_" + "a" * 32
CLIENT = "b5f127f9-1d95-4f6e-8c08-4c0729c775fa"


@pytest.mark.parametrize("reader", [module._read, module._read_pinned_windows_record])
def test_small_record_read_does_not_allocate_the_maximum(tmp_path, monkeypatch, reader):
    path = tmp_path / "small.json"
    payload = b'{"synthetic":"small public receipt"}'
    path.write_bytes(payload)
    requested = []
    fdopen = os.fdopen

    @contextmanager
    def observed(descriptor, mode):
        with fdopen(descriptor, mode) as stream:
            class Reader:
                def fileno(self):
                    return stream.fileno()

                def read(self, amount):
                    requested.append(amount)
                    return stream.read(amount)

            yield Reader()

    monkeypatch.setattr(os, "fdopen", observed)
    if os.name != "nt":
        monkeypatch.setattr(module, "_windows_open", lambda p, **_: os.open(p, os.O_RDONLY))
    assert reader(path, module.MAX_RECORD_BYTES) == payload
    assert requested == [len(payload) + 1]


def allow(device):
    assert device.startswith("dev_")


def validate(payload, metadata):
    assert isinstance(payload, bytes)
    assert metadata["mode"] == "text"


@pytest.fixture
def journal(tmp_path):
    return CaptureJournal(InstanceStore.initialise(tmp_path / "i"))


def metadata(**changes):
    return dict(
        schema_version=1,
        client_submission_id=CLIENT,
        captured_at="2026-09-26T12:34:56+02:00",
        mode="text",
        channel="paired_pwa",
        **changes,
    )


def submit(journal, payload=b"exact\x00bytes\xff", device=DEVICE, value=None, **guards):
    return journal.submit(
        device,
        payload,
        value or metadata(),
        transport_channel="paired_pwa",
        authorize=guards.get("authorize", allow),
        validate_payload=guards.get("validate_payload", validate),
    )


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_restart_replay_and_read_are_pure(journal):
    receipt = submit(journal)
    assert receipt["status"] == "committed"
    assert "acquisition_id" not in receipt
    before = tree(journal.store.paths.root)
    restarted = CaptureJournal(journal.store)
    assert restarted.lookup(DEVICE, CLIENT, authorize=allow) == receipt
    assert tree(journal.store.paths.root) == before
    assert submit(restarted) == receipt
    assert tree(journal.store.paths.root) == before
    receipt["metadata"]["note"] = "mutated response"
    assert "note" not in restarted.lookup(DEVICE, CLIENT, authorize=allow)["metadata"]


def test_absent_lookup_creates_nothing(journal):
    before = tree(journal.store.paths.root.parent)
    assert journal.lookup(DEVICE, CLIENT, authorize=allow) is None
    assert tree(journal.store.paths.root.parent) == before


@pytest.mark.parametrize("change", ["bytes", "metadata"])
def test_conflict_preserves_original(journal, change):
    receipt = submit(journal)
    before = tree(journal.store.paths.root)
    with pytest.raises(CaptureJournalError, match="conflicting"):
        submit(
            journal,
            payload=b"other" if change == "bytes" else b"exact\x00bytes\xff",
            value=metadata(note="other") if change == "metadata" else None,
        )
    assert tree(journal.store.paths.root) == before
    assert journal.lookup(DEVICE, CLIENT, authorize=allow) == receipt


def test_occurrences_and_devices_remain_distinct(journal):
    one = submit(journal)
    two = submit(journal, value={**metadata(), "client_submission_id": str(uuid4())})
    other = "dev_" + "b" * 32
    three = submit(journal, device=other)
    assert len({one["id"], two["id"], three["id"]}) == 3
    assert journal.lookup(other, CLIENT, authorize=allow) == three


@pytest.mark.parametrize("operation", ["lookup", "list", "replay"])
def test_inventory_rejects_identity_change_after_last_record(journal, monkeypatch, operation):
    submit(journal)
    before = tree(journal.root)
    validate_record = journal._validate

    def change_after_validation(*args, **kwargs):
        value = validate_record(*args, **kwargs)
        config = journal.store.read_config()
        config["instance"]["id"] = "instance_foreign"
        journal.store.write_config(config)
        return value

    monkeypatch.setattr(journal, "_validate", change_after_validation)
    with pytest.raises(CaptureJournalError, match="identity changed"):
        if operation == "lookup":
            journal.lookup(DEVICE, CLIENT, authorize=allow)
        elif operation == "list":
            journal.list_receipts(DEVICE, authorize=allow)
        else:
            submit(journal)
    assert tree(journal.root) == before


def test_inventory_identity_is_fresh_for_each_operation(journal):
    receipt = submit(journal)
    config = journal.store.read_config()
    assert journal.lookup(DEVICE, CLIENT, authorize=allow) == receipt
    foreign = {**config, "instance": {**config["instance"], "id": "instance_foreign"}}
    journal.store.write_config(foreign)
    before = tree(journal.root)
    with pytest.raises(CaptureJournalError, match="invalid Capture record"):
        journal.lookup(DEVICE, CLIENT, authorize=allow)
    assert tree(journal.root) == before
    journal.store.write_config(config)
    assert journal.lookup(DEVICE, CLIENT, authorize=allow) == receipt


@pytest.mark.skipif(os.name != "nt", reason="Windows directory share-access contract")
@pytest.mark.parametrize("fail_validation", [False, True])
def test_inventory_pins_ancestors_and_releases_handles(journal, monkeypatch, fail_validation):
    receipt = submit(journal)
    validate_record = journal._validate
    paths = [journal.store.paths.root, journal.root, journal.root / DEVICE]

    def while_pinned(*args, **kwargs):
        for path in paths:
            with pytest.raises(OSError):
                path.rename(path.with_name(path.name + "-moved"))
        if fail_validation:
            raise CaptureJournalError("test validation failure")
        return validate_record(*args, **kwargs)

    monkeypatch.setattr(journal, "_validate", while_pinned)
    if fail_validation:
        with pytest.raises(CaptureJournalError, match="test validation failure"):
            journal.lookup(DEVICE, CLIENT, authorize=allow)
    else:
        assert journal.lookup(DEVICE, CLIENT, authorize=allow) == receipt
    for path in paths:
        moved = path.with_name(path.name + "-moved")
        path.rename(moved)
        moved.rename(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows record share-access contract")
def test_inventory_record_denies_writes_and_delete_during_read(journal, monkeypatch):
    receipt = submit(journal)
    path = next(journal.root.rglob("*.json"))
    original_fstat = os.fstat
    observed = []

    def while_open(descriptor):
        info = original_fstat(descriptor)
        if info.st_ino == path.stat().st_ino:
            with pytest.raises(OSError):
                path.write_bytes(b"corruption")
            with pytest.raises(OSError):
                path.unlink()
            observed.append(True)
        return info

    monkeypatch.setattr(module.os, "fstat", while_open)
    assert journal.lookup(DEVICE, CLIENT, authorize=allow) == receipt
    assert observed
    monkeypatch.setattr(module.os, "fstat", original_fstat)
    # Release is observable: a subsequent modification is read and rejected,
    # rather than hidden by a cached inventory or a leaked read handle.
    path.write_bytes(b"corruption")
    with pytest.raises(CaptureJournalError, match="invalid Capture record"):
        journal.lookup(DEVICE, CLIENT, authorize=allow)


@pytest.mark.parametrize("operation", ["new", "replay", "lookup"])
def test_revocation_rechecked(journal, operation):
    if operation != "new":
        submit(journal)
    before = tree(journal.store.paths.root)

    def deny(device):
        raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        if operation == "lookup":
            journal.lookup(DEVICE, CLIENT, authorize=deny)
        else:
            submit(journal, authorize=deny)
    assert tree(journal.store.paths.root) == before


def test_payload_guard_rejects_before_commit(journal):
    def reject(payload, metadata):
        raise ValueError("unsupported bytes")

    with pytest.raises(ValueError, match="unsupported"):
        submit(journal, validate_payload=reject)
    assert not journal.root.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("instance_id", "foreign"),
        ("payload_base64", "***"),
    ],
)
def test_corrupt_records_fail_without_reset(journal, field, value):
    submit(journal)
    path = next(journal.root.rglob("*.json"))
    record = json.loads(path.read_bytes())
    record[field] = value
    path.write_text(json.dumps(record))
    before = tree(journal.store.paths.root)
    with pytest.raises(CaptureJournalError):
        journal.lookup(DEVICE, CLIENT, authorize=allow)
    with pytest.raises(CaptureJournalError):
        submit(journal)
    assert tree(journal.store.paths.root) == before


def test_hash_collision_cannot_override_exact_identity(journal, monkeypatch):
    receipt = submit(journal)
    monkeypatch.setattr(
        module, "capture_payload_fingerprint", lambda *a, **k: receipt["fingerprint"]
    )
    with pytest.raises(CaptureJournalError, match="conflicting"):
        submit(journal, payload=b"different")


def test_limits_keep_replay_available(journal, monkeypatch):
    receipt = submit(journal)
    monkeypatch.setattr(module, "MAX_RECORDS", 1)
    assert submit(journal) == receipt
    with pytest.raises(CaptureJournalError, match="full"):
        submit(journal, value={**metadata(), "client_submission_id": str(uuid4())})


def test_concurrent_writer_is_busy_then_reconciles(journal):
    entered, release = Event(), Event()

    def guard(payload, metadata):
        entered.set()
        assert release.wait(5)

    with ThreadPoolExecutor(1) as pool:
        writer = pool.submit(submit, journal, validate_payload=guard)
        assert entered.wait(5)
        try:
            with pytest.raises(InstanceLifecycleBusy):
                submit(CaptureJournal(journal.store))
        finally:
            release.set()
        receipt = writer.result()
    assert submit(journal) == receipt
    assert len(list(journal.root.rglob("*.json"))) == 1


@pytest.mark.parametrize("point", ["prepared", "replaced", "committed"])
def test_interruption_reconciles_before_retry(journal, monkeypatch, point):
    original_replace = atomic_commit.replace_file
    original_write = journal.store._atomic_bytes

    def replace(source, target):
        if point == "prepared":
            raise SystemExit("interrupted")
        original_replace(source, target)
        raise SystemExit("interrupted")

    def write(path, data):
        original_write(path, data)
        if path.name == "manifest.json" and b'"status": "committed"' in data:
            raise SystemExit("interrupted")

    if point == "committed":
        monkeypatch.setattr(journal.store, "_atomic_bytes", write)
    else:
        # The constructor's default is bound at import time.
        factory = module.AtomicInstanceCommit
        monkeypatch.setattr(
            module, "AtomicInstanceCommit", lambda *a, **k: factory(*a, **k, replace=replace)
        )
    with pytest.raises(SystemExit):
        submit(journal)
    monkeypatch.undo()
    before = tree(journal.store.paths.root.parent)
    with pytest.raises(CaptureJournalError, match="recovery required"):
        journal.lookup(DEVICE, CLIENT, authorize=allow)
    assert tree(journal.store.paths.root.parent) == before
    InstanceStore.open(journal.store.paths.root)
    receipt = submit(CaptureJournal(journal.store))
    assert submit(journal) == receipt
    assert len(list(journal.root.rglob("*.json"))) == 1
    assert not list((journal.lifecycle.control_root / "transactions").glob("capture-*"))


def test_recovery_rejects_foreign_target(journal, monkeypatch):
    factory = module.AtomicInstanceCommit

    def stop(source, target):
        raise SystemExit()

    monkeypatch.setattr(
        module, "AtomicInstanceCommit", lambda *a, **k: factory(*a, **k, replace=stop)
    )
    with pytest.raises(SystemExit):
        submit(journal)
    monkeypatch.undo()
    manifest = next(
        (journal.lifecycle.control_root / "transactions").glob("capture-*/manifest.json")
    )
    value = json.loads(manifest.read_bytes())
    value["entries"][0]["relative"] = "instance.yaml"
    manifest.write_text(json.dumps(value))
    before = tree(journal.store.paths.root)
    with pytest.raises(CaptureJournalError, match="allowlist"):
        submit(journal)
    assert tree(journal.store.paths.root) == before


def test_lists_are_device_scoped_and_pure(journal):
    receipt = submit(journal)
    other = "dev_" + "b" * 32
    submit(journal, device=other)
    before = tree(journal.store.paths.root.parent)
    assert journal.list_receipts(DEVICE, authorize=allow) == [receipt]
    assert tree(journal.store.paths.root.parent) == before


@pytest.mark.parametrize("point", ["replaced", "committed"])
def test_process_death_releases_lock_and_open_recovers(journal, point):
    script = """
import json, os, sys
from provelume.capture_journal import CaptureJournal
from provelume import capture_journal as module
from provelume.storage import InstanceStore
from provelume.atomic_commit import replace_file
store = InstanceStore(sys.argv[1])
journal = CaptureJournal(store)
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
journal.submit(sys.argv[3], b'exact', json.loads(sys.argv[4]), transport_channel='paired_pwa',
               authorize=lambda d: None, validate_payload=lambda b, m: None)
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(journal.store.paths.root),
            point,
            DEVICE,
            json.dumps(metadata()),
        ],
        env=env,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 73, result.stderr.decode(errors="replace")
    record = next(journal.root.rglob("*.json"))
    interrupted_receipt = json.loads(record.read_bytes())["receipt"]
    journal.lifecycle.prepare()
    receipt = journal.lookup(DEVICE, CLIENT, authorize=allow)
    if point == "committed":
        assert receipt == interrupted_receipt
    else:
        assert receipt is None
    committed = submit(journal, payload=b"exact")
    assert submit(journal, payload=b"exact") == committed


def test_duplicate_fields_and_byte_capacity_fail_closed(journal, monkeypatch):
    submit(journal)
    path = next(journal.root.rglob("*.json"))
    original = path.read_bytes()
    path.write_bytes(original.replace(b"{", b'{"schema_version":1,', 1))
    with pytest.raises(CaptureJournalError):
        journal.lookup(DEVICE, CLIENT, authorize=allow)
    path.write_bytes(original)
    monkeypatch.setattr(module, "MAX_JOURNAL_BYTES", len(original) + 1)
    with pytest.raises(CaptureJournalError, match="byte budget"):
        submit(journal, value={**metadata(), "client_submission_id": str(uuid4())})
    assert path.read_bytes() == original
