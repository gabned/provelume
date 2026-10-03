from __future__ import annotations

import dataclasses
import io
import json
import os
import socket
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from ai_model_fixtures import LICENSE, Download, package, runner

from provelume import ai_model_store as storage
from provelume.ai_model_store import ModelStore, default_runtime, inspect_package
from provelume.ai_models import (
    MANIFEST_SHA256,
    ModelError,
    ModelRegistry,
    parse_manifest,
    sha256,
)
from provelume.component_inventory import ComponentInventory
from provelume.service import ProvelumeInstance

V1, V2 = "fixture.model-v1", "fixture.model-v2"
REQUEST = {"requested": True, "license_accepted": "CC0-1.0"}


@pytest.fixture
def store(tmp_path):
    return ModelStore(tmp_path / "ai-models")


@pytest.fixture
def runtime():
    return default_runtime()


def install(store, runtime, version="1"):
    return store.install(f"fixture.model-v{version}", runtime,
                         transport=Download(package(version)), **REQUEST)


def activate(store, runtime, version="1"):
    identifier = f"fixture.model-v{version}"
    evidence = store.self_test(identifier, runtime, runner, requested=True)
    return store.activate(identifier, runtime, evidence, requested=True)


def test_governed_manifest_separates_identity_trust_and_qualification():
    registry = ModelRegistry.packaged()
    assert sha256(registry.raw) == MANIFEST_SHA256
    for entry in registry.entries:
        assert entry.package_sha256 == sha256(package(entry.version))
        assert entry.qualification == "SYNTHETIC_ONLY"
        assert entry.profile.model == "fixture.model"
        assert entry.profile.revision == entry.model_sha256
    record = registry.inventory()
    assert record == ComponentInventory.model_registry()
    assert record["recommended"] is None
    assert all(e["status"] == "unverified" and not e["offline_qualified"]
               for e in record["entries"])
    changed = json.loads(registry.raw)
    changed["entries"][0]["channel"] = "stable"
    raw = json.dumps(changed).encode()
    assert parse_manifest(raw)[0].channel == "stable"
    with pytest.raises(ModelError, match="untrusted"):
        ModelRegistry(raw)  # Even a consistent caller-supplied hash is not approval.


@pytest.mark.parametrize(("field", "value"), [
    ("unknown", "hook.py"), ("runtime_id", "llama.cpp"), ("runtime_version", "2"),
    ("format", "pickle"), ("format", "gguf-v3"), ("format", "onnx"),
    ("qualification", "OFFLINE_QUALIFIED"), ("channel", "recommended"),
    ("app_version", "0.12.0"), ("id", "../model"), ("version", True),
    ("license", "unknown"), ("origin", "https://other.invalid"),
    ("url", "http://fixtures.invalid/a.zip"), ("url", "https://user:secret@fixtures.invalid/a"),
    ("url", "https://fixtures.invalid/a?secret=value"),
    ("package_size", 200000), ("package_size", True), ("model_size", -1),
    ("model_sha256", "abc"), ("evidence", "untrusted-companion.sha256"),
])
def test_closed_manifest(field, value):
    payload = json.loads(ModelRegistry.packaged().raw)
    payload["entries"][0][field] = value
    with pytest.raises(ModelError):
        parse_manifest(json.dumps(payload).encode())


@pytest.mark.parametrize("raw", [b"{", b"\xff", b'{"schema_version":1,"schema_version":1}',
                                 b"[" * 2000, b" " * 40000, b"null"],
                         ids=["truncated", "encoding", "duplicate", "depth", "size", "null"])
def test_invalid_manifest_bytes(raw):
    with pytest.raises(ModelError):
        parse_manifest(raw)


def test_duplicate_manifest_id_and_unknown_top_level():
    payload = json.loads(ModelRegistry.packaged().raw)
    payload["entries"][1] = payload["entries"][0]
    with pytest.raises(ModelError):
        parse_manifest(json.dumps(payload).encode())
    payload["token"] = "SYNTHETIC_SECRET"
    with pytest.raises(ModelError) as error:
        parse_manifest(json.dumps(payload).encode())
    assert "SYNTHETIC_SECRET" not in str(error.value)


