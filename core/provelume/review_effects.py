"""Immutable, IO-free value contracts for retained domain review effects."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .action_center_model import (
    ActionCenterConflict,
    ActionCenterDenied,
    ActionCenterError,
    ActionCenterStale,
    ActionCenterUnavailable,
    bounded_json,
    json_bytes,
)

ABSENT = "ABSENT"
MAX_WRITES = 256
MAX_ENTRY_BYTES = 8 * 1024 * 1024
MAX_EFFECT_BYTES = 32 * 1024 * 1024
ReviewError = ActionCenterError
ReviewStale = ActionCenterStale
ReviewConflict = ActionCenterConflict
ReviewDenied = ActionCenterDenied
ReviewUnavailable = ActionCenterUnavailable
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def relative_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 for char in value)
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(part.rstrip(" .") != part for part in value.split("/"))
    ):
        raise ReviewError("Review writes require a normalized relative path")
    return value


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedWrite:
    relative: str
    expected_sha256: str
    data: bytes
    immutable: bool = False

    def __post_init__(self) -> None:
        relative_path(self.relative)
        if self.expected_sha256 != ABSENT and (
            not isinstance(self.expected_sha256, str)
            or _HASH.fullmatch(self.expected_sha256) is None
        ):
            raise ReviewError("Review write requires an exact preimage or ABSENT")
        if type(self.data) is not bytes or len(self.data) > MAX_ENTRY_BYTES:
            raise ReviewError("Review candidate bytes exceed their bound")
        if type(self.immutable) is not bool:
            raise ReviewError("Invalid review write intent")
        if self.immutable and self.expected_sha256 != ABSENT:
            raise ReviewError("Immutable review writes must create a new record")


@dataclass(frozen=True, slots=True, init=False)
class PreparedEffect:
    domain: str
    action: str
    writes: tuple[PreparedWrite, ...]
    _result_json: bytes
    history_ref: str
    effect: str
    reversibility: str

    def __init__(
        self,
        domain: str,
        action: str,
        writes: tuple[PreparedWrite, ...],
        result: dict[str, Any],
        history_ref: str,
        effect: str,
        reversibility: str,
    ) -> None:
        if any(not isinstance(x, str) or _NAME.fullmatch(x) is None for x in (domain, action)):
            raise ReviewError("Invalid review effect identity")
        selected = tuple(writes)
        if (
            not selected
            or len(selected) > MAX_WRITES
            or any(not isinstance(x, PreparedWrite) for x in selected)
            or len({x.relative for x in selected}) != len(selected)
            or sum(len(x.data) for x in selected) > MAX_EFFECT_BYTES
        ):
            raise ReviewError("Invalid or unbounded review effect writes")
        relative_path(history_ref)
        if not any(x.relative == history_ref and x.immutable for x in selected):
            raise ReviewError("Review effect requires retained immutable domain history")
        if not isinstance(result, dict):
            raise ReviewError("Review result must be a JSON object")
        clean_result = bounded_json(result)
        for value in (effect, reversibility):
            if not isinstance(value, str) or not value or len(value) > 4000:
                raise ReviewError("Review effect description is missing or unbounded")
        for name, value in (
            ("domain", domain),
            ("action", action),
            ("writes", selected),
            ("_result_json", json_bytes(clean_result)),
            ("history_ref", history_ref),
            ("effect", effect),
            ("reversibility", reversibility),
        ):
            object.__setattr__(self, name, value)

    @property
    def result(self) -> dict[str, Any]:
        return json.loads(self._result_json)
