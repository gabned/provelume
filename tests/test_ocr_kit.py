from __future__ import annotations

import hashlib
import platform
import stat
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from provelume.ocr_contract import OcrSettings
from provelume.ocr_kit import (
    ENGINE,
    MANIFEST,
    PACKS,
    PDFIUM_DLL,
    PILLOW_CORE,
    PYTHON_DLL,
    TSV_CONFIG,
    WORKER,
    OcrKitError,
    active_kit,
    build_identity,
    import_kit,
    inspect_kit,
    remove_kit,
)
from provelume.publication import canonical_bytes, file_identity
from provelume.service import ProvelumeInstance


@pytest.fixture
def kit(tmp_path):
    build = {
        "source_repository": "gabned/provelume",
        "version": "0.14.0",
        "commit": "a" * 40,
        "official": False,
        "channel": "development",
        "tag": None,
    }
    files = {
        ENGINE: b"synthetic-never-executed-engine",
        TSV_CONFIG: b"tessedit_create_tsv 1\n",
        WORKER: b"synthetic-worker",
        **{p: b"synthetic-pack" for p in PACKS.values()},
        "components.json": b"{}",
        "native-dependencies.json": b"{}",
        "worker/_internal/python312.dll": b"synthetic-runtime",
        PDFIUM_DLL: b"synthetic-pdfium",
        PILLOW_CORE: b"synthetic-decoder",
        "ocr-components.cdx.json": b"{}",
        "licenses/synthetic.txt": b"Synthetic unit-fixture license",
    }
    manifest = {
        "schema_version": 1,
        "source_repository": "gabned/provelume",
        "version": build["version"],
        "commit": build["commit"],
        "platform": "windows",
        "architecture": "x86_64",
        "python": platform.python_version(),
        "entrypoints": {"engine": ENGINE, "worker": WORKER, "packs": PACKS},
        "files": [
            {"path": k, "size_bytes": len(v), "sha256": hashlib.sha256(v).hexdigest()}
            for k, v in files.items()
        ],
        "components": [
            {
                "name": "synthetic",
                "version": "1",
                "license": "MIT",
                "source": "synthetic-unit-fixture",
                "notices": ["licenses/synthetic.txt"],
            }
        ],
        "native_dependencies": [
            {
                "path": name,
                "architecture": "AMD64",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "imports": [],
            }
            for name, raw in files.items()
            if Path(name).suffix in {".exe", ".dll", ".pyd"}
        ],
        "trust": {"synthetic": True},
        "build_identity": build_identity(build),
    }

    def write(*, changes=None, extras=None, raw=None, omit=()):
        value = dict(manifest)
        value.update(changes or {})
        value["files"] = [r for r in value["files"] if r["path"] not in omit]
        value["native_dependencies"] = [
            r for r in value["native_dependencies"] if r["path"] not in omit
        ]
        target = tmp_path / "provelume-0.14.0-ocr-windows-x64.zip"
        with zipfile.ZipFile(target, "w") as archive:
            for name, payload in {
                **{name: data for name, data in files.items() if name not in omit},
                MANIFEST: raw or canonical_bytes(value),
                **(extras or {}),
            }.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = 0o100644 << 16
                archive.writestr(info, payload)
        return target

    archive = write()
    root = tmp_path / "Host OCR"
    return build, files, manifest, write, archive, root


def install(kit):
    build, _, _, _, archive, root = kit
    return import_kit(
        archive,
        root=root,
        build=build,
        development=True,
        expected_sha256=file_identity(archive)["sha256"],
    )


def test_explicit_import_disabled_state_originals_and_preferences_are_preserved(kit, tmp_path):
    build, _, _, _, _, root = kit
    instance = ProvelumeInstance.initialise(tmp_path / "Instance")
    before = {
        p.relative_to(instance.root): p.read_bytes()
        for p in instance.root.rglob("*")
        if p.is_file()
    }
    result = install(kit)
    assert result["status"] == "imported" and result["network_used"] is False
    assert result["ocr_enablement_changed"] is False
    assert instance.ocr_capability()["state"] == "disabled"
    assert before == {
        p.relative_to(instance.root): p.read_bytes()
        for p in instance.root.rglob("*")
        if p.is_file()
    }
    current = active_kit(root=root, build=build)
    assert current.verify()["entrypoints"]["worker"] == WORKER
    assert install(kit)["kit"] == result["kit"]
    assert remove_kit(root=root, build=build)["status"] == "removed"
    assert not current.root.exists() and not (root / "active.json").exists()
    assert instance.ocr_capability()["state"] == "disabled"