def test_actual_install_import_verify_and_explicit_activation(store, runtime, tmp_path):
    source = tmp_path / "offline.zip"
    source.write_bytes(package())
    assert store.import_offline(V1, source, runtime, **REQUEST)["activated"] is False
    assert store.verify(V1, runtime).license == LICENSE
    assert store._state()["active"] is None
    assert activate(store, runtime)["inference_authorized"] is False
    with store.use(runtime) as model:
        assert model.model.endswith(b"version=1\n")
    assert install(store, runtime)["state"] == "verified"
    assert not list((store.root / "staging").iterdir())


@pytest.mark.parametrize("raw", [package()[:-1], b"bad", package() + b"x",
                                 package().replace(b"version=1", b"version=9")],
                         ids=["truncated", "bad", "trailing", "substituted"])
def test_corrupt_or_truncated_cannot_install(store, runtime, raw):
    with pytest.raises(ModelError):
        store.install(V1, runtime, transport=Download(raw), **REQUEST)
    assert not list((store.root / "verified").iterdir())
    assert store._state()["active"] is None


@pytest.mark.parametrize("name", ["../model.bin", "/model.bin", "C:/model.bin", "MODEL.BIN",
                                  "model.bin.", "model.bin ", "model.bin:stream", "a/model.bin",
                                  "model.bin\\child", "con", "./model.bin", "model.bin\x00x"])
def test_hostile_member_names_cannot_extract(name):
    raw = package(entries=[(name, b"x"), ("LICENSE.txt", LICENSE)])
    entry = dataclasses.replace(ModelRegistry.packaged().entry(V1),
                                package_size=len(raw), package_sha256=sha256(raw))
    with pytest.raises(ModelError):
        inspect_package(raw, entry)


@pytest.mark.parametrize("kind", ["compressed", "duplicate", "extra", "symlink", "directory",
                                  "extra-field", "expansive", "license", "hardlink-mode"])
def test_package_structure_bounds_even_with_consistent_outer_hash(kind):
    entries = [("model.bin", b"PROVELUME-SYNTHETIC-MODEL/1\nversion=1\n"),
               ("LICENSE.txt", LICENSE)]
    if kind == "duplicate":
        entries[1] = entries[0]
    if kind == "extra":
        entries.append(("hook.py", b"raise Exception('must never execute')"))
    if kind == "expansive":
        entries[0] = ("model.bin", b"x" * 100000)
    if kind == "license":
        entries[1] = ("LICENSE.txt", b"invalid license")
    raw = package(entries=entries, compression=zipfile.ZIP_DEFLATED
                  if kind == "compressed" else zipfile.ZIP_STORED)
    if kind in ("symlink", "directory", "extra-field", "hardlink-mode"):
        target = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as old, zipfile.ZipFile(target, "w") as new:
            for info in old.infolist():
                data = old.read(info)
                if info.filename == "model.bin":
                    if kind == "extra-field":
                        info.extra = b"\x01\x00\x00\x00"
                    else:
                        info.external_attr = {"symlink": stat.S_IFLNK | 0o600,
                                              "directory": stat.S_IFDIR | 0o700,
                                              "hardlink-mode": stat.S_IFREG | 0o777}[kind] << 16
                new.writestr(info, data)
        raw = target.getvalue()
    entry = dataclasses.replace(ModelRegistry.packaged().entry(V1),
                                package_size=len(raw), package_sha256=sha256(raw))
    with pytest.raises(ModelError):
        inspect_package(raw, entry)


@pytest.mark.parametrize("field,value", [("app_version", "0.12.0"), ("id", "other.runtime"),
                                         ("version", "2"), ("platform", "darwin"),
                                         ("format", "gguf"), ("configuration", b"{}")])
def test_unqualified_runtime_fails_before_acquisition(store, runtime, field, value):
    downloader = Download()
    with pytest.raises(ModelError, match="compatibility"):
        store.install(V1, dataclasses.replace(runtime, **{field: value}),
                      transport=downloader, **REQUEST)
    assert downloader.calls == 0
    assert not store.root.exists()


def test_consent_license_revocation_and_unknown_fail_before_transport(store, runtime):
    download = Download()
    for kwargs in ({"requested": False, "license_accepted": "CC0-1.0"},
                   {"requested": True, "license_accepted": "unknown"}):
        with pytest.raises(ModelError):
            store.install(V1, runtime, transport=download, **kwargs)
    store.allowed_ids = ()
    for identifier in (V1, "untrusted-byom"):
        with pytest.raises(ModelError):
            store.install(identifier, runtime, transport=download, **REQUEST)
    assert download.calls == 0


