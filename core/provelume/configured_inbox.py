from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .domain import Source
from .folder_settings import FolderSettingsManager, inbox_source_id
from .inbox import InboxManager as BaseInboxManager
from .operations import OperationLedger
from .storage import InstanceStore, utc_now

_SUBMISSION_ID = re.compile(r"inbox_[0-9a-f]{32}\Z")


class InboxManager(BaseInboxManager):
    """Inbox runtime backed by configurable, optionally external local folders."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.folder_settings = FolderSettingsManager(store)
        self.operations = OperationLedger(store)
        self.submissions = store.paths.state / "inbox" / "submissions"
        self.legacy_submissions = store.paths.root / "inbox" / "submissions"
        self.root = store.paths.root / "inbox"
        self.drop = self.root / "drop"
        self.items = self.root / "items"
        self._refresh_paths()

    def _refresh_paths(self) -> None:
        settings = self.folder_settings.read()
        self.drop = settings.drop_path
        self.items = settings.managed_path

    def ensure(self) -> None:
        settings = self.folder_settings.ensure_paths()
        self.drop = settings.drop_path
        self.items = settings.managed_path
        self.submissions.mkdir(parents=True, exist_ok=True)

    def _source_id(self) -> str:
        self.ensure()
        settings = self.folder_settings.read()
        source_id = inbox_source_id(self.store)
        existing = self.store.read_canonical("sources", source_id)
        created_at = utc_now() if existing is None else str(existing["created_at"])
        if existing is None or existing.get("name") != settings.name:
            self.store.write_source(
                Source(
                    id=source_id,
                    kind="filesystem",
                    name=settings.name,
                    created_at=created_at,
                )
            )
        config = self.store.read_config()
        sources = config.setdefault("sources", {})
        if not isinstance(sources, dict):
            raise ValueError("Instance Sources configuration must be an object")
        sources[source_id] = {
            "kind": "filesystem",
            "name": settings.name,
            "path": settings.managed_configured,
        }
        self.store.write_config(config)
        return source_id

    def _submission_directories(self) -> tuple[Path, ...]:
        if self.submissions.resolve() == self.legacy_submissions.resolve():
            return (self.submissions,)
        return (self.submissions, self.legacy_submissions)

    def list_submissions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        records: dict[str, dict[str, Any]] = {}
        for directory in self._submission_directories():
            if not directory.exists():
                continue
            for path in directory.glob("inbox_*.json"):
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        value = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    continue
                record_id = str(value.get("id", "")) if isinstance(value, dict) else ""
                if (
                    isinstance(value, dict)
                    and _SUBMISSION_ID.fullmatch(record_id) is not None
                    and path.stem == record_id
                    and isinstance(value.get("created_at"), str)
                ):
                    records.setdefault(record_id, value)
        result = list(records.values())
        result.sort(
            key=lambda item: (
                str(item.get("created_at", "")),
                str(item.get("id", "")),
            ),
            reverse=True,
        )
        return result[: min(limit, 500)]

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        if _SUBMISSION_ID.fullmatch(submission_id) is None:
            return None
        for directory in self._submission_directories():
            path = directory / f"{submission_id}.json"
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8") as handle:
                    value = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and value.get("id") == submission_id:
                return value
        return None

    def summary(self) -> dict[str, Any]:
        self._refresh_paths()
        settings = self.folder_settings.public_view()
        submissions = self.list_submissions(limit=500)
        drop_files = (
            sum(1 for path in self.drop.rglob("*") if path.is_file())
            if self.drop.exists()
            else 0
        )
        return {
            "schema_version": 1,
            "name": settings["name"],
            "drop_locator": settings["drop"]["display"],
            "folders": {
                "drop": settings["drop"],
                "managed": settings["managed"],
                "canonical_storage": settings["canonical_storage"],
            },
            "drop_files": drop_files,
            "submissions": len(submissions),
            "completed": sum(
                item.get("status") == "completed" for item in submissions
            ),
            "attention": sum(
                item.get("status") in {"failed", "completed_with_errors"}
                for item in submissions
            ),
        }