@pytest.mark.parametrize(
    "name", [ENGINE, TSV_CONFIG, WORKER, *PACKS.values(), "worker/_internal/python312.dll"]
)
@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_missing_or_changed_component_blocks_and_explicit_reimport_recovers(kit, name, mutation):
    build, _, _, _, _, root = kit
    install(kit)
    current = active_kit(root=root, build=build)
    path = current.root / name
    if mutation == "missing":
        path.unlink()
    else:
        path.write_bytes(b"altered")
    with pytest.raises(OcrKitError) as error:
        active_kit(root=root, build=build)
    expected = (
        "ocr_engine_unavailable"
        if name in {ENGINE, TSV_CONFIG}
        else "ocr_language_pack_missing"
        if name.startswith("tessdata/")
        else "ocr_renderer_unavailable"
    )
    assert error.value.code == expected
    install(kit)
    assert active_kit(root=root, build=build).verify()
    assert len(list(root.glob("quarantine-*"))) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"commit": "b" * 40},
        {"version": "0.99.0"},
        {"platform": "linux"},
        {"architecture": "arm64"},
        {"python": "3.12.0"},
        {"schema_version": True},
        {"entrypoints": {"worker": "python.exe"}},
        {"files": []},
    ],
)
def test_wrong_identity_or_incomplete_kit_does_not_activate(kit, change):
    build, _, _, write, _, root = kit
    archive = write(changes=change)
    with pytest.raises(OcrKitError):
        import_kit(
            archive,
            root=root,
            build=build,
            development=True,
            expected_sha256=file_identity(archive)["sha256"],
        )
    assert not (root / "active.json").exists()


@pytest.mark.parametrize(
    "name",
    [
        "../escaped",
        "/absolute",
        "C:/drive",
        "a\\b",
        "CON.txt",
        "worker/file:stream",
        "worker/file.",
        "WORKER/provelumeocrworker.EXE",
        "unlisted.dll",
    ],
)
def test_unsafe_or_extra_archive_member_is_rejected(kit, name):
    build, _, _, write, _, root = kit
    archive = write(extras={name: b"unexpected"})
    with pytest.raises(OcrKitError):
        import_kit(
            archive,
            root=root,
            build=build,
            development=True,
            expected_sha256=file_identity(archive)["sha256"],
        )
    assert not (root / "active.json").exists()


def test_wrong_archive_digest_and_manifest_tamper_leave_prior_pointer_unchanged(kit):
    build, _, _, write, archive, root = kit
    install(kit)
    before = (root / "active.json").read_bytes()
    with pytest.raises(OcrKitError):
        import_kit(archive, root=root, build=build, development=True, expected_sha256="0" * 64)
    write(extras={ENGINE: b"tampered"})
    with pytest.raises(OcrKitError):
        install(kit)
    assert (root / "active.json").read_bytes() == before
    current = active_kit(root=root, build=build)
    (current.root / MANIFEST).write_bytes(b"{}")
    with pytest.raises(OcrKitError):
        current.verify()


def test_symlink_and_ambiguous_json_are_rejected(kit, tmp_path):
    build, _, _, write, _, root = kit
    archive = write(raw=b'{"schema_version":1,"schema_version":1}')
    with pytest.raises(OcrKitError):
        install(kit)
    archive = write()
    with zipfile.ZipFile(archive, "a") as source:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        source.writestr(info, "../target")
    with pytest.raises(OcrKitError):
        install(kit)
    write()
    target = tmp_path / "redirect"
    target.mkdir()
    try:
        root.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("host cannot create an unprivileged symbolic link")
    with pytest.raises(OcrKitError):
        install(kit)
    assert not list(target.iterdir())


def test_official_build_requires_matching_publication_receipt_and_forbids_dev_digest(kit, tmp_path):
    build, _, _, write, archive, root = kit
    official = {**build, "official": True, "channel": "stable", "tag": "v0.14.0"}
    with pytest.raises(OcrKitError):
        import_kit(
            archive,
            root=root,
            build=official,
            development=True,
            expected_sha256=file_identity(archive)["sha256"],
        )
    # An independently selected operator digest qualifies a candidate offline;
    # this does not create publication evidence or permit the development flag.
    with pytest.raises(OcrKitError):
        import_kit(
            archive, root=root, build=official, expected_sha256=file_identity(archive)["sha256"]
        )
    archive = write(changes={"build_identity": build_identity(official)})
    assert (
        import_kit(
            archive, root=root, build=official, expected_sha256=file_identity(archive)["sha256"]
        )["status"]
        == "imported"
    )
    receipt = {
        "schema_version": 1,
        **{k: official[k] for k in ("source_repository", "version", "commit", "channel", "tag")},
        "published_at": "2026-01-01T00:00:00Z",
        "observed_at": "2026-01-01T00:00:01Z",
        "release_id": 1,
        "release_url": "https://github.com/gabned/provelume/releases/tag/v0.14.0",
        "manifest": {"name": "release-manifest.json", "size_bytes": 1, "sha256": "a" * 64},
        "artifacts": [file_identity(archive)],
    }
    path = tmp_path / "synthetic-receipt.json"
    path.write_bytes(canonical_bytes(receipt))
    assert import_kit(archive, root=root, build=official, receipt_path=path)["status"] == "imported"
    receipt["commit"] = "b" * 40
    path.write_bytes(canonical_bytes(receipt))
    with pytest.raises(OcrKitError):
        import_kit(archive, root=root, build=official, receipt_path=path)