@pytest.mark.parametrize("outcome", ["FAILED", "UNKNOWN", "yes", True, None])
def test_self_test_non_success_never_activates(store, runtime, outcome):
    install(store, runtime)
    try:
        evidence = store.self_test(V1, runtime, lambda *_: outcome, requested=True)
    except ModelError:
        evidence = None
    with pytest.raises(ModelError):
        store.activate(V1, runtime, evidence, requested=True)
    assert store._state()["active"] is None


def test_self_test_error_expiry_copy_and_restart_invalidate(store, runtime, monkeypatch):
    install(store, runtime)
    evidence = store.self_test(V1, runtime, runner, requested=True)
    with pytest.raises(ModelError, match="stale"):
        store.activate(V1, runtime, dataclasses.replace(evidence), requested=True)
    other = ModelStore(store.root)
    with pytest.raises(ModelError, match="stale"):
        other.activate(V1, runtime, evidence, requested=True)
    now = time.monotonic()
    monkeypatch.setattr(storage.time, "monotonic", lambda: now + 100)
    with pytest.raises(ModelError, match="stale"):
        store.activate(V1, runtime, evidence, requested=True)
    monkeypatch.undo()

    def broken(*_):
        raise RuntimeError("SYNTHETIC_SECRET /private/path")

    with pytest.raises(ModelError, match="self_test") as error:
        store.self_test(V1, runtime, broken, requested=True)
    assert "SYNTHETIC_SECRET" not in str(error.value)
    with pytest.raises(ModelError, match="stale"):
        store.activate(V1, runtime, evidence, requested=True)


def test_byte_and_admission_substitution_invalidates_self_test(store, runtime):
    install(store, runtime)
    evidence = store.self_test(V1, runtime, runner, requested=True)
    store.allowed_ids = (V1,)
    with pytest.raises(ModelError, match="stale"):
        store.activate(V1, runtime, evidence, requested=True)
    entry = store.registry.entry(V1)
    store._path(entry).write_bytes(b"substituted")
    with pytest.raises(ModelError):
        store.verify(V1, runtime)


def test_substitution_during_self_test_and_after_activation(store, runtime):
    install(store, runtime)
    path = store._path(store.registry.entry(V1))

    def substituted(model, *_):
        assert model.model.endswith(b"version=1\n")
        path.write_bytes(package("2"))
        return "PASSED"

    with pytest.raises(ModelError, match="integrity"):
        store.self_test(V1, runtime, substituted, requested=True)
    path.write_bytes(package())
    activate(store, runtime)
    path.write_bytes(package("2"))
    with pytest.raises(ModelError, match="integrity"), store.use(runtime):
        pass


