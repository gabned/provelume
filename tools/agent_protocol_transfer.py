"""Predecessor-bound extraction validation. Digests bind bytes, never authority.

The authorized host independently selects the accepted predecessor commit and
manifest digest through the existing exact-head qualification and merge route.
This module is offline: it cannot create repositories, publish or grant rights.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def valid_path(value):
    require(
        isinstance(value, str)
        and value
        and "\\" not in value
        and ":" not in value
        and "\0" not in value
        and not value.startswith("/")
        and all(p not in {"", ".", ".."} for p in value.split("/")),
        "Unsafe path",
    )
    require(not any(ord(c) < 32 or c in '<>"|?*' for c in value), "Nonportable path character")
    require(
        not any(part.casefold() in {".git", ".agent"} for part in value.split("/")),
        "Git metadata and operational caches are not transfer surfaces",
    )
    require(
        not any(
            p.endswith((" ", "."))
            or p.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10)),
            }
            for p in value.split("/")
        ),
        "Nonportable Windows path",
    )
    return value


def validate_manifest(manifest, *, trusted_manifest, accepted_predecessor):
    require(digest(manifest) == trusted_manifest, "Untrusted transfer manifest")
    require(
        re.fullmatch(r"[0-9a-f]{40}", accepted_predecessor or ""),
        "Host-selected accepted predecessor required",
    )
    correction = manifest.get("schema") == "agent-protocol-transfer/v2"
    require(
        manifest.get("schema") in {"agent-protocol-transfer/v1", "agent-protocol-transfer/v2"},
        "Unknown transfer schema",
    )
    require(
        set(manifest)
        == (
            {
                "schema",
                "source_repository",
                "source_commit",
                "destination_repository",
                "destination_id",
                "files",
                "future_paths",
                "dependencies",
                "initialization",
            }
            | ({"bootstrap_history"} if correction else set())
        ),
        "Unknown manifest fields",
    )
    require(
        manifest["initialization"] in {"FULL_ROOT", "LICENSE_ONLY_ROOT"},
        "Unsupported bootstrap route",
    )
    if correction:
        history = manifest["bootstrap_history"]
        require(
            manifest["initialization"] == "LICENSE_ONLY_ROOT"
            and isinstance(history, list)
            and 0 < len(history) <= 16,
            "Bounded accepted bootstrap history required",
        )
        seen = set()
        previous = None
        for row in history:
            require(
                set(row) == {"commit", "parent", "tree", "qualified_by", "manifest_sha256"},
                "Unknown bootstrap history fields",
            )
            for field in ["commit", "parent", "tree", "qualified_by"]:
                require(
                    re.fullmatch(r"[0-9a-f]{40}", row[field]), "Exact history identity required"
                )
            require(
                re.fullmatch(r"[0-9a-f]{64}", row["manifest_sha256"]),
                "Historical qualification manifest required",
            )
            require(
                row["commit"] not in seen
                and row["commit"] != row["parent"]
                and (previous is None or previous == row["parent"]),
                "Broken accepted bootstrap history",
            )
            seen.add(row["commit"])
            previous = row["commit"]
        require(history[0]["parent"] not in seen, "Cyclic bootstrap history")
    require(
        manifest["source_repository"] == "gabned/provelume"
        and manifest["destination_repository"] == "gabned/agent-protocol",
        "Transfer route is not predecessor-registered",
    )
    require(
        type(manifest["destination_id"]) is int and manifest["destination_id"] > 0,
        "Stable destination identity required",
    )
    require(re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"]), "Immutable source required")
    require(
        manifest["source_commit"] == accepted_predecessor,
        "Source commit differs from host-selected accepted predecessor",
    )
    require(isinstance(manifest["files"], list) and manifest["files"], "Exact inventory required")
    paths, folded, source_paths = [], set(), set()
    for row in manifest["files"]:
        require(
            set(row)
            == {
                "source_path",
                "destination_path",
                "source_revision",
                "mode",
                "git_blob",
                "sha256",
                "content_base64",
                "treatment",
            },
            "Unknown inventory fields",
        )
        name = valid_path(row["destination_path"])
        require(name.casefold() not in folded, "Case-insensitive collision")
        require(row["mode"] in {"100644", "100755"}, "Symlink/submodule modes refused")
        require(
            row["treatment"] in {"KEEP", "MOVE", "CONSOLIDATE", "COMPATIBILITY"},
            "Unqualified deletion or treatment",
        )
        require(
            re.fullmatch(r"[0-9a-f]{40}", row["git_blob"])
            and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
            "Invalid content identity",
        )
        if row["source_path"] is None:
            require(
                row["source_revision"] == "AUTHORED" and isinstance(row["content_base64"], str),
                "Authored bootstrap bytes missing",
            )
            verify_bytes(row, base64.b64decode(row["content_base64"], validate=True))
        else:
            valid_path(row["source_path"])
            require(
                row["source_revision"] == "SOURCE" and row["content_base64"] is None,
                "Copy must retain original provenance",
            )
            require(
                (row["source_revision"], row["source_path"]) not in source_paths,
                "One source must not become divergent copies",
            )
            source_paths.add((row["source_revision"], row["source_path"]))
        paths.append(name)
        folded.add(name.casefold())
    require(paths == sorted(paths), "Inventory must be sorted")
    for name in paths:
        require(
            not any(
                str(parent).casefold() in folded
                for parent in PurePosixPath(name).parents
                if str(parent) != "."
            ),
            "File/directory collision",
        )
    for notice in ("LICENSE", "COMMERCIAL-LICENSE.md", "THIRD_PARTY_NOTICES.md"):
        row = next((r for r in manifest["files"] if r["destination_path"] == notice), None)
        require(
            row is not None and row["source_path"] == notice and row["source_revision"] == "SOURCE",
            "Applicable notice must be preserved",
        )
    future = manifest["future_paths"]
    require(isinstance(future, list) and future == sorted(set(future)), "Closed future inventory")
    for name in future:
        valid_path(name)
        require("*" not in name and "?" not in name, "Wildcard registration refused")
    combined = paths + [name for name in future if name not in paths]
    require(
        len({name.casefold() for name in combined}) == len(combined), "Future path case collision"
    )
    for name in combined:
        require(
            not any(
                str(parent).casefold() in {p.casefold() for p in combined}
                for parent in PurePosixPath(name).parents
                if str(parent) != "."
            ),
            "Future file/directory collision",
        )
    require(
        isinstance(manifest["dependencies"], list)
        and manifest["dependencies"] == sorted(set(manifest["dependencies"])),
        "Dependency inventory required",
    )
    return manifest


def verify_bytes(row, data):
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    require(
        blob == row["git_blob"] and hashlib.sha256(data).hexdigest() == row["sha256"],
        "Transferred bytes do not match predecessor inventory",
    )


def verify_source(manifest, observations, *, trusted_manifest, accepted_predecessor):
    validate_manifest(
        manifest, trusted_manifest=trusted_manifest, accepted_predecessor=accepted_predecessor
    )
    require(
        set(observations) == {"repository", "commit", "files"}, "Exact source observations required"
    )
    require(
        observations["repository"] == manifest["source_repository"]
        and observations["commit"] == manifest["source_commit"],
        "Wrong source revision",
    )
    expected = sorted(
        (r for r in manifest["files"] if r["source_revision"] == "SOURCE"),
        key=lambda r: r["source_path"],
    )
    actual = observations["files"]
    require(
        isinstance(actual, list) and len(actual) == len(expected), "Incomplete source inventory"
    )
    for row, observed in zip(expected, actual, strict=True):
        require(set(observed) == {"path", "mode", "content_base64"}, "Unknown source fields")
        require(
            (row["source_path"], row["mode"]) == (observed["path"], observed["mode"]),
            "Source path/mode mismatch",
        )
        verify_bytes(row, base64.b64decode(observed["content_base64"], validate=True))
    return {"result": "SOURCE_BYTES_VERIFIED", "source_commit": manifest["source_commit"]}


def verify_destination(
    manifest,
    observations,
    *,
    trusted_manifest,
    accepted_predecessor,
    accepted_history=None,
    trusted_history=None,
):
    validate_manifest(
        manifest, trusted_manifest=trusted_manifest, accepted_predecessor=accepted_predecessor
    )
    correction = manifest["schema"] == "agent-protocol-transfer/v2"
    if correction:
        # This host-selected input is outside the candidate manifest/observations.
        # Its digest binds retained bytes; the host authenticates the predecessor
        # qualification and original byte receipt before selecting this context.
        require(
            isinstance(accepted_history, list)
            and accepted_history
            and isinstance(trusted_history, str)
            and digest(accepted_history) == trusted_history,
            "Independent authenticated historical qualification is required",
        )
        require(
            len(accepted_history) == len(manifest["bootstrap_history"]),
            "Historical qualification inventory differs",
        )
        for actual, claim in zip(accepted_history, manifest["bootstrap_history"], strict=True):
            require(
                set(actual)
                == {
                    "source_repository",
                    "qualification_commit",
                    "manifest_sha256",
                    "destination_repository",
                    "destination_id",
                    "destination_commit",
                    "destination_parent",
                    "destination_tree",
                },
                "Unknown historical qualification proof fields",
            )
            expected = {
                "source_repository": manifest["source_repository"],
                "qualification_commit": claim["qualified_by"],
                "manifest_sha256": claim["manifest_sha256"],
                "destination_repository": manifest["destination_repository"],
                "destination_id": manifest["destination_id"],
                "destination_commit": claim["commit"],
                "destination_parent": claim["parent"],
                "destination_tree": claim["tree"],
            }
            require(
                actual == expected,
                "Candidate history differs from independently authenticated qualification",
            )
    else:
        require(
            accepted_history is None and trusted_history is None,
            "Historical qualification inputs do not apply to transfer-v1",
        )
    require(
        set(observations)
        == (
            {"repository", "repository_id", "commit", "parents", "files", "seed"}
            | ({"history"} if correction else set())
        ),
        "Exact destination observation required",
    )
    require(
        observations["repository"] == manifest["destination_repository"]
        and observations["repository_id"] == manifest["destination_id"],
        "Wrong destination identity",
    )
    require(re.fullmatch(r"[0-9a-f]{40}", observations["commit"]), "Observed commit required")
    if manifest["initialization"] == "FULL_ROOT":
        require(
            observations["parents"] == [] and observations["seed"] is None,
            "Initial transfer must not import product history",
        )
    else:
        seed = observations["seed"]
        require(
            isinstance(seed, dict) and set(seed) == {"commit", "parents", "files"},
            "Observed license-only root required",
        )
        require(
            re.fullmatch(r"[0-9a-f]{40}", seed["commit"]) and seed["parents"] == [],
            "Bootstrap root must not import history",
        )
        if correction:
            previous = seed["commit"]
            history = observations["history"]
            require(
                isinstance(history, list) and len(history) == len(manifest["bootstrap_history"]),
                "Incomplete observed bootstrap history",
            )
            for actual, expected in zip(history, manifest["bootstrap_history"], strict=True):
                require(
                    actual
                    == {
                        "commit": expected["commit"],
                        "parents": [expected["parent"]],
                        "tree": expected["tree"],
                    }
                    and expected["parent"] == previous,
                    "Observed history differs from predecessor-qualified bootstrap",
                )
                previous = expected["commit"]
            retained = {seed["commit"], *(r["commit"] for r in manifest["bootstrap_history"])}
            require(
                observations["parents"] == [previous] and observations["commit"] not in retained,
                "Correction must append to the exact retained bootstrap",
            )
        else:
            require(
                observations["parents"] == [seed["commit"]],
                "Only the bootstrap root may be a parent",
            )
        require(len(seed["files"]) == 1, "Bootstrap root contains unrelated files")
        license_row = next(r for r in manifest["files"] if r["destination_path"] == "LICENSE")
        actual = seed["files"][0]
        require(
            set(actual) == {"path", "mode", "content_base64"}
            and actual["path"] == "LICENSE"
            and actual["mode"] == license_row["mode"],
            "Unexpected bootstrap license",
        )
        verify_bytes(license_row, base64.b64decode(actual["content_base64"], validate=True))
    rows = observations["files"]
    require(
        isinstance(rows, list) and len(rows) == len(manifest["files"]),
        "Incomplete or extra destination files",
    )
    for expected, actual in zip(manifest["files"], rows, strict=True):
        require(set(actual) == {"path", "mode", "content_base64"}, "Unknown observation fields")
        require(
            (actual["path"], actual["mode"]) == (expected["destination_path"], expected["mode"]),
            "Path or executable mode drift",
        )
        verify_bytes(expected, base64.b64decode(actual["content_base64"], validate=True))
    return {
        "schema": "agent-protocol-transfer-receipt/v2"
        if correction
        else "agent-protocol-transfer-receipt/v1",
        "result": "BYTES_VERIFIED",
        "accepted_predecessor": accepted_predecessor,
        "manifest_sha256": trusted_manifest,
        "destination_commit": observations["commit"],
        "publication_authorized": False,
        "functional_qualification": "REQUIRED",
    }


def materialize(manifest, source_root, destination, *, trusted_manifest, accepted_predecessor):
    """Host-side local byte acquisition; no remote write or authority is granted."""
    validate_manifest(
        manifest, trusted_manifest=trusted_manifest, accepted_predecessor=accepted_predecessor
    )
    source_root, destination = Path(source_root).absolute(), Path(destination).absolute()
    require(
        not any(p.is_symlink() for p in (destination, *destination.parents)),
        "Symlink destination refused",
    )
    require(not destination.is_relative_to(source_root), "Use an independent destination")
    expected = {r["destination_path"] for r in manifest["files"]}
    if destination.exists():
        require(destination.is_dir(), "Existing non-directory preserved")
        require(
            not any(p.is_symlink() for p in destination.rglob("*")),
            "Existing symlink material preserved",
        )
        actual = {
            p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()
        }
        require(actual <= expected, "Unrelated destination material preserved")
    payloads = []
    for row in manifest["files"]:
        if row["source_revision"] == "AUTHORED":
            data = base64.b64decode(row["content_base64"], validate=True)
        else:
            command = [
                "git",
                "--no-replace-objects",
                "-c",
                "protocol.allow=never",
                "-c",
                "safe.directory=" + source_root.as_posix(),
                "-C",
                str(source_root),
            ]
            environment = {**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}
            data = subprocess.check_output(
                [*command, "show", manifest["source_commit"] + ":" + row["source_path"]],
                env=environment,
            )
            tree = subprocess.check_output(
                [*command, "ls-tree", manifest["source_commit"], "--", row["source_path"]],
                env=environment,
            )
            require(tree.decode().split()[0] == row["mode"], "Source executable mode mismatch")
        verify_bytes(row, data)
        target = destination / row["destination_path"]
        require(
            not any(p.is_symlink() for p in (target, *target.parents)), "Symlink target refused"
        )
        if target.exists():
            require(target.is_file() and target.read_bytes() == data, "Existing bytes preserved")
            if os.name != "nt":
                require(
                    bool(target.stat().st_mode & 0o100) == (row["mode"] == "100755"),
                    "Existing mode drift requires explicit reconciliation",
                )
        payloads.append((row, target, data))
    for row, target, data in payloads:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(data)
            if row["mode"] == "100755":
                target.chmod(target.stat().st_mode | 0o100)
    return {
        "result": "MATERIALIZED",
        "files": len(payloads),
        "authority": "NOT_GRANTED",
        "functional_qualification": "REQUIRED",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=["validate-manifest", "verify-source", "verify-destination", "materialize"],
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--trusted-manifest", required=True)
    parser.add_argument("--accepted-predecessor", required=True)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--accepted-history", type=Path)
    parser.add_argument("--trusted-history")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        trust = {
            "trusted_manifest": args.trusted_manifest,
            "accepted_predecessor": args.accepted_predecessor,
        }
        if args.operation == "validate-manifest":
            validate_manifest(manifest, **trust)
            result = {
                "result": "INVENTORY_VALID",
                "authority": "HOST_VERIFIED_PREDECESSOR_REQUIRED",
            }
        elif args.operation == "materialize":
            require(
                args.source_root is not None and args.destination is not None,
                "Source and independent destination required",
            )
            result = materialize(manifest, args.source_root, args.destination, **trust)
        else:
            require(args.observations is not None, "Destination observations required")
            observations = json.loads(args.observations.read_text(encoding="utf-8"))
            if args.operation == "verify-source":
                require(
                    args.accepted_history is None and args.trusted_history is None,
                    "Historical qualification applies only to destination verification",
                )
                result = verify_source(manifest, observations, **trust)
            else:
                result = verify_destination(
                    manifest,
                    observations,
                    **trust,
                    accepted_history=json.loads(args.accepted_history.read_text(encoding="utf-8"))
                    if args.accepted_history
                    else None,
                    trusted_history=args.trusted_history,
                )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(json.dumps({"result": "BLOCKED", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