def test_frozen_disabled_does_not_probe_and_missing_kit_never_uses_path(tmp_path, monkeypatch):
    instance = ProvelumeInstance.initialise(tmp_path / "Instance")
    instance.ocr._packaged_components = True
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "host"))
    assert instance.ocr_capability()["state"] == "disabled"
    instance.configure_ocr(replace(OcrSettings(), mode="forced"))
    monkeypatch.setattr("shutil.which", lambda *args: pytest.fail("unverified PATH lookup"))
    capability = instance.ocr_capability()
    assert capability["available"] is False
    assert capability["error"]["code"] == "ocr_renderer_unavailable"


def test_frozen_renderer_dispatch_uses_dedicated_executable_and_material_identity(
    tmp_path, monkeypatch
):
    from provelume.ocr_process import BoundedProcessResult
    from provelume.ocr_renderer import PdfiumPillowRenderer

    commands, checks = [], []

    def run(command, **kwargs):
        commands.append(command)
        return BoundedProcessResult(
            command=tuple(command), returncode=0, stdout=b"{}", stderr=b"", duration_ms=1
        )

    monkeypatch.setattr("provelume.ocr_renderer.run_bounded_process", run)
    executable = tmp_path / "DedicatedWorker.exe"
    renderer = PdfiumPillowRenderer(
        OcrSettings(),
        tmp_path,
        worker_executable=executable,
        material_fingerprint="a" * 64,
        before_execute=lambda: checks.append(True),
    )
    assert renderer._run(["probe"], work_directory=tmp_path, timeout=1) == {}
    assert commands == [[str(executable), "probe"]] and checks == [True]
    assert renderer.adapter_version == "1+" + "a" * 64


@pytest.mark.parametrize(
    "missing",
    [PYTHON_DLL, PDFIUM_DLL, PILLOW_CORE, "ocr-components.cdx.json", "licenses/synthetic.txt"],
)
def test_self_consistent_but_incomplete_kit_never_activates(kit, missing):
    _, _, _, write, _, root = kit
    write(omit=(missing,))
    with pytest.raises(OcrKitError):
        install(kit)
    assert not (root / "active.json").exists()


@pytest.mark.parametrize("matching", [False, True])
def test_runtime_dll_bytes_must_match_the_installed_program(kit, monkeypatch, matching):
    _, files, _, _, _, root = kit
    raw = files[PYTHON_DLL]
    runtime = {
        "name": "python312.dll",
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest() if matching else "0" * 64,
    }
    monkeypatch.setattr("provelume.ocr_kit._runtime_identity", lambda: runtime)
    if matching:
        assert install(kit)["status"] == "imported"
    else:
        with pytest.raises(OcrKitError) as error:
            install(kit)
        assert error.value.code == "ocr_version_incompatible"
        assert not (root / "active.json").exists()


def test_frozen_operator_reports_concurrent_provisioning_as_unavailable(tmp_path, monkeypatch):
    import json

    from provelume.ocr_desktop import run_ocr_command
    from provelume.shell_settings import ShellSettingsBusy

    def busy(*args, **kwargs):
        raise ShellSettingsBusy("another provisioning operation owns the lock")

    monkeypatch.setattr("provelume.ocr_desktop.import_kit", busy)
    output = tmp_path / "result.json"
    assert (
        run_ocr_command(["kit-import", "synthetic.zip", "--expected-sha256", "0" * 64], output) == 2
    )
    assert json.loads(output.read_text())["code"] == "provisioning_busy"


def test_explicit_kit_preview_installs_nothing_and_rejects_changed_archive(kit):
    build, _files, _manifest, _write, archive, root = kit
    before = archive.read_bytes()
    preview = inspect_kit(archive, expected_sha256=hashlib.sha256(before).hexdigest(), build=build)
    assert preview["status"] == "previewed" and not preview["installed"]
    assert not root.exists()
    assert len(preview["components"]) == 6
    assert preview["authority"] == "explicit-sha256"
    archive.write_bytes(before + b"changed-after-preview")
    with pytest.raises(OcrKitError):
        inspect_kit(archive, expected_sha256=preview["kit"]["sha256"], build=build)
    assert not root.exists()
