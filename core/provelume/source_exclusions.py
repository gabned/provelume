"""Versioned, portable filesystem selection rules and bounded read-only traversal."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import stat
import time
import unicodedata
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .extractors import extractor_for
from .paths import UnsafePathError, normalise_locator

MAX_RULES = 32
MAX_PATTERN_CHARS = 256
MAX_SCAN_ENTRIES = 10000
MAX_SCAN_DEPTH = 32
MAX_PREVIEW_ROWS = 200
SCAN_SECONDS = 10.0
KINDS = ("subfolder", "file", "extension", "type", "glob")
TYPE_EXTENSIONS = {
    "text": (".txt", ".md", ".markdown", ".csv"),
    "document": (".pdf", ".docx", ".xlsx"),
    "image": (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif"),
    "audio": (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".opus"),
    "video": (".mp4", ".mov", ".mkv", ".avi", ".webm"),
    "email": (".eml",),
    "archive": (".zip",),
}


class ExclusionError(ValueError):
    code = "invalid_rules"


class ExclusionLimitError(ExclusionError):
    code = "preview_limit"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_pattern(kind: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ExclusionError("An exclusion pattern must be text.")
    pattern = unicodedata.normalize("NFC", value.strip().replace("\\", "/"))
    if not pattern or len(pattern) > MAX_PATTERN_CHARS or any(ord(c) < 32 for c in pattern):
        raise ExclusionError(
            "The exclusion pattern is empty, too long or contains control characters."
        )
    if kind == "extension":
        pattern = pattern.casefold()
        if not pattern.startswith("."):
            pattern = "." + pattern
        if re.fullmatch(r"\.[a-z0-9][a-z0-9_-]{0,31}", pattern) is None:
            raise ExclusionError("Use one extension, such as .pdf, without wildcards.")
        return pattern
    if kind == "type":
        pattern = pattern.casefold()
        if pattern not in TYPE_EXTENSIONS:
            raise ExclusionError("Select a supported file type.")
        return pattern
    if kind not in KINDS:
        raise ExclusionError("Unsupported exclusion rule kind.")
    if kind == "subfolder":
        pattern = pattern.rstrip("/")
    parts = pattern.split("/")
    if (
        not pattern
        or pattern.startswith("/")
        or ":" in pattern
        or any(part in {"", ".", ".."} for part in parts)
        or len(parts) > 16
        or (kind == "glob" and any(c in pattern for c in "[]{}!"))
    ):
        raise ExclusionError(
            "Use a bounded Source-relative pattern without traversal or character classes."
        )
    if kind != "glob" and any(c in pattern for c in "*?"):
        raise ExclusionError("Wildcards require a glob rule.")
    if kind == "glob" and (
        sum(part == "**" for part in parts) > 2
        or any("**" in part and part != "**" for part in parts)
        or pattern.count("*") + pattern.count("?") > 12
    ):
        raise ExclusionError("The glob exceeds its bounded wildcard complexity.")
    return pattern


def rule(
    kind: str,
    pattern: str,
    *,
    action: str = "exclude",
    enabled: bool = True,
    rule_id: str | None = None,
) -> dict[str, Any]:
    selected = normalize_pattern(kind, pattern)
    return {
        "id": rule_id or "rule_" + fingerprint([kind, selected, action])[:16],
        "kind": kind,
        "pattern": selected,
        "action": action,
        "enabled": enabled,
    }


def default_policy() -> dict[str, Any]:
    return normalize_policy(
        {
            "schema_version": 1,
            "revision": 1,
            "enabled": True,
            "rules": [rule("glob", p) for p in (".git/**", ".github/**")]
            + [rule("file", p) for p in (".gitignore", ".gitattributes", ".gitmodules")],
        }
    )


def normalize_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "revision",
        "enabled",
        "rules",
    }:
        raise ExclusionError("Exclusion policy fields are incomplete or unsupported.")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["revision"]) is not int
        or not 1 <= value["revision"] < 2**31
        or type(value["enabled"]) is not bool
        or not isinstance(value["rules"], list)
        or len(value["rules"]) > MAX_RULES
    ):
        raise ExclusionError("Invalid exclusion version, state or rule count.")
    rules, identifiers, criteria = [], set(), set()
    for raw in value["rules"]:
        if not isinstance(raw, Mapping) or set(raw) != {
            "id",
            "kind",
            "pattern",
            "action",
            "enabled",
        }:
            raise ExclusionError("Exclusion rule fields are incomplete or unsupported.")
        if (
            not isinstance(raw["id"], str)
            or re.fullmatch(r"rule_[0-9a-f]{16}", raw["id"]) is None
            or raw["kind"] not in KINDS
            or not isinstance(raw["action"], str)
            or raw["action"] not in {"exclude", "include"}
            or type(raw["enabled"]) is not bool
        ):
            raise ExclusionError("Invalid exclusion rule identity, kind or state.")
        item = rule(
            raw["kind"],
            raw["pattern"],
            action=raw["action"],
            enabled=raw["enabled"],
            rule_id=raw["id"],
        )
        criterion = (item["kind"], item["pattern"], item["action"])
        if item["id"] in identifiers or criterion in criteria:
            raise ExclusionError("Duplicate exclusion rule.")
        identifiers.add(item["id"])
        criteria.add(criterion)
        rules.append(item)
    return {
        "schema_version": 1,
        "revision": value["revision"],
        "enabled": value["enabled"],
        "rules": sorted(rules, key=lambda item: item["id"]),
    }


def policy_for_source(store: Any, source_id: str) -> dict[str, Any] | None:
    sources = store.read_config().get("sources") or {}
    item = sources.get(source_id) if isinstance(sources, Mapping) else None
    if not isinstance(item, Mapping) or item.get("folder") is None:
        return None
    return normalize_policy(item["exclusions"]) if "exclusions" in item else default_policy()


def _glob_matches(pattern: str, locator: str) -> bool:
    patterns, components = pattern.split("/"), locator.split("/")

    @lru_cache(maxsize=2048)
    def match(i: int, j: int) -> bool:
        if i == len(patterns):
            return j == len(components)
        if patterns[i] == "**":
            return match(i + 1, j) or (j < len(components) and match(i, j + 1))
        return (
            j < len(components)
            and fnmatch.fnmatchcase(components[j], patterns[i])
            and match(i + 1, j + 1)
        )

    return match(0, 0)


def decision(
    policy: Mapping[str, Any] | None, locator: str, *, directory: bool = False
) -> dict[str, Any]:
    locator = unicodedata.normalize("NFC", normalise_locator(locator))
    if len(locator) > 4096 or len(locator.split("/")) > MAX_SCAN_DEPTH + 1:
        raise ExclusionLimitError("Source locator exceeds the traversal bound.")
    if policy is None or not policy["enabled"]:
        return {"included": True, "reason": "rules_disabled", "rule_ids": []}
    excluded, included = [], []
    suffix = Path(locator).suffix.casefold()
    for item in policy["rules"]:
        if not item["enabled"]:
            continue
        kind, pattern = item["kind"], item["pattern"]
        matched = (
            (directory and locator == pattern or locator.startswith(pattern + "/"))
            if kind == "subfolder"
            else locator == pattern and not directory
            if kind == "file"
            else suffix == pattern and not directory
            if kind == "extension"
            else suffix in TYPE_EXTENSIONS[pattern] and not directory
            if kind == "type"
            else _glob_matches(pattern, locator) and (not directory or pattern.endswith("/**"))
        )
        if matched:
            (included if item["action"] == "include" else excluded).append(item["id"])
    return {
        "included": bool(included) or not excluded,
        "reason": "explicit_override" if included else "excluded" if excluded else "included",
        "rule_ids": included or excluded,
    }


def _can_override_subtree(policy: Mapping[str, Any] | None, directory: str) -> bool:
    """Retain only subtrees that may contain an enabled explicit include match."""
    if policy is None or not policy["enabled"]:
        return False
    for item in policy["rules"]:
        if not item["enabled"] or item["action"] != "include":
            continue
        kind, pattern = item["kind"], item["pattern"]
        if kind in {"extension", "type"}:
            return True
        if kind == "file":
            if pattern.startswith(directory + "/"):
                return True
            continue
        if kind == "glob":
            # A literal prefix bounds the possible descendants of a glob.
            # Wildcards in the first component conservatively retain the tree.
            prefix = []
            for part in pattern.split("/"):
                if "*" in part or "?" in part:
                    break
                prefix.append(part)
            pattern = "/".join(prefix)
        if (
            not pattern
            or pattern == directory
            or pattern.startswith(directory + "/")
            or directory.startswith(pattern + "/")
        ):
            return True
    return False


def scan(source: Path, max_files: int, policy: Mapping[str, Any] | None) -> dict[str, Any]:
    """Inspect bounded metadata; excluded subtrees are counted without opening them."""
    selected = source.expanduser().resolve(strict=True)
    root = selected.parent if selected.is_file() else selected
    deadline = time.monotonic() + SCAN_SECONDS
    counts = dict(
        entries=0,
        included_files=0,
        excluded_files=0,
        excluded_directories=0,
        unsupported_files=0,
        unfollowed_links=0,
        included_bytes=0,
    )
    accepted, rows, metadata_rows = [], [], []
    seen_files, seen_locators = set(), set()

    def budget() -> None:
        counts["entries"] += 1
        if counts["entries"] > MAX_SCAN_ENTRIES or time.monotonic() > deadline:
            raise ExclusionLimitError(
                "Source traversal exceeds its entry or time bound; select a narrower folder."
            )

    def inspect(candidate: Path, depth: int) -> None:
        if depth > MAX_SCAN_DEPTH or time.monotonic() > deadline:
            raise ExclusionLimitError("Source traversal exceeds its depth bound.")
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise UnsafePathError("A symbolic link escapes the Source root.") from exc
        locator = normalise_locator(relative.as_posix())
        info = resolved.stat()
        directory = stat.S_ISDIR(info.st_mode)
        selected_decision = decision(policy, locator, directory=directory)
        metadata_rows.append(
            [
                locator,
                info.st_size,
                info.st_mtime_ns,
                directory,
                selected_decision["reason"],
                selected_decision["rule_ids"],
            ]
        )
        if directory:
            if not selected_decision["included"] and not _can_override_subtree(
                policy, unicodedata.normalize("NFC", locator)
            ):
                counts["excluded_directories"] += 1
                if len(rows) < MAX_PREVIEW_ROWS:
                    rows.append({"locator": locator, "kind": "directory", **selected_decision})
                return
            if candidate.is_symlink() or candidate.is_junction():
                counts["unfollowed_links"] += 1
                # Directory links are never followed, including cycles inside the root.
                if len(rows) < MAX_PREVIEW_ROWS:
                    rows.append(
                        {
                            "locator": locator,
                            "kind": "directory",
                            "included": False,
                            "reason": "directory_link_not_followed",
                            "rule_ids": [],
                        }
                    )
                return
            walk(resolved, depth + 1)
            return
        if resolved in seen_files:
            return
        normalized_locator = unicodedata.normalize("NFC", locator)
        if normalized_locator in seen_locators:
            raise UnsafePathError("Source filenames collide after portable normalization.")
        seen_files.add(resolved)
        seen_locators.add(normalized_locator)
        if not selected_decision["included"]:
            counts["excluded_files"] += 1
        elif not stat.S_ISREG(info.st_mode) or extractor_for(resolved) is None:
            counts["unsupported_files"] += 1
            selected_decision = {"included": False, "reason": "unsupported_type", "rule_ids": []}
        else:
            counts["included_files"] += 1
            counts["included_bytes"] += info.st_size
            if counts["included_files"] > max_files:
                raise ExclusionLimitError("Source exceeds its configured included-file limit.")
            accepted.append((locator, resolved))
        if len(rows) < MAX_PREVIEW_ROWS:
            rows.append({"locator": locator, "kind": "file", **selected_decision})

    def walk(directory: Path, depth: int) -> None:
        entries = []
        with os.scandir(directory) as iterator:
            for entry in iterator:
                budget()
                entries.append(Path(entry.path))
        for candidate in sorted(entries):
            inspect(candidate, depth)

    if selected.is_file():
        budget()
        inspect(selected, 0)
    else:
        walk(selected, 0)
    return {
        "files": sorted(accepted),
        "counts": counts,
        "rows": rows,
        "rows_truncated": counts["included_files"]
        + counts["excluded_files"]
        + counts["unsupported_files"]
        + counts["unfollowed_links"]
        + counts["excluded_directories"]
        > len(rows),
        "snapshot_fingerprint": fingerprint(sorted(metadata_rows)),
        "complete": True,
    }


__all__ = [
    "ExclusionError",
    "ExclusionLimitError",
    "KINDS",
    "TYPE_EXTENSIONS",
    "canonical_json",
    "decision",
    "default_policy",
    "fingerprint",
    "normalize_policy",
    "policy_for_source",
    "rule",
    "scan",
]
