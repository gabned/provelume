#!/usr/bin/env python3
"""Native dependency verification and routing; credentials belong to the enrolled host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ".github/agent-protocol/pin.json"
VENDOR = ROOT / "tools/agent_protocol_core"
REPOSITORY = "gabned/provelume"
REPOSITORY_ID = 1343746770


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlink dependency refused")
    return path.read_bytes()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def verify():
    """Byte proof only: an accepted host independently authenticates source/policy."""
    pin = json.loads(read(ROOT / PIN_PATH))
    require(pin["schema"] == "agent-protocol-consumer-pin/v2", "Unknown consumer pin")
    require(
        (pin["consumer"], pin["consumer_id"]) == (REPOSITORY, REPOSITORY_ID),
        "Consumer identity changed",
    )
    require(
        pin["operational_revision"] == pin["work_revision"] == pin["source_manifest"]["revision"],
        "Work/operational source split",
    )
    manifest = pin["source_manifest"]
    require(
        (manifest["repository"], manifest["repository_id"])
        == ("gabned/agent-protocol", 1393711644),
        "Canonical repository changed",
    )
    require(digest(manifest) == pin["manifest_digest"], "Source inventory changed")
    expected = {}
    for row in manifest["files"]:
        name = row["path"]
        require(
            isinstance(name, str)
            and "\\" not in name
            and ":" not in name
            and not name.startswith("/")
            and all(p not in {"", ".", ".."} for p in name.split("/")),
            "Unsafe source path",
        )
        require(
            name.casefold() not in expected and row["mode"] in {"100644", "100755"},
            "Duplicate path or unsafe mode",
        )
        expected[name.casefold()] = name
        file = VENDOR / name
        data = read(file)
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(
            (hashlib.sha256(data).hexdigest(), blob) == (row["sha256"], row["blob"]),
            "Canonical bytes changed: " + name,
        )
        if os.name != "nt":
            require(
                bool(file.stat().st_mode & 0o111) == (row["mode"] == "100755"),
                "Canonical mode changed: " + name,
            )
    actual = {
        p.relative_to(VENDOR).as_posix()
        for p in VENDOR.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    require(actual == set(expected.values()), "Unmanaged or missing canonical files")
    # Import only after checking every immutable distribution byte.
    sys.path.insert(0, str(VENDOR / "src"))
    from agent_protocol.source import validate_inventory

    validate_inventory(manifest, pin["manifest_digest"])
    return pin


def documents(pin, phase, host, workstream):
    from agent_protocol.documents import select

    core_manifest = json.loads(read(VENDOR / ".github/agent-protocol/documents.json"))
    core = select(
        VENDOR,
        core_manifest,
        accepted_digest=pin["documents_digest"],
        phase=phase,
        host=host,
        workstream=workstream,
    )
    local_manifest = json.loads(read(ROOT / ".github/agent-protocol/documents.json"))
    local = select(
        ROOT,
        local_manifest,
        accepted_digest=digest(local_manifest),
        phase=phase,
        host=host,
        workstream=workstream,
    )
    return {
        "source_revision": pin["operational_revision"],
        "core": core,
        "local": local,
        "model_text_bytes": core["model_text_bytes"] + local["model_text_bytes"],
        "authority": "ACCEPTED_CONSUMER_BASE_REQUIRED",
        "tokens": "UNKNOWN",
        "cost": "UNKNOWN",
    }


def bind_product_host(journal, *, collect_native, native_authority, merge_native,
                      collect_recovery_native):
    """Bind the repository's accepted PRODUCT host to the canonical journal engine.

    These are authenticated host capabilities, never candidate JSON, executable
    paths or PR-body fields. Native qualification/release/consent stays local.
    """
    pin = verify()
    from agent_protocol.host import ProtocolHost

    identity = journal.read()["identity"]
    require((identity["repository"], identity["repository_id"], identity["workstream_class"])
            == (REPOSITORY, REPOSITORY_ID, "PRODUCT"), "Native PRODUCT identity changed")
    require(all(callable(value) for value in
                (collect_native, native_authority, merge_native, collect_recovery_native)),
            "Complete independently accepted native host capabilities required")

    def authority(state):
        current = native_authority(state)
        require(current["identity"] == identity and current["pin"] == pin["operational_revision"],
                "Native authority/source differs from accepted consumer pin")
        require(current["policy"]["selected"] == "REPOSITORY_POLICY"
                and current["policy"]["contract"]["routing"] == "PRODUCT/v2",
                "Native PRODUCT policy cannot downgrade to Protocol-only checks")
        require({"CI", "NATIVE", "REVIEWS", "EFFECTS", "ANCESTRY", "SOURCE", "AUTHORIZATION"}
                <= set(current["policy"]["required_gates"]),
                "Complete native PRODUCT gate inventory required")
        return current

    # Fail before exposing a write interface if the accepted route is incomplete.
    authority(journal.read())
    return ProtocolHost(journal, collect=collect_native, authority=authority,
                        merge=merge_native, collect_recovery=collect_recovery_native)


def workspace(action):
    """Native Provelume profile, invoked only inside the isolated project image."""
    require(REPOSITORY == "gabned/provelume" and os.name == "posix", "Native profile differs")
    wheels = Path("/opt/native-wheels")
    inventory = json.loads(read(wheels / "inventory.json"))
    editable = json.loads(read(wheels / "editable-requirements.json"))
    require(isinstance(editable, list) and editable and all(
        isinstance(item, str) and item and not any(c in item for c in "/\\:@\n\r")
        and not item.startswith("-") for item in editable), "Invalid native backend requirements")
    require(inventory and set(inventory) == {p.name for p in wheels.glob("*.whl")},
            "Complete native dependency inventory required")
    for name, expected in inventory.items():
        require(Path(name).name == name and name.endswith(".whl"), "Invalid native wheel")
        require(hashlib.sha256(read(wheels / name)).hexdigest() == expected,
                "Native dependency cache changed")
    temporary = ROOT / ".agent"
    require(not temporary.is_symlink(), "Native workspace cache symlink refused")
    temporary.mkdir(exist_ok=True)
    environment = temporary / "lab-venv"
    marker = temporary / "lab-environment.json"
    binding = {"repository": REPOSITORY, "runtime": sys.version,
               "pyproject_sha256": hashlib.sha256(read(ROOT / "pyproject.toml")).hexdigest(),
               "wheels_sha256": digest(inventory), "editable_requirements_sha256": digest(editable)}
    if marker.exists():
        require(json.loads(read(marker)) == binding,
                "Existing native environment differs; preserve it")
    else:
        require(not environment.exists(), "Unmanaged native environment preserved")
        with marker.open("x", encoding="utf-8") as stream:
            json.dump(binding, stream, sort_keys=True)
    require(not environment.is_symlink(), "Native environment symlink refused")
    if not environment.exists():
        require(action == "prepare", "Prepare the native environment before execution")
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = environment / "bin/python"
    require(python.is_file(), "Interrupted native preparation requires reconciliation")
    if action == "prepare":
        subprocess.run([str(python), "-m", "pip", "install", "--no-index",
            "--find-links", str(wheels), "--require-hashes", "-r",
            str(ROOT / "build-lock/ubuntu-py312-x86_64.requirements.txt")], cwd=ROOT, check=True)
        subprocess.run([str(python), "-m", "pip", "install", "--no-index",
                        "--find-links", str(wheels), *editable], cwd=ROOT, check=True)
        subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--no-build-isolation",
            "--find-links", str(wheels), "-e", ".[dev]"], cwd=ROOT, check=True)
        return {"native_environment": "PREPARED", "gates": "NOT_REPLACED"}
    if action == "check":
        subprocess.run([str(python), "-m", "ruff", "check",
                        "--cache-dir", str(temporary / "ruff-cache"),
                        "core", "tests", "scripts", "tools", "packaging"],
                       cwd=ROOT, check=True)
        subprocess.run([str(python), "-m", "pytest", "-q"], cwd=ROOT, check=True)
        subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
        return {"native_checks": "PASS", "remote_qualification": "REQUIRED"}
    instance = temporary / "lab-synthetic-instance"
    require(not instance.is_symlink(), "Synthetic instance symlink refused")
    if not instance.exists():
        subprocess.run([str(python), "-m", "provelume", "init", str(instance),
                        "--name", "Synthetic development instance"], cwd=ROOT, check=True)
    # Preserve the product's loopback-only serving policy. No public/listen-all
    # override or production endpoint is introduced for convenience.
    subprocess.run([str(python), "-m", "provelume", "serve", str(instance),
                    "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT, check=True)
    return {"native_runtime": "STOPPED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    docs = sub.add_parser("documents")
    docs.add_argument("--phase", required=True)
    docs.add_argument("--host", required=True)
    docs.add_argument("--workstream", required=True)
    engine = sub.add_parser("engine")
    engine.add_argument("arguments", nargs=argparse.REMAINDER)
    collector = sub.add_parser("collect")
    collector.add_argument("arguments", nargs=argparse.REMAINDER)
    native_workspace = sub.add_parser("workspace")
    native_workspace.add_argument("action", choices=["prepare", "check", "start"])
    args = parser.parse_args(argv)
    try:
        pin = verify()
        if args.command == "verify":
            result = {
                "result": "BYTES_VERIFIED",
                "repository": REPOSITORY,
                "revision": pin["operational_revision"],
                "files": len(pin["source_manifest"]["files"]),
                "authority": "REQUIRES_ACCEPTED_BASE_AND_AUTHENTICATED_RELEASE",
            }
        elif args.command == "documents":
            result = documents(pin, args.phase, args.host, args.workstream)
        elif args.command == "workspace":
            result = workspace(args.action)
        elif args.command == "engine":
            from agent_protocol.cli import main as core_main

            return core_main(args.arguments)
        else:
            return subprocess.run(
                ["node", str(VENDOR / "tools/collect.mjs"), *args.arguments], check=False
            ).returncode
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(json.dumps({"result": "REFUSED", "reason": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
