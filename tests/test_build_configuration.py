from __future__ import annotations

import tomllib
from pathlib import Path


def test_repository_pins_deterministic_build_inputs() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as handle:
        configuration = tomllib.load(handle)

    assert configuration["build-system"]["requires"] == ["hatchling==1.31.0"]
    assert configuration["build-system"]["build-backend"] == "hatchling.build"
    assert configuration["tool"]["hatch"]["build"]["reproducible"] is True

    release_requirements = {
        line.strip()
        for line in (root / "requirements-release.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "build==1.5.0" in release_requirements
    assert "cyclonedx-bom==7.3.1" in release_requirements
    assert "hatchling==1.31.0" in release_requirements
    assert all("==" in requirement for requirement in release_requirements)


def test_release_workflows_use_the_shared_deterministic_builder() -> None:
    root = Path(__file__).resolve().parents[1]
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")

    for workflow in (ci, release):
        assert "scripts/deterministic_build.py" in workflow
        assert "SOURCE_DATE_EPOCH" in workflow
        assert "build-determinism.json" in workflow
        assert "python -m build --sdist --wheel" not in workflow
