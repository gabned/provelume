from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


def _load_module() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "build_environment_lock.py"
    spec = importlib.util.spec_from_file_location("provelume_build_environment_lock", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _requirements_lock(tmp_path: Path) -> Path:
    path = tmp_path / "requirements-build.lock"
    path.write_text(
        "# synthetic public build lock\n"
        "build==1.5.0 --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    return path


def _payload(lock: ModuleType, requirements: Path) -> dict[str, object]:
    return lock.generate_payload(
        tag="3.12.14-slim-bookworm",
        digest="sha256:" + "b" * 64,
        python_target="CPython 3.12.14",
        requirements_lock=requirements,
    )


def test_generate_and_validate_pinned_reference(tmp_path: Path) -> None:
    lock = _load_module()
    requirements = _requirements_lock(tmp_path)
    payload = _payload(lock, requirements)

    assert payload["image"]["reference"] == (
        "docker.io/library/python@sha256:" + "b" * 64
    )
    assert payload["image"]["tagged_reference"] == (
        "docker.io/library/python:3.12.14-slim-bookworm"
    )
    assert payload["inputs"]["requirements_lock_sha256"] == hashlib.sha256(
        requirements.read_bytes()
    ).hexdigest()

    result = lock.validate_lock(payload, requirements_lock=requirements)
    assert result["status"] == "valid"
    assert result["architecture"] == "amd64"
    assert result["python"] == "CPython 3.12.14"


def test_rejects_floating_or_inconsistent_image_reference(tmp_path: Path) -> None:
    lock = _load_module()
    requirements = _requirements_lock(tmp_path)
    payload = _payload(lock, requirements)
    payload["image"]["reference"] = "docker.io/library/python:3.12.14-slim-bookworm"

    with pytest.raises(lock.BuildEnvironmentLockError, match="digest reference"):
        lock.validate_lock(payload, requirements_lock=requirements)

    payload = _payload(lock, requirements)
    payload["image"]["tagged_reference"] = "docker.io/library/python:latest"
    with pytest.raises(lock.BuildEnvironmentLockError, match="tagged_reference"):
        lock.validate_lock(payload, requirements_lock=requirements)


def test_rejects_noncanonical_registry_or_repository(tmp_path: Path) -> None:
    lock = _load_module()
    requirements = _requirements_lock(tmp_path)
    payload = _payload(lock, requirements)
    payload["image"]["registry"] = "private.example.invalid"

    with pytest.raises(lock.BuildEnvironmentLockError, match="canonical public Python"):
        lock.validate_lock(payload, requirements_lock=requirements)


def test_rejects_target_drift(tmp_path: Path) -> None:
    lock = _load_module()
    requirements = _requirements_lock(tmp_path)
    payload = _payload(lock, requirements)
    payload["target"]["architecture"] = "arm64"

    with pytest.raises(lock.BuildEnvironmentLockError, match="certified linux/amd64"):
        lock.validate_lock(payload, requirements_lock=requirements)


def test_rejects_changed_requirements_lock(tmp_path: Path) -> None:
    lock = _load_module()
    requirements = _requirements_lock(tmp_path)
    payload = _payload(lock, requirements)
    requirements.write_text("changed\n", encoding="utf-8")

    with pytest.raises(lock.BuildEnvironmentLockError, match="bytes differ"):
        lock.validate_lock(payload, requirements_lock=requirements)


def test_lock_file_and_github_outputs_are_machine_readable(tmp_path: Path) -> None:
    lock = _load_module()
    requirements = _requirements_lock(tmp_path)
    path = tmp_path / "build-environment.lock.json"
    output = tmp_path / "github-output.txt"
    lock.write_lock(path, _payload(lock, requirements))

    assert (
        lock.main(
            [
                "check",
                "--lock",
                str(path),
                "--requirements-lock",
                str(requirements),
                "--json",
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == 1
    values = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert values["reference"].startswith("docker.io/library/python@sha256:")
    assert values["operating_system"] == "linux"


def test_generate_rejects_invalid_digest_or_python_target(tmp_path: Path) -> None:
    lock = _load_module()
    requirements = _requirements_lock(tmp_path)
    with pytest.raises(lock.BuildEnvironmentLockError, match="digest"):
        lock.generate_payload(
            tag="3.12.14-slim-bookworm",
            digest="sha256:not-a-digest",
            python_target="CPython 3.12.14",
            requirements_lock=requirements,
        )
    with pytest.raises(lock.BuildEnvironmentLockError, match="Python target"):
        lock.generate_payload(
            tag="3.12.14-slim-bookworm",
            digest="sha256:" + "b" * 64,
            python_target="Python 3.12",
            requirements_lock=requirements,
        )
