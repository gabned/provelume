"""Explicit preview/apply boundary for one managed filesystem Source."""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from queue import Empty, Queue
from threading import BoundedSemaphore, Thread
from typing import Any

from .folder_sources import FolderSourceManager
from .instance_lifecycle import InstanceLifecycleManager
from .paths import UnsafePathError
from .source_exclusions import (
    ExclusionError,
    default_policy,
    fingerprint,
    normalize_policy,
    policy_for_source,
    rule,
    scan,
)
from .storage import InstanceStore

PREVIEW_SECONDS = 5.0
_PREVIEW_SLOTS = BoundedSemaphore(2)


class ExclusionPreviewError(ExclusionError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def propose_change(current: Mapping[str, Any], fields: Mapping[str, str]) -> dict[str, Any]:
    current = normalize_policy(current)
    if fields.get("revision") != str(current["revision"]):
        raise ExclusionPreviewError("version_conflict")
    operation = fields.get("operation")
    if operation == "inspect":
        return current
    proposed = deepcopy(current)
    proposed["revision"] += 1
    if operation == "defaults":
        proposed = {**default_policy(), "revision": proposed["revision"]}
    elif operation == "state":
        if fields.get("enabled") not in {"true", "false"}:
            raise ExclusionError("Choose whether rules are enabled.")
        proposed["enabled"] = fields["enabled"] == "true"
    elif operation in {"upsert", "remove"}:
        selected_id = fields.get("rule_id") or None
        existing = next((item for item in proposed["rules"] if item["id"] == selected_id), None)
        if selected_id is not None and existing is None:
            raise ExclusionPreviewError("version_conflict")
        if existing is not None:
            proposed["rules"].remove(existing)
        if operation == "remove":
            if existing is None:
                raise ExclusionError("Select an existing rule to remove.")
        else:
            if fields.get("rule_enabled") not in {"true", "false"}:
                raise ExclusionError("Choose whether the rule is enabled.")
            proposed["rules"].append(
                rule(
                    fields.get("kind", ""),
                    fields.get("pattern", ""),
                    action=fields.get("rule_action", "exclude"),
                    enabled=fields["rule_enabled"] == "true",
                    rule_id=selected_id,
                )
            )
    else:
        raise ExclusionError("Unsupported exclusion operation.")
    return normalize_policy(proposed)


class FolderSourceExclusionManager:
    def __init__(self, store: InstanceStore):
        self.store = store
        self.sources = FolderSourceManager(store)

    def get(self, source_id: str) -> dict[str, Any]:
        self.sources._configured(source_id)
        policy = policy_for_source(self.store, source_id)
        assert policy is not None
        return {"source_id": source_id, "policy": policy, "fingerprint": fingerprint(policy)}

    def preview(self, source_id: str, policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
        current = self.get(source_id)
        proposed = normalize_policy(policy) if policy is not None else current["policy"]
        if proposed["revision"] not in {
            current["policy"]["revision"],
            current["policy"]["revision"] + 1,
        }:
            raise ExclusionPreviewError("version_conflict")
        _source, item, folder = self.sources._configured(source_id)
        path = Path(item["path"])
        if not path.is_absolute():
            path = self.store.paths.root / path
        if not _PREVIEW_SLOTS.acquire(blocking=False):
            raise ExclusionPreviewError("preview_busy")
        outcomes: Queue[Any] = Queue(maxsize=1)

        def probe() -> None:
            try:
                outcome = scan(
                    self.sources.selected_for_read(path), int(folder["max_files"]), proposed
                )
            except ExclusionError as exc:
                outcome = exc
            except (OSError, UnsafePathError):
                outcome = ExclusionPreviewError("preview_unavailable")
            except Exception:
                outcome = ExclusionPreviewError("preview_unavailable")
            finally:
                _PREVIEW_SLOTS.release()
            outcomes.put(outcome)

        try:
            Thread(target=probe, name="provelume-exclusion-preview", daemon=True).start()
        except RuntimeError as exc:
            _PREVIEW_SLOTS.release()
            raise ExclusionPreviewError("preview_busy") from exc
        try:
            outcome = outcomes.get(timeout=PREVIEW_SECONDS)
        except Empty as exc:
            raise ExclusionPreviewError("preview_timeout") from exc
        if isinstance(outcome, Exception):
            raise outcome
        preview_hash = fingerprint(
            {
                "schema_version": 1,
                "source_id": source_id,
                "current": current["fingerprint"],
                "proposed": proposed,
                "snapshot": outcome["snapshot_fingerprint"],
            }
        )
        return {
            "schema_version": 1,
            "source_id": source_id,
            "policy": proposed,
            "current_fingerprint": current["fingerprint"],
            "preview_fingerprint": preview_hash,
            "counts": outcome["counts"],
            "rows": outcome["rows"],
            "rows_truncated": outcome["rows_truncated"],
            "complete": outcome["complete"],
            "canonical_deletion": False,
        }

    def apply(
        self, source_id: str, policy: Mapping[str, Any], *, preview_fingerprint: str
    ) -> dict[str, Any]:
        with InstanceLifecycleManager(self.store)._hold(purpose="folder-source-exclusions"):
            current = self.get(source_id)
            proposed = normalize_policy(policy)
            if proposed["revision"] != current["policy"]["revision"] + 1:
                raise ExclusionPreviewError("version_conflict")
            # Repeat the exact read-only preview under the mutation lock. Late or
            # timed-out probes cannot ever apply their result or change records.
            checked = self.preview(source_id, proposed)
            if (
                not isinstance(preview_fingerprint, str)
                or re.fullmatch(r"[0-9a-f]{64}", preview_fingerprint) is None
                or not hmac.compare_digest(
                    checked["preview_fingerprint"],
                    preview_fingerprint,
                )
            ):
                raise ExclusionPreviewError("stale_preview")
            config = self.store.read_config()
            config["sources"][source_id]["exclusions"] = proposed
            self.store.write_config(config)
            return self.get(source_id)


__all__ = ["ExclusionPreviewError", "FolderSourceExclusionManager", "propose_change"]