@pytest.mark.parametrize("failure", ["cancel", "timeout", "truncated", "space", "write"])
def test_failed_update_preserves_active_bytes(store, runtime, monkeypatch, failure):
    install(store, runtime)
    activate(store, runtime)
    before = (store.root / "selection.json").read_bytes()
    def cancel():
        return failure == "cancel"
    download = Download(package("2")[:-1] if failure == "truncated" else package("2"))
    if failure == "timeout":
        download.failure = ModelError("timeout")
    if failure == "space":
        monkeypatch.setattr(storage.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    if failure == "write":
        monkeypatch.setattr(storage, "write_local_bytes",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(ModelError):
        store.update(V2, runtime, transport=download, cancel=cancel, **REQUEST)
    assert (store.root / "selection.json").read_bytes() == before
    with store.use(runtime) as model:
        assert model.model.endswith(b"version=1\n")


def test_rollback_requires_current_integrity_compatibility_and_admission(store, runtime):
    install(store, runtime)
    activate(store, runtime)
    install(store, runtime, "2")
    activate(store, runtime, "2")
    store.allowed_ids = (V2,)
    with pytest.raises(ModelError, match="revoked"):
        store.rollback(runtime, runner, requested=True)
    store.allowed_ids = (V1, V2)
    with pytest.raises(ModelError, match="compatibility"):
        store.rollback(dataclasses.replace(runtime, version="2"), runner, requested=True)
    assert store.rollback(runtime, runner, requested=True)["id"] == V1
    with store.use(runtime) as model:
        assert model.entry.id == V1


def test_remove_active_or_leased_refused_then_controlled_removal(store, runtime):
    install(store, runtime)
    activate(store, runtime)
    with pytest.raises(ModelError, match="in_use"):
        store.remove(V1, requested=True)
    with store.use(runtime), pytest.raises(ModelError, match="busy"):
        ModelStore(store.root).remove(V1, requested=True)
    store.deactivate(requested=True)
    store.remove(V1, requested=True)
    assert store._state()["previous"] is None
    with pytest.raises(ModelError):
        store.verify(V1, runtime)


def test_restart_and_interrupted_stage_recovery_is_explicit(store, runtime):
    install(store, runtime)
    activate(store, runtime)
    partial = store.root / "staging" / ("a" * 32 + ".part")
    partial.write_bytes(package()[:50])
    restarted = ModelStore(store.root)
    restarted.status()
    assert partial.exists()
    with pytest.raises(ModelError), restarted.use(runtime):
        pass
    recovered = restarted.recover(requested=True)
    assert recovered["discarded_staging"] == 1
    assert recovered["self_test"] == "UNKNOWN"
    assert restarted.verify(V1, runtime).entry.id == V1
    activate(restarted, runtime)


def test_hardlinks_and_symlinks_rejected(store, runtime, tmp_path):
    source = tmp_path / "source.zip"
    source.write_bytes(package())
    linked = tmp_path / "hard.zip"
    os.link(source, linked)
    with pytest.raises(ModelError):
        store.import_offline(V1, linked, runtime, **REQUEST)
    linked.unlink()
    install(store, runtime)
    installed = store._path(store.registry.entry(V1))
    os.link(installed, linked)
    with pytest.raises(ModelError):
        store.verify(V1, runtime)
    linked.unlink()
    if os.name != "nt":
        source.unlink()
        source.symlink_to(installed)
        other = ModelStore(tmp_path / "other")
        with pytest.raises(ModelError):
            other.import_offline(V1, source, runtime, **REQUEST)


def test_poisoned_storage_parent_and_missing_selection(store, runtime, tmp_path):
    if os.name != "nt":
        target = tmp_path / "real"
        target.mkdir()
        store.root.symlink_to(target, target_is_directory=True)
        with pytest.raises(ModelError, match="unsafe_path"):
            install(store, runtime)
        store.root.unlink()
    install(store, runtime)
    activate(store, runtime)
    store._path(store.registry.entry(V1)).unlink()
    with pytest.raises(ModelError), store.use(runtime):
        pass
    assert store.status()["entries"][0]["installation"] == "missing_or_unverified"


def test_no_implicit_network_or_dispatch(store, runtime, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("implicit network")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert store.status()["network_used"] is False
    assert not store.root.exists()
    with pytest.raises(ModelError, match="consent"):
        store.registry.discover()
    assert store.registry.discover(requested=True) == (V1, V2)
    install(store, runtime)
    activate(store, runtime)
    assert ProvelumeInstance.ai_execution_status()["enabled"] is False


def test_cross_process_lock_release(store, runtime):
    install(store, runtime)
    code = (
        "import sys; from provelume.ai_model_store import ModelStore; "
        "from provelume.ai_models import ModelError\n"
        "try: ModelStore(sys.argv[1]).recover(requested=True)\n"
        "except ModelError as e: print(e.code); sys.exit(2)\n"
    )
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
           if key in os.environ}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "core")
    with store._hold():
        result = subprocess.run([sys.executable, "-c", code, str(store.root)],
                                env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode == 2 and "busy" in result.stdout
    result = subprocess.run([sys.executable, "-c", code, str(store.root)],
                            env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_executable_s04_demonstration(store, runtime, tmp_path):
    source = tmp_path / "trusted-synthetic.zip"
    source.write_bytes(package())
    store.import_offline(V1, source, runtime, **REQUEST)
    assert store.verify(V1, runtime).entry.model_sha256 == store.registry.entry(V1).model_sha256
    activate(store, runtime)
    with pytest.raises(ModelError):
        store.update(V2, runtime, transport=Download(b"hostile"), **REQUEST)
    with store.use(runtime) as valid:
        assert valid.entry.id == V1
    install(store, runtime, "2")
    activate(store, runtime, "2")
    assert store.rollback(runtime, runner, requested=True)["id"] == V1
    with pytest.raises(ModelError, match="in_use"):
        store.remove(V1, requested=True)
    store.deactivate(requested=True)
    store.remove(V1, requested=True)
    store.remove(V2, requested=True)
    assert not list((store.root / "verified").iterdir())
    assert ProvelumeInstance.ai_execution_status()["enabled"] is False


def test_crash_during_staging_never_publishes_and_os_lock_recovers(store, runtime):
    install(store, runtime)
    activate(store, runtime)
    code = '''
import os, sys
from provelume.ai_model_store import ModelStore, default_runtime
class Interrupted:
    def fetch(self, entry, **kwargs):
        yield b"partial"
        os._exit(17)
ModelStore(sys.argv[1]).install("fixture.model-v2", default_runtime(), requested=True,
                               license_accepted="CC0-1.0", transport=Interrupted())
'''
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
           if key in os.environ}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "core")
    result = subprocess.run([sys.executable, "-c", code, str(store.root)],
                            env=env, capture_output=True, timeout=15)
    assert result.returncode == 17, result.stderr
    assert store._state()["active"] == V1
    assert len(list((store.root / "staging").iterdir())) == 1
    restarted = ModelStore(store.root)
    assert restarted.recover(requested=True)["discarded_staging"] == 1
    assert restarted.verify(V1, runtime).entry.id == V1
    with pytest.raises(ModelError):
        restarted.verify(V2, runtime)


def test_writer_temporary_recovery_and_staging_quota(store, runtime):
    install(store, runtime)
    temporary = store.root / "verified" / (".maintenance-" + "b" * 32 + ".tmp")
    temporary.write_bytes(b"uncommitted")
    assert store.recover(requested=True)["discarded_temporary"] == 1
    for index in range(8):
        (store.root / "staging" / (f"{index:032x}" + ".part")).write_bytes(b"partial")
    download = Download(package("2"))
    with pytest.raises(ModelError, match="limit"):
        store.install(V2, runtime, transport=download, **REQUEST)
    assert download.calls == 0


def test_backup_export_and_fresh_restore_have_no_model_bytes_or_authority(tmp_path, runtime):
    from provelume.instance_backup import create_backup, extract_backup
    from provelume.portable_transfer import PortableInstanceTransfer
    from provelume.storage import InstanceStore

    instance = InstanceStore.initialise(tmp_path / "instance", name="Synthetic")
    models = ModelStore.for_instance(instance.paths.root)
    install(models, runtime)
    activate(models, runtime)
    backup = create_backup(instance, destination=tmp_path / "backup.zip")
    exported = PortableInstanceTransfer(instance).export(tmp_path / "export.zip")
    for result in (backup, exported):
        with zipfile.ZipFile(result["archive"]) as archive:
            assert all("ai-models" not in name and not name.endswith(".pkg")
                       for name in archive.namelist())
            for name in archive.namelist():
                assert b"PROVELUME-SYNTHETIC-MODEL" not in archive.read(name)
                assert b"SYNTHETIC_SECRET" not in archive.read(name)
    restored = tmp_path / "restored"
    extract_backup(Path(backup["archive"]), restored)
    restored_models = ModelStore.for_instance(restored)
    assert not restored_models.root.exists()
    assert all(row["installation"] == "missing_or_unverified"
               for row in restored_models.status()["entries"])


def test_service_metadata_and_factory_are_pure(tmp_path, monkeypatch):
    from provelume.storage import InstanceStore

    instance = ProvelumeInstance.__new__(ProvelumeInstance)
    instance.store = InstanceStore(tmp_path / "instance")
    instance.components = ComponentInventory(distribution_versions={})
    before = list(tmp_path.iterdir())
    monkeypatch.setattr(socket, "socket", lambda *_: pytest.fail("implicit socket"))
    assert instance.ai_model_registry()["recommended"] is None
    lifecycle = instance.ai_model_lifecycle()
    assert not lifecycle.root.is_relative_to(instance.root)
    assert list(tmp_path.iterdir()) == before
