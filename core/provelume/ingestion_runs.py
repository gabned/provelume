from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .storage import InstanceStore

INGESTION_RUN_SCHEMA_VERSION = 1
INGESTION_RUN_STATUSES = frozenset(
    {"running", "completed", "completed_with_errors", "failed"}
)
INGESTION_ITEM_STATUSES = frozenset({"pending", "running", "completed", "failed"})
_RUN_ID = re.compile(r"run_[0-9a-f]{32}\Z")
_ITEM_ID = re.compile(r"item_[0-9a-f]{32}\Z")


@dataclass(frozen=True, slots=True)
class IngestionRunRecord:
    schema_version: int
    id: str
    source_id: str
    started_at: str
    completed_at: str | None
    status: str
    item_count: int
    completed_items: int
    failed_items: int
    max_file_bytes: int
    max_files: int
    retry_of_run_id: str | None = None
    error_code: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionItemRecord:
    schema_version: int
    id: str
    run_id: str
    source_id: str
    locator: str
    status: str
    attempt: int
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    acquisition_id: str | None = None
    outcome: str | None = None
    retry_of_item_id: str | None = None
    error_code: str | None = None
    error: str | None = None


class IngestionLedger:
    """Durable, local-only operational records for filesystem ingestion."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.root = store.paths.state / "ingestion"
        self.runs = self.root / "runs"
        self.items = self.root / "items"

    def _ensure_directories(self) -> None:
        self.runs.mkdir(parents=True, exist_ok=True)
        self.items.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def new_run_id() -> str:
        return f"run_{uuid4().hex}"

    @staticmethod
    def new_item_id() -> str:
        return f"item_{uuid4().hex}"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"expected JSON object in {path}")
        return value

    def write_run(self, run: IngestionRunRecord) -> None:
        if run.schema_version != INGESTION_RUN_SCHEMA_VERSION:
            raise ValueError("unsupported ingestion run schema version")
        if run.status not in INGESTION_RUN_STATUSES or _RUN_ID.fullmatch(run.id) is None:
            raise ValueError("invalid ingestion run record")
        self._ensure_directories()
        self.store._atomic_json(self.runs / f"{run.id}.json", asdict(run))

    def write_item(self, item: IngestionItemRecord) -> None:
        if item.schema_version != INGESTION_RUN_SCHEMA_VERSION:
            raise ValueError("unsupported ingestion item schema version")
        if (
            item.status not in INGESTION_ITEM_STATUSES
            or _ITEM_ID.fullmatch(item.id) is None
            or _RUN_ID.fullmatch(item.run_id) is None
        ):
            raise ValueError("invalid ingestion item record")
        self._ensure_directories()
        self.store._atomic_json(self.items / f"{item.id}.json", asdict(item))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if _RUN_ID.fullmatch(run_id) is None:
            return None
        path = self.runs / f"{run_id}.json"
        return self._read_json(path) if path.is_file() else None

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        if _ITEM_ID.fullmatch(item_id) is None:
            return None
        path = self.items / f"{item_id}.json"
        return self._read_json(path) if path.is_file() else None

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        if not self.runs.exists():
            return []
        records = [self._read_json(path) for path in self.runs.glob("run_*.json")]
        records.sort(
            key=lambda item: (str(item.get("started_at", "")), item["id"]),
            reverse=True,
        )
        return records[:limit]

    def items_for_run(self, run_id: str) -> list[dict[str, Any]]:
        if _RUN_ID.fullmatch(run_id) is None or not self.items.exists():
            return []
        records = []
        for path in self.items.glob("item_*.json"):
            record = self._read_json(path)
            if record.get("run_id") == run_id:
                records.append(record)
        records.sort(key=lambda item: (str(item.get("locator", "")), item["id"]))
        return records

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        return {"run": run, "items": self.items_for_run(run_id)}
