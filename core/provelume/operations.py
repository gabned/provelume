from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any
from uuid import uuid4

from .storage import InstanceStore, utc_now

OPERATION_SCHEMA_VERSION = 1
OPERATION_STATUSES = frozenset(
    {"running", "completed", "completed_with_errors", "failed"}
)
OPERATION_LEVELS = frozenset({"info", "warning", "error"})
_OPERATION_ID = re.compile(r"op_[0-9a-f]{32}\Z")
MAX_EVENTS = 500
MAX_MESSAGE_CHARS = 2000
MAX_CODE_CHARS = 120


@dataclass(frozen=True, slots=True)
class OperationEvent:
    at: str
    level: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OperationRecord:
    schema_version: int
    id: str
    kind: str
    title: str
    status: str
    started_at: str
    completed_at: str | None
    summary: str | None
    parent_operation_id: str | None
    related: dict[str, str]
    metrics: dict[str, int]
    error_code: str | None
    error: str | None
    events: tuple[OperationEvent, ...]


class OperationLedger:
    """Instance-local, path-redacted log of high-level product operations."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.records = store.paths.state / "operations" / "records"

    @staticmethod
    def _bounded(value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()[:MAX_MESSAGE_CHARS]

    @staticmethod
    def _record_from_payload(payload: dict[str, Any]) -> OperationRecord:
        events = tuple(OperationEvent(**event) for event in payload.get("events", []))
        return OperationRecord(
            schema_version=int(payload["schema_version"]),
            id=str(payload["id"]),
            kind=str(payload["kind"]),
            title=str(payload["title"]),
            status=str(payload["status"]),
            started_at=str(payload["started_at"]),
            completed_at=payload.get("completed_at"),
            summary=payload.get("summary"),
            parent_operation_id=payload.get("parent_operation_id"),
            related={
                str(key): str(value)
                for key, value in payload.get("related", {}).items()
            },
            metrics={
                str(key): int(value)
                for key, value in payload.get("metrics", {}).items()
            },
            error_code=payload.get("error_code"),
            error=payload.get("error"),
            events=events,
        )

    @staticmethod
    def _payload(record: OperationRecord) -> dict[str, Any]:
        value = asdict(record)
        value["events"] = [asdict(event) for event in record.events]
        return value

    def _write(self, record: OperationRecord) -> None:
        if (
            record.schema_version != OPERATION_SCHEMA_VERSION
            or _OPERATION_ID.fullmatch(record.id) is None
            or record.status not in OPERATION_STATUSES
        ):
            raise ValueError("invalid operation record")
        self.records.mkdir(parents=True, exist_ok=True)
        self.store._atomic_json(
            self.records / f"{record.id}.json",
            self._payload(record),
        )

    def start(
        self,
        kind: str,
        title: str,
        *,
        summary: str | None = None,
        parent_operation_id: str | None = None,
        related: dict[str, str] | None = None,
    ) -> OperationRecord:
        selected_kind = kind.strip()
        if not selected_kind:
            raise ValueError("operation kind is required")
        if (
            parent_operation_id is not None
            and _OPERATION_ID.fullmatch(parent_operation_id) is None
        ):
            raise ValueError("invalid parent operation ID")
        record = OperationRecord(
            schema_version=OPERATION_SCHEMA_VERSION,
            id=f"op_{uuid4().hex}",
            kind=selected_kind[:MAX_CODE_CHARS],
            title=self._bounded(title) or selected_kind,
            status="running",
            started_at=utc_now(),
            completed_at=None,
            summary=self._bounded(summary),
            parent_operation_id=parent_operation_id,
            related={
                str(key)[:MAX_CODE_CHARS]: str(value)[:MAX_MESSAGE_CHARS]
                for key, value in sorted((related or {}).items())
            },
            metrics={},
            error_code=None,
            error=None,
            events=(),
        )
        self._write(record)
        return record

    def append(
        self,
        operation_id: str,
        code: str,
        message: str,
        *,
        level: str = "info",
        details: dict[str, Any] | None = None,
    ) -> OperationRecord:
        if level not in OPERATION_LEVELS:
            raise ValueError("invalid operation event level")
        record = self.get_record(operation_id)
        if record is None:
            raise KeyError(operation_id)
        if record.status != "running":
            raise ValueError("cannot append to a closed operation")
        safe_details: dict[str, Any] = {}
        for key, value in (details or {}).items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe_details[str(key)[:MAX_CODE_CHARS]] = (
                    self._bounded(value) if isinstance(value, str) else value
                )
        event = OperationEvent(
            at=utc_now(),
            level=level,
            code=code.strip()[:MAX_CODE_CHARS],
            message=self._bounded(message) or code.strip(),
            details=safe_details,
        )
        events = (*record.events, event)
        if len(events) > MAX_EVENTS:
            events = events[-MAX_EVENTS:]
        updated = replace(record, events=events)
        self._write(updated)
        return updated

    def close(
        self,
        operation_id: str,
        *,
        status: str,
        summary: str | None = None,
        metrics: dict[str, int] | None = None,
        error_code: str | None = None,
        error: str | None = None,
    ) -> OperationRecord:
        if status not in OPERATION_STATUSES - {"running"}:
            raise ValueError("operation must close with a terminal status")
        record = self.get_record(operation_id)
        if record is None:
            raise KeyError(operation_id)
        if record.status != "running":
            raise ValueError("operation is already closed")
        closed = replace(
            record,
            status=status,
            completed_at=utc_now(),
            summary=self._bounded(summary) if summary is not None else record.summary,
            metrics={
                str(key)[:MAX_CODE_CHARS]: int(value)
                for key, value in (metrics or {}).items()
            },
            error_code=(error_code or "")[:MAX_CODE_CHARS] or None,
            error=self._bounded(error),
        )
        self._write(closed)
        return closed

    def get_record(self, operation_id: str) -> OperationRecord | None:
        if _OPERATION_ID.fullmatch(operation_id) is None:
            return None
        path = self.records / f"{operation_id}.json"
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"expected JSON object in {path}")
        return self._record_from_payload(value)

    def get(self, operation_id: str) -> dict[str, Any] | None:
        record = self.get_record(operation_id)
        return self._payload(record) if record is not None else None

    def list(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit < 1 or not self.records.exists():
            return []
        records = []
        for path in self.records.glob("op_*.json"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    value = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            if kind and value.get("kind") != kind:
                continue
            if status and value.get("status") != status:
                continue
            records.append(value)
        records.sort(
            key=lambda item: (
                str(item.get("started_at", "")),
                str(item.get("id", "")),
            ),
            reverse=True,
        )
        return records[: min(limit, 500)]

    def kinds(self) -> list[str]:
        return sorted({str(item["kind"]) for item in self.list(limit=500)})
