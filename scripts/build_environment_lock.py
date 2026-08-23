#!/usr/bin/env python3
"""Generate and validate Provelume's certified OCI build environment lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

SCHEMA_VERSION = 1
ASSURANCE = "pinned-public-oci-builder"
CANONICAL_REGISTRY = "docker.io"
CANONICAL_REPOSITORY = "library/python"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PYTHON_TARGET = re.compile(r"^CPython \d+\.\d+\.\d+$")
SUPPORTED_TARGET = ("linux", "amd64")


class BuildEnvironmentLockError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise BuildEnvironmentLockError(f"cannot hash required file: {path}") from exc
    return digest.hexdigest()


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise BuildEnvironmentLockError(f"{label} must be a non-empty string")
    return value


def generate_payload(
    *,
    tag: str,
    digest: str,
    python_target: str,
    requirements_lock: Path,
    operating_system: str = SUPPORTED_TARGET[0],
    architecture: str = SUPPORTED_TARGET[1],
) -> dict[str, Any]:
    if not TAG.fullmatch(tag):
        raise BuildEnvironmentLockError("builder image tag is invalid")
    if not DIGEST.fullmatch(digest):
        raise BuildEnvironmentLockError("builder image digest must be sha256:<64 hex>")
    if not PYTHON_TARGET.fullmatch(python_target):
        raise BuildEnvironmentLockError("Python target must be 'CPython X.Y.Z'")
    if (operating_system, architecture) != SUPPORTED_TARGET:
        raise BuildEnvironmentLockError("only the certified linux/amd64 target is supported")

    repository = f"{CANONICAL_REGISTRY}/{CANONICAL_REPOSITORY}"
    return {
        "schema_version": SCHEMA_VERSION,
        "assurance": ASSURANCE,
        "target": {
            "operating_system": operating_system,
            "architecture": architecture,
            "python": python_target,
        },
        "image": {
            "registry": CANONICAL_REGISTRY,
            "repository": CANONICAL_REPOSITORY,
            "tag": tag,
            "digest": digest,
            "reference": f"{repository}@{digest}",
            "tagged_reference": f"{repository}:{tag}",
        },
        "inputs": {
            "requirements_lock": requirements_lock.name,
            "requirements_lock_sha256": _sha256_file(requirements_lock),
        },
        "network_policy": {
            "wheelhouse_materialization": "allowed-for-hash-locked-downloads",
            "distribution_build": "disabled",
        },
        "limitations": [
            "The lock certifies one Linux/amd64 OCI builder target.",
            "The host kernel and GitHub Actions service are outside the OCI image digest.",
            "Cross-job equality is not an independent third-party rebuild.",
        ],
    }


def write_lock(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_lock(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BuildEnvironmentLockError("build environment lock is missing or a symlink")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise BuildEnvironmentLockError("build environment lock is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise BuildEnvironmentLockError("build environment lock is not valid JSON") from exc
    except OSError as exc:
        raise BuildEnvironmentLockError("cannot read build environment lock") from exc
    if not isinstance(value, dict):
        raise BuildEnvironmentLockError("build environment lock must be a JSON object")
    return value


def validate_lock(
    payload: dict[str, Any],
    *,
    requirements_lock: Path,
) -> dict[str, str]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise BuildEnvironmentLockError("unsupported build environment lock schema")
    if payload.get("assurance") != ASSURANCE:
        raise BuildEnvironmentLockError("unsupported build environment assurance")

    target = payload.get("target")
    image = payload.get("image")
    inputs = payload.get("inputs")
    policy = payload.get("network_policy")
    limitations = payload.get("limitations")
    if not isinstance(target, dict):
        raise BuildEnvironmentLockError("target must be an object")
    if not isinstance(image, dict):
        raise BuildEnvironmentLockError("image must be an object")
    if not isinstance(inputs, dict):
        raise BuildEnvironmentLockError("inputs must be an object")
    if not isinstance(policy, dict):
        raise BuildEnvironmentLockError("network_policy must be an object")
    if not isinstance(limitations, list) or not limitations:
        raise BuildEnvironmentLockError("limitations must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in limitations):
        raise BuildEnvironmentLockError("every limitation must be a non-empty string")

    operating_system = _require_string(target.get("operating_system"), "target.operating_system")
    architecture = _require_string(target.get("architecture"), "target.architecture")
    python_target = _require_string(target.get("python"), "target.python")
    if (operating_system, architecture) != SUPPORTED_TARGET:
        raise BuildEnvironmentLockError("build target is not the certified linux/amd64 target")
    if not PYTHON_TARGET.fullmatch(python_target):
        raise BuildEnvironmentLockError("target.python is invalid")

    registry = _require_string(image.get("registry"), "image.registry")
    repository = _require_string(image.get("repository"), "image.repository")
    tag = _require_string(image.get("tag"), "image.tag")
    digest = _require_string(image.get("digest"), "image.digest")
    reference = _require_string(image.get("reference"), "image.reference")
    tagged_reference = _require_string(
        image.get("tagged_reference"),
        "image.tagged_reference",
    )
    if registry != CANONICAL_REGISTRY or repository != CANONICAL_REPOSITORY:
        raise BuildEnvironmentLockError("builder must use the canonical public Python image")
    if not TAG.fullmatch(tag):
        raise BuildEnvironmentLockError("image.tag is invalid")
    if not DIGEST.fullmatch(digest):
        raise BuildEnvironmentLockError("image.digest is invalid")
    canonical = f"{registry}/{repository}"
    if reference != f"{canonical}@{digest}":
        raise BuildEnvironmentLockError("image.reference is not the canonical digest reference")
    if ":" in reference.rsplit("/", 1)[-1].split("@", 1)[0]:
        raise BuildEnvironmentLockError("image.reference must not include a floating tag")
    if tagged_reference != f"{canonical}:{tag}":
        raise BuildEnvironmentLockError("image.tagged_reference is inconsistent")

    lock_name = _require_string(
        inputs.get("requirements_lock"),
        "inputs.requirements_lock",
    )
    lock_digest = _require_string(
        inputs.get("requirements_lock_sha256"),
        "inputs.requirements_lock_sha256",
    )
    if lock_name != requirements_lock.name:
        raise BuildEnvironmentLockError("requirements lock filename is inconsistent")
    if not re.fullmatch(r"[0-9a-f]{64}", lock_digest):
        raise BuildEnvironmentLockError("requirements lock digest is invalid")
    if lock_digest != _sha256_file(requirements_lock):
        raise BuildEnvironmentLockError("requirements lock bytes differ from environment lock")

    if policy.get("wheelhouse_materialization") != "allowed-for-hash-locked-downloads":
        raise BuildEnvironmentLockError("wheelhouse network policy is unsupported")
    if policy.get("distribution_build") != "disabled":
        raise BuildEnvironmentLockError("distribution build network policy must be disabled")

    return {
        "status": "valid",
        "reference": reference,
        "tagged_reference": tagged_reference,
        "digest": digest,
        "operating_system": operating_system,
        "architecture": architecture,
        "python": python_target,
        "requirements_lock_sha256": lock_digest,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    subparsers = value.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("--tag", required=True)
    generate.add_argument("--digest", required=True)
    generate.add_argument("--python", required=True)
    generate.add_argument("--requirements-lock", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)

    check = subparsers.add_parser("check")
    check.add_argument("--lock", type=Path, default=Path("build-environment.lock.json"))
    check.add_argument(
        "--requirements-lock",
        type=Path,
        default=Path("requirements-build.lock"),
    )
    check.add_argument("--json", action="store_true")
    check.add_argument("--github-output", type=Path)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "generate":
            payload = generate_payload(
                tag=arguments.tag,
                digest=arguments.digest,
                python_target=arguments.python,
                requirements_lock=arguments.requirements_lock,
            )
            write_lock(arguments.output, payload)
            print(f"wrote build environment lock: {arguments.output}")
            return 0

        result = validate_lock(
            read_lock(arguments.lock),
            requirements_lock=arguments.requirements_lock,
        )
        if arguments.github_output is not None:
            with arguments.github_output.open("a", encoding="utf-8") as handle:
                for key in (
                    "reference",
                    "tagged_reference",
                    "digest",
                    "operating_system",
                    "architecture",
                    "python",
                    "requirements_lock_sha256",
                ):
                    handle.write(f"{key}={result[key]}\n")
        if arguments.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(
                "valid build environment lock: "
                f"{result['reference']} ({result['python']})"
            )
        return 0
    except (BuildEnvironmentLockError, OSError) as exc:
        print(f"build environment lock error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
