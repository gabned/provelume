"""Transferred build inputs cannot silently omit, substitute or license native code."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts import build_ai_runtime_input, stage_ai_runtime_inputs


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    # Small public bytes exercise the real offline ZIP boundary, with a test-owned
    # lock. No fake input can be selected by a command or a product endpoint.
    lock = {"platforms": {}}
    paths = {}
    source = tmp_path / "source"
    notices = source / "core/provelume/runtime_notices"
    notices.mkdir(parents=True)
    original = Path(__file__).resolve().parents[1]
    for name in ("llama-LICENSE.txt", "LLVM-OpenMP-LICENSE.txt"):
        raw = (original / "core/provelume/runtime_notices" / name).read_bytes()
        (notices / name).write_bytes(raw)
    for platform, name in (("windows", "libomp.dll"), ("linux", "libllama.so.0")):
        directory = tmp_path / platform
        directory.mkdir()
        raw = ("public " + platform).encode()
        (directory / name).write_bytes(raw)
        lock["platforms"][platform] = {name: {
            "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}
        paths[platform] = tmp_path / (platform + ".zip")
    monkeypatch.setattr(build_ai_runtime_input, "runtime_lock", lambda: lock)
    monkeypatch.setattr(stage_ai_runtime_inputs, "runtime_lock", lambda: lock)
    for platform, path in paths.items():
        build_ai_runtime_input.build(tmp_path / platform, platform, path)
    return source, paths


def test_transferred_pair_composes_both_optional_trees(inputs):
    source, paths = inputs
    result = stage_ai_runtime_inputs.stage(source, paths)
    assert result["model_weights_included"] is False
    assert result["native_bytes"] == len(b"public windowspublic linux")
    root = source / "core/provelume/native-ai"
    assert (root / "windows/libomp.dll").read_bytes() == b"public windows"
    assert (root / "linux/libllama.so.0").read_bytes() == b"public linux"


@pytest.mark.parametrize("corruption", ["member", "bytes", "notice", "license", "version"])
def test_invalid_second_platform_publishes_nothing(inputs, corruption):
    source, paths = inputs
    path = paths["windows"]  # Sorted last, after the other input has been validated.
    with zipfile.ZipFile(path) as archive:
        rows = [(info, archive.read(info)) for info in archive.infolist()]
    path.unlink()
    with zipfile.ZipFile(path, "x") as archive:
        for info, raw in rows:
            if info.filename.startswith("native/"):
                if corruption == "member":
                    continue
                if corruption == "bytes":
                    raw += b"changed"
            if info.filename.startswith("notices/") and corruption == "notice":
                raw = b"substituted"
            if info.filename.endswith(".json") and corruption in {"license", "version"}:
                value = json.loads(raw)
                value["components"][0]["licenses" if corruption == "license" else "version"] = []
                raw = json.dumps(value).encode()
            archive.writestr(info, raw)
    with pytest.raises(ValueError):
        stage_ai_runtime_inputs.stage(source, paths)
    assert not (source / "core/provelume/native-ai").exists()


def test_one_platform_is_not_a_portable_distribution(inputs):
    source, paths = inputs
    with pytest.raises(ValueError, match="both"):
        stage_ai_runtime_inputs.stage(source, {"linux": paths["linux"]})
    assert not (source / "core/provelume/native-ai").exists()
