from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import deterministic_build
from scripts.deterministic_build import DeterministicBuildError


def _project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        """
[build-system]
requires = ["hatchling==1.31.0"]
build-backend = "hatchling.build"

[project]
name = "provelume"
version = "0.1.0"

[tool.hatch.build]
reproducible = true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "core").mkdir()
    (root / "core" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    return root


def _artifacts(root: Path, suffix: bytes = b"") -> dict[str, Path]:
    root.mkdir(parents=True)
    wheel = root / "provelume-0.1.0-py3-none-any.whl"
    sdist = root / "provelume-0.1.0.tar.gz"
    wheel.write_bytes(b"wheel" + suffix)
    sdist.write_bytes(b"sdist" + suffix)
    return {"wheel": wheel, "sdist": sdist}


def test_source_date_epoch_fails_closed() -> None:
    assert deterministic_build.source_date_epoch("0") == 0
    with pytest.raises(DeterministicBuildError, match="required"):
        deterministic_build.source_date_epoch(None)
    with pytest.raises(DeterministicBuildError, match="integer"):
        deterministic_build.source_date_epoch("not-a-number")
    with pytest.raises(DeterministicBuildError, match="negative"):
        deterministic_build.source_date_epoch("-1")


def test_source_fingerprint_ignores_generated_outputs(tmp_path: Path) -> None:
    source = _project(tmp_path)
    before = deterministic_build.source_fingerprint(source)
    (source / "dist").mkdir()
    (source / "dist" / "generated.whl").write_bytes(b"generated")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "module.pyc").write_bytes(b"cache")
    assert deterministic_build.source_fingerprint(source) == before
    (source / "core" / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert deterministic_build.source_fingerprint(source) != before


def test_source_tree_rejects_symlinks(tmp_path: Path) -> None:
    source = _project(tmp_path / "source")
    link = source / "core" / "linked.py"
    try:
        os.symlink(source / "core" / "module.py", link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available on this platform")

    with pytest.raises(DeterministicBuildError, match="symlinks"):
        deterministic_build.validate_source_tree(source)
    with pytest.raises(DeterministicBuildError, match="symlinks"):
        deterministic_build.source_fingerprint(source)


def test_compare_builds_detects_byte_difference(tmp_path: Path) -> None:
    first = _artifacts(tmp_path / "first")
    second = _artifacts(tmp_path / "second")
    records = deterministic_build.compare_builds(first, second)
    assert all(record["byte_identical"] for record in records)

    second["wheel"].write_bytes(b"different")
    records = deterministic_build.compare_builds(first, second)
    assert next(record for record in records if record["kind"] == "wheel")[
        "byte_identical"
    ] is False


def test_run_copies_verified_artifacts_and_writes_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _project(tmp_path / "source")
    output = tmp_path / "dist"
    evidence = tmp_path / "evidence.json"
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1787443200")
    monkeypatch.setattr(
        deterministic_build.importlib.metadata,
        "version",
        lambda name: {"build": "1.5.0", "hatchling": "1.31.0"}[name],
    )

    def fake_build_once(_source: Path, workspace: Path, _epoch: int) -> dict[str, Path]:
        return _artifacts(workspace / "dist")

    monkeypatch.setattr(deterministic_build, "build_once", fake_build_once)
    payload = deterministic_build.run(
        source=source,
        output_dir=output,
        evidence=evidence,
        commit="a" * 40,
    )

    assert payload["full_release_reproducibility_claimed"] is False
    assert payload["source_repository"] == "gabned/provelume"
    assert all(record["byte_identical"] for record in payload["artifacts"])
    assert {path.name for path in output.iterdir()} == {
        "provelume-0.1.0-py3-none-any.whl",
        "provelume-0.1.0.tar.gz",
    }
    assert json.loads(evidence.read_text(encoding="utf-8"))["source_commit"] == "a" * 40


def test_run_preserves_mismatch_evidence_and_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _project(tmp_path / "source")
    evidence = tmp_path / "evidence.json"
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1787443200")
    monkeypatch.setattr(
        deterministic_build.importlib.metadata,
        "version",
        lambda name: {"build": "1.5.0", "hatchling": "1.31.0"}[name],
    )
    calls = 0

    def fake_build_once(_source: Path, workspace: Path, _epoch: int) -> dict[str, Path]:
        nonlocal calls
        calls += 1
        return _artifacts(workspace / "dist", suffix=str(calls).encode())

    monkeypatch.setattr(deterministic_build, "build_once", fake_build_once)
    with pytest.raises(DeterministicBuildError, match="differ"):
        deterministic_build.run(
            source=source,
            output_dir=tmp_path / "dist",
            evidence=evidence,
            commit=None,
        )
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert any(not record["byte_identical"] for record in payload["artifacts"])
