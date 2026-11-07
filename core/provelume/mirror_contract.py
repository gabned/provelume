"""Closed one-way mirror contracts. Inventory identities never grant authority."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath

MAX_RECORDS = 20_000
MAX_DOCUMENTS = 1_000
MAX_FILES = 5_000
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_PLANS = 16
MAX_GENERATIONS = 8
MAX_DESTINATIONS = 32
MAX_SECONDS = 60
PLAN_SECONDS = 900
PROFILES = ("git", "github", "gitlab", "gitea", "folder", "rsync-ssh")
HASH = re.compile(r"[0-9a-f]{64}\Z")
_PATH = re.compile(r"(?:[a-z0-9_-]+/){0,4}[a-z0-9_.-]+\Z")
_SECRET = re.compile(
    rb"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----|"
    rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})|"
    rb"glpat-[A-Za-z0-9_-]{20,}|"
    rb"\bAKIA[A-Z0-9]{16}\b|"
    rb"(?i:(?:password|access_token|refresh_token|client_secret|api_key)"
    rb"[\"' \t]*[:=][\"' \t]*[^\s\"',}]{8,})"
)
_SENSITIVE = re.compile(
    rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    rb"(?i:\b(?:confidential|riservato|medical|sanitario|iban)\b)"
)


class MirrorError(ValueError):
    def __init__(self, code="invalid"):
        self.code = code
        super().__init__("mirror_" + code)


def require(value, code="invalid"):
    if not value:
        raise MirrorError(code)


def raw(value, *, maximum=MAX_MANIFEST_BYTES):
    try:
        result = (
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            + "\n"
        ).encode()
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise MirrorError() from None
    require(len(result) <= maximum, "limit")
    return result


def parse(data):
    require(type(data) is bytes and len(data) <= MAX_MANIFEST_BYTES, "limit")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "integrity")
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=pairs)
    except (ValueError, RecursionError, UnicodeError):
        raise MirrorError("integrity") from None
    require(type(value) is dict)
    raw(value)
    return value


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fingerprint(value):
    return sha(raw(value))


def identifier(value, prefix):
    require(type(value) is str and re.fullmatch(prefix + r"_[0-9a-f]{32}", value))
    return value


def label(value):
    require(
        type(value) is str
        and 0 < len(value.strip()) <= 240
        and not any(ord(char) < 32 for char in value)
    )
    return value


def path(value):
    require(
        type(value) is str
        and len(value) <= 220
        and _PATH.fullmatch(value)
        and not any(part in {".", "..", ".git"} for part in PurePosixPath(value).parts)
    )
    return value


def selection(value):
    require(type(value) is dict and set(value) == {"kind", "id"})
    require(value["kind"] in {"instance", "area", "project"})
    identifier(
        value["id"], {"instance": "inst", "area": "area", "project": "project"}[value["kind"]]
    )
    return value


def includes(value):
    require(type(value) is dict and set(value) == {"originals", "attachments", "ai_receipts"})
    for _name, values in value.items():
        require(
            type(values) is list and len(values) <= MAX_DOCUMENTS and values == sorted(set(values))
        )
        for item in values:
            require(
                type(item) is str
                and len(item) <= 100
                and re.fullmatch(r"[a-z0-9]+_[a-z0-9_]+", item)
            )
    return value


def inventory(value):
    """Exact complete inventory, sorted and unique, without filesystem side effects."""
    require(type(value) is list and len(value) <= MAX_FILES, "limit")
    names, total = [], 0
    for item in value:
        require(type(item) is dict and set(item) == {"path", "size_bytes", "sha256", "category"})
        names.append(path(item["path"]))
        require(
            type(item["size_bytes"]) is int and 0 <= item["size_bytes"] <= MAX_FILE_BYTES, "limit"
        )
        require(type(item["sha256"]) is str and HASH.fullmatch(item["sha256"]))
        require(
            item["category"] in {"markdown", "metadata", "original", "attachment", "ai_receipt"}
        )
        total += item["size_bytes"]
    require(names == sorted(set(names)) and len({name.casefold() for name in names}) == len(names))
    require(total <= MAX_TOTAL_BYTES, "limit")
    raw(value)
    return value


def findings(data):
    """Report categories only; never echo secret values or matched excerpts."""
    result = []
    if _SECRET.search(data):
        result.append("secret_pattern")
    if _SENSITIVE.search(data):
        result.append("sensitive_pattern")
    return result


def diff(source, destination):
    inventory(source)
    inventory(destination)
    before = {row["path"]: row for row in destination}
    after = {row["path"]: row for row in source}
    return {
        "add": [name for name in sorted(after) if name not in before],
        "change": [
            name for name in sorted(after) if name in before and after[name] != before[name]
        ],
        "retain_destination_only": [name for name in sorted(before) if name not in after],
        "delete": [],
    }


def destination_observation(value):
    require(
        type(value) is dict
        and set(value) == {"destination_sha256", "visibility", "writable", "inventory", "revision"}
    )
    require(
        type(value["destination_sha256"]) is str and HASH.fullmatch(value["destination_sha256"])
    )
    require(value["visibility"] in {"private", "public", "unknown"})
    require(type(value["writable"]) is bool)
    require(type(value["revision"]) is str and 0 < len(value["revision"]) <= 2048)
    inventory(value["inventory"])
    return value
