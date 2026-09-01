from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from .atomic_commit import (
    TRANSCRIPT_INTAKE_TRANSACTION_PROFILE,
    AtomicCommitError,
    AtomicInstanceCommit,
)
from .domain import (
    Acquisition,
    Document,
    DocumentVersion,
    Original,
    ProvenanceEdge,
    as_record,
)
from .instance_lifecycle import InstanceLifecycleManager
from .paths import UnsafePathError, safe_instance_path
from .scheduler import SchedulerStore, public_job_record
from .scheduler_model import SchedulerConflictError, SchedulerError, retry_payload
from .storage import InstanceStore, utc_now
from .transcript_bundle import (
    TRANSCRIPT_BUNDLE_GENERATOR,
    TRANSCRIPT_BUNDLE_KIND,
    TranscriptDerivedPlan,
    build_transcript_bundle,
    derivation_key_values,
    revision_id,
    transcript_id,
)
from .transcript_contract import (
    TRANSCRIPT_ADAPTER_ID,
    TRANSCRIPT_ADAPTER_VERSION,
    TRANSCRIPT_CONTRACT_SCHEMA_VERSION,
    TRANSCRIPT_JOB_KIND,
    TRANSCRIPT_PARSER_PROTOCOL_VERSION,
    TranscriptContractError,
    TranscriptLimits,
    profile_format,
    settings_fingerprint,
)
from .transcript_files import LocalTranscriptAdapter, TranscriptSnapshot
from .transcript_parsers import BoundedTranscriptParser, TranscriptParser
from .transcript_sources import TranscriptSourceManager

TRANSCRIPT_JOB_SCHEMA_VERSION = 1
TRANSCRIPT_RECIPE_SCHEMA_VERSION = 1
TRANSCRIPT_CONTRACT_VERSION = "1"
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "manual_intervention"}
_CHECKPOINT = Callable[[dict[str, int]], Mapping[str, Any]]
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_INTERNAL_ID = re.compile(r"[a-z][a-z0-9_]*_[0-9a-f]{32,64}\Z")
_COMPONENT_ID = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")
_COMPONENT_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}\Z")


def _json_bytes(value: Any) -> bytes:
    selected = as_record(value) if not isinstance(value, Mapping) else dict(value)
    return (json.dumps(selected, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _stable(prefix: str, value: str) -> str:
    return f"{prefix}_{uuid5(NAMESPACE_URL, value).hex}"


def _document_id(source_id: str, locator_sha256: str) -> str:
    return _stable("doc", f"transcript-document:{source_id}:{locator_sha256}")


def _version_id(document_id: str, sequence: int, original_sha256: str) -> str:
    return _stable("ver", f"transcript-version:{document_id}:{sequence}:{original_sha256}")


def _acquisition_id(source_id: str, locator_sha256: str, original_sha256: str) -> str:
    return _stable(
        "acq", f"transcript-acquisition:{source_id}:{locator_sha256}:{original_sha256}"
    )


def _edge(
    from_kind: str,
    from_id: str,
    relation: str,
    to_kind: str,
    to_id: str,
    *,
    created_at: str,
) -> ProvenanceEdge:
    identity = f"{from_kind}:{from_id}:{relation}:{to_kind}:{to_id}"
    return ProvenanceEdge(
        id=_stable("edge", identity),
        from_kind=from_kind,
        from_id=from_id,
        relation=relation,
        to_kind=to_kind,
        to_id=to_id,
        created_at=created_at,
    )


class TranscriptJobManager:
    """Durable explicit orchestration for Source-confined transcript intake."""

    def __init__(
        self,
        store: InstanceStore,
        *,
        parser: TranscriptParser | None = None,
    ):
        self.store = store
        self.sources = TranscriptSourceManager(store)
        self.scheduler = SchedulerStore(store)
        self.parser = parser or BoundedTranscriptParser()
        parser_id = getattr(self.parser, "parser_id", None)
        parser_version = getattr(self.parser, "parser_version", None)
        parser_protocol = getattr(self.parser, "parser_protocol_version", None)
        supported_profiles = getattr(self.parser, "supported_profiles", None)
        if (
            not isinstance(parser_id, str)
            or _COMPONENT_ID.fullmatch(parser_id) is None
            or not isinstance(parser_version, str)
            or _COMPONENT_VERSION.fullmatch(parser_version) is None
            or parser_protocol != TRANSCRIPT_PARSER_PROTOCOL_VERSION
            or not isinstance(supported_profiles, tuple)
            or not supported_profiles
            or any(profile not in {"srt-v1", "webvtt-v1"} for profile in supported_profiles)
        ):
            raise TranscriptContractError(
                "transcript_internal_error", "transcript parser contract is invalid"
            )
        self.root = store.paths.state / "transcript-intake"
        self.requests = self.root / "requests"
        self.runs = self.root / "runs"
        self.work = self.root / "work"
        self.cancellations = self.root / "cancellations"
        self.source_states = self.root / "sources"
        self.recipes = self.root / "recipes"

    def _settings_sha256(self, limits: TranscriptLimits) -> str:
        return settings_fingerprint(
            limits,
            parser_id=self.parser.parser_id,
            parser_version=self.parser.parser_version,
            parser_protocol_version=self.parser.parser_protocol_version,
        )

    def _parse(
        self,
        data: bytes,
        *,
        profile: str,
        limits: TranscriptLimits,
        deadline: float | None = None,
    ) -> Any:
        if profile not in self.parser.supported_profiles:
            raise TranscriptContractError(
                "transcript_profile_unsupported",
                "transcript profile is unavailable from the selected parser",
            )
        parsed = self.parser.parse(
            data,
            profile=profile,
            limits=limits,
            deadline=deadline,
        )
        if (
            parsed.profile != profile
            or parsed.parser_id != self.parser.parser_id
            or parsed.parser_version != self.parser.parser_version
            or parsed.parser_protocol_version != self.parser.parser_protocol_version
        ):
            raise TranscriptContractError(
                "transcript_internal_error",
                "transcript parser returned inconsistent provenance",
            )
        return parsed

    def _read_json(self, path: Path, *, limit: int = 8 * 1024 * 1024) -> dict[str, Any]:
        try:
            value_stat = path.lstat()
            if path.is_symlink() or not path.is_file() or value_stat.st_size > limit:
                raise TranscriptContractError(
                    "transcript_internal_error", "transcript intake state is invalid"
                )
            value = json.loads(path.read_text(encoding="utf-8"))
        except TranscriptContractError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TranscriptContractError(
                "transcript_internal_error", "transcript intake state is unreadable"
            ) from exc
        if not isinstance(value, dict):
            raise TranscriptContractError(
                "transcript_internal_error", "transcript intake state must be an object"
            )
        return value

    def _write_json(self, path: Path, value: Mapping[str, Any]) -> None:
        self.store._atomic_json(path, dict(value))

    def _write_immutable(self, path: Path, value: Mapping[str, Any]) -> None:
        selected = dict(value)
        if path.exists():
            if self._read_json(path) != selected:
                raise TranscriptContractError(
                    "transcript_internal_error", "transcript intake request is immutable"
                )
            return
        self._write_json(path, selected)

    def _policy_for_source(self, source_id: str) -> dict[str, Any] | None:
        matches = [
            policy
            for policy in self.scheduler.list_policies()
            if policy["job_kind"] == TRANSCRIPT_JOB_KIND
            and policy["scope"] == {"kind": "source", "id": source_id}
        ]
        if len(matches) > 1:
            raise TranscriptContractError(
                "transcript_internal_error", "transcript Source has multiple policies"
            )
        return matches[0] if matches else None

    def sync_policy(self, source_id: str) -> dict[str, Any]:
        source = self.sources.public_view(source_id)
        schedule = dict(source["schedule"])
        enabled = (
            source["lifecycle_state"] == "active"
            and source["state"] == "enabled"
            and schedule["mode"] == "interval"
        )
        state = "enabled" if enabled else "disabled"
        current = self._policy_for_source(source_id)
        if current is None:
            return self.scheduler.create_policy(
                job_kind=TRANSCRIPT_JOB_KIND,
                scope={"kind": "source", "id": source_id},
                state=state,
                schedule=schedule,
                retry=retry_payload(max_attempts=3, base_seconds=30, max_seconds=300),
            )
        if current["state"] == state and current["schedule"] == schedule:
            return current
        return self.scheduler.update_policy(
            str(current["id"]), state=state, schedule=schedule
        )

    def _request_record(
        self,
        job_id: str,
        snapshot: TranscriptSnapshot,
        limits: TranscriptLimits,
        *,
        resync: bool,
    ) -> dict[str, Any]:
        return {
            "schema_version": TRANSCRIPT_JOB_SCHEMA_VERSION,
            "job_id": job_id,
            **snapshot.safe_record(),
            "adapter_id": TRANSCRIPT_ADAPTER_ID,
            "adapter_version": TRANSCRIPT_ADAPTER_VERSION,
            "parser_id": self.parser.parser_id,
            "parser_version": self.parser.parser_version,
            "parser_protocol_version": self.parser.parser_protocol_version,
            "contract_version": TRANSCRIPT_CONTRACT_VERSION,
            "settings_sha256": self._settings_sha256(limits),
            "limits": limits.as_record(),
            "resync": resync,
            "requested_at": utc_now(),
            "network_used": False,
            "runtime_downloads": False,
            "remote_fallback": False,
        }

    def _source_state(self, source_id: str) -> dict[str, Any]:
        path = self.source_states / f"{source_id}.json"
        if not path.exists():
            return {
                "schema_version": TRANSCRIPT_JOB_SCHEMA_VERSION,
                "source_id": source_id,
                "cursor_revision": 0,
                "config_revision": 0,
                "snapshot_sha256": None,
                "item_count": 0,
                "last_job_id": None,
                "last_completed_at": None,
                "resync_required": False,
                "complete": False,
            }
        value = self._read_json(path, limit=128 * 1024)
        expected = {
            "schema_version",
            "source_id",
            "cursor_revision",
            "config_revision",
            "snapshot_sha256",
            "item_count",
            "last_job_id",
            "last_completed_at",
            "resync_required",
            "complete",
        }
        if (
            set(value) != expected
            or value.get("schema_version") != TRANSCRIPT_JOB_SCHEMA_VERSION
            or value.get("source_id") != source_id
        ):
            raise TranscriptContractError(
                "transcript_internal_error", "transcript Source cursor is invalid"
            )
        return value

    def reset_cursor(self, source_id: str) -> dict[str, Any]:
        source = self.sources.public_view(source_id)
        if source["lifecycle_state"] != "active":
            raise TranscriptContractError(
                "transcript_source_removed", "transcript Source was removed"
            )
        current = self._source_state(source_id)
        selected = {
            **current,
            "cursor_revision": int(current["cursor_revision"]) + 1,
            "config_revision": int(source["config_revision"]),
            "snapshot_sha256": None,
            "item_count": 0,
            "last_job_id": None,
            "last_completed_at": None,
            "resync_required": True,
            "complete": False,
        }
        self._write_json(self.source_states / f"{source_id}.json", selected)
        return dict(selected)

    def source_checkpoint(self, source_id: str) -> dict[str, Any]:
        self.sources.public_view(source_id)
        return self._source_state(source_id)

    def _snapshot(self, source_id: str, limits: TranscriptLimits) -> tuple[Any, Any]:
        config = self.sources.source_config(source_id, require_enabled=True)
        adapter = LocalTranscriptAdapter(config)
        return adapter, adapter.snapshot(limits=limits)

    def queue(
        self,
        source_id: str,
        *,
        request_key: str | None = None,
        force_retry: bool = False,
    ) -> dict[str, Any]:
        limits = TranscriptLimits()
        _adapter, snapshot = self._snapshot(source_id, limits)
        policy = self.sync_policy(source_id)
        source_state = self._source_state(source_id)
        identity = "\x1f".join(
            (
                source_id,
                snapshot.snapshot_sha256,
                snapshot.profile,
                str(snapshot.config_revision),
                TRANSCRIPT_ADAPTER_VERSION,
                self.parser.parser_id,
                self.parser.parser_version,
                str(self.parser.parser_protocol_version),
                self._settings_sha256(limits),
            )
        )
        if request_key is not None:
            selected_key = request_key.strip()
            if not selected_key or len(selected_key) > 200:
                raise TranscriptContractError(
                    "transcript_internal_error", "transcript idempotency key is invalid"
                )
            identity += f"\x1f{selected_key}"
        if force_retry:
            identity += f"\x1fretry:{uuid4().hex}"
        provisional = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        try:
            queued = self.scheduler.run_now(str(policy["id"]), request_key=provisional)
        except SchedulerError as exc:
            raise TranscriptContractError(
                "transcript_internal_error", "transcript intake could not be queued"
            ) from exc
        job = queued["job"]
        request = self._request_record(
            str(job["id"]),
            snapshot,
            limits,
            resync=bool(source_state["resync_required"]),
        )
        request_path = self.requests / f"{job['id']}.json"
        if request_path.exists():
            current = self._read_json(request_path)
            stable = set(request) - {"requested_at"}
            if any(current.get(key) != request.get(key) for key in stable):
                raise TranscriptContractError(
                    "transcript_internal_error", "transcript intake request is immutable"
                )
            request = current
        else:
            self._write_immutable(request_path, request)
        return {
            "schema_version": TRANSCRIPT_JOB_SCHEMA_VERSION,
            "created": bool(queued["created"]),
            "job": public_job_record(job),
            "request": {
                key: request[key]
                for key in (
                    "source_id",
                    "profile",
                    "selection_kind",
                    "config_revision",
                    "snapshot_sha256",
                    "file_count",
                    "total_bytes",
                    "settings_sha256",
                    "resync",
                    "network_used",
                )
            },
        }

    def _request_for_job(
        self, job: Mapping[str, Any]
    ) -> tuple[dict[str, Any], LocalTranscriptAdapter, TranscriptSnapshot, TranscriptLimits]:
        job_id = str(job["id"])
        source_id = str(job["scope"]["id"])
        path = self.requests / f"{job_id}.json"
        if path.exists():
            request = self._read_json(path)
            limits = TranscriptLimits.from_mapping(request.get("limits"))
            adapter, snapshot = self._snapshot(source_id, limits)
            safe = snapshot.safe_record()
            if (
                request.get("job_id") != job_id
                or any(request.get(key) != value for key, value in safe.items())
                or request.get("parser_id") != self.parser.parser_id
                or request.get("parser_version") != self.parser.parser_version
                or request.get("parser_protocol_version")
                != self.parser.parser_protocol_version
                or request.get("settings_sha256") != self._settings_sha256(limits)
            ):
                raise TranscriptContractError(
                    "transcript_input_changed",
                    "transcript Source changed after intake was queued",
                )
            return request, adapter, snapshot, limits
        if job.get("reason") not in {"scheduled", "coalesced", "catch_up"}:
            raise TranscriptContractError(
                "transcript_internal_error", "transcript intake request is missing"
            )
        limits = TranscriptLimits()
        adapter, snapshot = self._snapshot(source_id, limits)
        request = self._request_record(job_id, snapshot, limits, resync=False)
        self._write_immutable(path, request)
        return request, adapter, snapshot, limits

    def _cancel_requested(self, job_id: str) -> bool:
        path = self.cancellations / f"{job_id}.json"
        if not path.exists():
            return False
        value = self._read_json(path, limit=64 * 1024)
        return (
            value.get("schema_version") == TRANSCRIPT_JOB_SCHEMA_VERSION
            and value.get("job_id") == job_id
        )

    @staticmethod
    def _record_path(kind: str, record_id: str) -> str:
        return f"knowledge/{kind}/{record_id}.json"

    @staticmethod
    def _artifact_path(artifact_id: str) -> str:
        return f"state/derived/artifacts/{artifact_id}.json"

    @staticmethod
    def _derived_edge_path(edge_id: str) -> str:
        return f"state/derived/provenance/{edge_id}.json"

    def _artifact_valid(self, artifact_id: str) -> bool:
        record_path = self.store.paths.derived_artifacts / f"{artifact_id}.json"
        if not record_path.is_file() or record_path.is_symlink():
            return False
        try:
            record = self._read_json(record_path, limit=256 * 1024)
            target = safe_instance_path(self.store.paths.root, str(record["storage_ref"]))
            data = target.read_bytes()
            manifest = json.loads(data.decode("utf-8"))
        except (KeyError, OSError, UnicodeError, json.JSONDecodeError, UnsafePathError):
            return False
        if (
            hashlib.sha256(data).hexdigest() != record.get("checksum")
            or not isinstance(manifest, dict)
            or manifest.get("kind") != TRANSCRIPT_BUNDLE_KIND
            or manifest.get("status") != "complete"
            or manifest.get("complete") is not True
            or manifest.get("active_content_executed") is not False
            or manifest.get("network_used") is not False
        ):
            return False
        representations = manifest.get("representations")
        if not isinstance(representations, Mapping):
            return False
        for value in representations.values():
            try:
                path = safe_instance_path(self.store.paths.root, str(value["storage_ref"]))
                payload = path.read_bytes()
            except (KeyError, OSError, UnsafePathError, TypeError):
                return False
            if (
                path.is_symlink()
                or len(payload) != value.get("size_bytes")
                or hashlib.sha256(payload).hexdigest() != value.get("sha256")
            ):
                return False
        return True

    def _artifact_records(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(self.store.paths.derived_artifacts.glob("*.json")):
            try:
                result.append(self._read_json(path, limit=256 * 1024))
            except TranscriptContractError:
                continue
        return result

    @staticmethod
    def _recipe_relative(revision_id_value: str, derivation_key: str) -> str:
        return (
            f"state/transcript-intake/recipes/{revision_id_value}/"
            f"{derivation_key}.json"
        )

    @staticmethod
    def _recipe_record(
        *,
        plan: TranscriptDerivedPlan,
        parsed: Any,
        limits: TranscriptLimits,
        settings_sha256: str,
        source_id: str,
        connector_instance_id: str,
        original_id: str,
        locator_sha256: str,
        filesystem_identity_sha256: str,
        filesystem_mtime_ns: int,
        created_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": TRANSCRIPT_RECIPE_SCHEMA_VERSION,
            "revision_id": plan.revision_id,
            "transcript_id": plan.transcript_id,
            "derivation_key": plan.derivation_key,
            "source_id": source_id,
            "connector_instance_id": connector_instance_id,
            "original_id": original_id,
            "original_sha256": parsed.original_sha256,
            "profile": parsed.profile,
            "format": parsed.format,
            "adapter_id": TRANSCRIPT_ADAPTER_ID,
            "adapter_version": TRANSCRIPT_ADAPTER_VERSION,
            "parser_id": parsed.parser_id,
            "parser_version": parsed.parser_version,
            "parser_protocol_version": parsed.parser_protocol_version,
            "settings_sha256": settings_sha256,
            "limits": limits.as_record(),
            "locator_sha256": locator_sha256,
            "filesystem_identity_sha256": filesystem_identity_sha256,
            "filesystem_mtime_ns": filesystem_mtime_ns,
            "created_at": created_at,
            "network_used": False,
            "runtime_downloads": False,
            "remote_fallback": False,
            "active_content_executed": False,
        }

    @staticmethod
    def _normalise_recipe(value: Any) -> dict[str, Any]:
        fields = {
            "schema_version",
            "revision_id",
            "transcript_id",
            "derivation_key",
            "source_id",
            "connector_instance_id",
            "original_id",
            "original_sha256",
            "profile",
            "format",
            "adapter_id",
            "adapter_version",
            "parser_id",
            "parser_version",
            "parser_protocol_version",
            "settings_sha256",
            "limits",
            "locator_sha256",
            "filesystem_identity_sha256",
            "filesystem_mtime_ns",
            "created_at",
            "network_used",
            "runtime_downloads",
            "remote_fallback",
            "active_content_executed",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise TranscriptContractError(
                "transcript_derived_invalid", "transcript derivation recipe is incomplete"
            )
        identifiers = (
            value.get("revision_id"),
            value.get("transcript_id"),
            value.get("source_id"),
            value.get("connector_instance_id"),
            value.get("original_id"),
        )
        digests = (
            value.get("derivation_key"),
            value.get("original_sha256"),
            value.get("settings_sha256"),
            value.get("locator_sha256"),
            value.get("filesystem_identity_sha256"),
        )
        parser_id = value.get("parser_id")
        parser_version = value.get("parser_version")
        adapter_id = value.get("adapter_id")
        adapter_version = value.get("adapter_version")
        profile = value.get("profile")
        try:
            limits = TranscriptLimits.from_mapping(value.get("limits"))
        except TranscriptContractError as exc:
            raise TranscriptContractError(
                "transcript_derived_invalid", "transcript derivation limits are invalid"
            ) from exc
        if (
            value.get("schema_version") != TRANSCRIPT_RECIPE_SCHEMA_VERSION
            or any(
                not isinstance(identifier, str)
                or _INTERNAL_ID.fullmatch(identifier) is None
                for identifier in identifiers
            )
            or any(
                not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None
                for digest in digests
            )
            or profile not in {"srt-v1", "webvtt-v1"}
            or value.get("format") != profile_format(str(profile))
            or not isinstance(parser_id, str)
            or _COMPONENT_ID.fullmatch(parser_id) is None
            or not isinstance(parser_version, str)
            or _COMPONENT_VERSION.fullmatch(parser_version) is None
            or value.get("parser_protocol_version")
            != TRANSCRIPT_PARSER_PROTOCOL_VERSION
            or not isinstance(adapter_id, str)
            or _COMPONENT_ID.fullmatch(adapter_id) is None
            or not isinstance(adapter_version, str)
            or _COMPONENT_VERSION.fullmatch(adapter_version) is None
            or type(value.get("filesystem_mtime_ns")) is not int
            or not isinstance(value.get("created_at"), str)
            or not value.get("created_at")
            or any(
                value.get(field) is not False
                for field in (
                    "network_used",
                    "runtime_downloads",
                    "remote_fallback",
                    "active_content_executed",
                )
            )
        ):
            raise TranscriptContractError(
                "transcript_derived_invalid", "transcript derivation recipe is invalid"
            )
        selected_settings = settings_fingerprint(
            limits,
            parser_id=str(parser_id),
            parser_version=str(parser_version),
            parser_protocol_version=int(value["parser_protocol_version"]),
            adapter_id=str(adapter_id),
            adapter_version=str(adapter_version),
        )
        selected_derivation = derivation_key_values(
            original_sha256=str(value["original_sha256"]),
            profile=str(profile),
            parser_id=str(parser_id),
            parser_version=str(parser_version),
            parser_protocol_version=int(value["parser_protocol_version"]),
            settings_sha256=str(value["settings_sha256"]),
        )
        if (
            value.get("settings_sha256") != selected_settings
            or value.get("derivation_key") != selected_derivation
        ):
            raise TranscriptContractError(
                "transcript_derived_invalid",
                "transcript derivation recipe provenance is inconsistent",
            )
        return {**dict(value), "limits": limits.as_record()}

    def _recipes_for_revision(self, revision_id_value: str) -> list[dict[str, Any]]:
        if _INTERNAL_ID.fullmatch(revision_id_value) is None:
            raise TranscriptContractError(
                "transcript_derived_invalid", "transcript revision identity is invalid"
            )
        root = self.recipes / revision_id_value
        if not root.exists():
            return []
        if root.is_symlink() or not root.is_dir():
            raise TranscriptContractError(
                "transcript_derived_invalid", "transcript recipe location is unsafe"
            )
        recipes: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise TranscriptContractError(
                    "transcript_derived_invalid", "transcript recipe entry is unsafe"
                )
            selected = self._normalise_recipe(self._read_json(path, limit=256 * 1024))
            if (
                selected["revision_id"] != revision_id_value
                or path.stem != selected["derivation_key"]
            ):
                raise TranscriptContractError(
                    "transcript_derived_invalid", "transcript recipe identity is inconsistent"
                )
            recipes.append(selected)
        return recipes

    def _latest_recipe(self, revision_id_value: str) -> dict[str, Any] | None:
        recipes = self._recipes_for_revision(revision_id_value)
        recipes.sort(
            key=lambda value: (str(value["created_at"]), str(value["derivation_key"])),
            reverse=True,
        )
        return recipes[0] if recipes else None

    def _stage_plan(
        self,
        transaction: AtomicInstanceCommit,
        plan: TranscriptDerivedPlan,
    ) -> None:
        transaction.add(plan.manifest_relative, plan.manifest_bytes, immutable=True)
        transaction.add(plan.cues_relative, plan.cues_bytes, immutable=True)
        transaction.add(plan.text_relative, plan.text_bytes, immutable=True)
        for artifact in (plan.bundle_artifact, plan.text_artifact):
            transaction.add(
                self._artifact_path(artifact.id), _json_bytes(artifact), immutable=True
            )
        for edge in plan.derived_edges:
            transaction.add(
                self._derived_edge_path(edge.id), _json_bytes(edge), immutable=True
            )

    def _commit_transcript(
        self,
        *,
        job_id: str,
        source_config: Any,
        observed: Any,
        parsed: Any,
        limits: TranscriptLimits,
        recheck: Callable[[], None],
    ) -> tuple[str, str]:
        now = utc_now()
        document_id = _document_id(observed.source_id, observed.locator_sha256)
        existing_document = self.store.read_canonical("documents", document_id)
        versions = self.store.versions_for_document(document_id)
        existing_version = next(
            (item for item in versions if item.get("content_hash") == observed.sha256), None
        )
        if existing_version is None:
            sequence = max((int(item["sequence"]) for item in versions), default=0) + 1
            selected_version_id = _version_id(document_id, sequence, observed.sha256)
            version = DocumentVersion(
                id=selected_version_id,
                document_id=document_id,
                sequence=sequence,
                content_hash=observed.sha256,
                original_id=f"sha256_{observed.sha256}",
                media_type="application/octet-stream",
                size_bytes=observed.size_bytes,
                acquired_at=now,
            )
        else:
            selected_version_id = str(existing_version["id"])
            version = DocumentVersion(**existing_version)
        original_id = f"sha256_{observed.sha256}"
        existing_original = self.store.read_canonical("originals", original_id)
        original = (
            Original(**existing_original)
            if existing_original is not None
            else Original(
                id=original_id,
                sha256=observed.sha256,
                size_bytes=observed.size_bytes,
                storage_ref=f"originals/sha256/{observed.sha256[:2]}/{observed.sha256}",
                created_at=now,
            )
        )
        acquisition_id = _acquisition_id(
            observed.source_id, observed.locator_sha256, observed.sha256
        )
        existing_acquisition = self.store.read_canonical("acquisitions", acquisition_id)
        document = Document(
            id=document_id,
            source_id=observed.source_id,
            locator=f"transcript-locator:sha256:{observed.locator_sha256}",
            title=f"Transcript {document_id[-8:]}",
            media_type=version.media_type,
            created_at=(str(existing_document["created_at"]) if existing_document else now),
            current_version_id=selected_version_id,
        )
        acquisition = (
            Acquisition(**existing_acquisition)
            if existing_acquisition is not None
            else Acquisition(
                id=acquisition_id,
                source_id=observed.source_id,
                locator=f"transcript-locator:sha256:{observed.locator_sha256}",
                observed_at=now,
                content_hash=observed.sha256,
                outcome="acquired",
                document_id=document_id,
                version_id=selected_version_id,
                acquisition_kind="transcript",
                connector_instance_id=source_config.connector_instance_id,
                retrieved_at=now,
                media_type="application/octet-stream",
                original_id=original_id,
                content_encoding=None,
                response_size_bytes=observed.size_bytes,
                authorized_origins=(),
                derived_status=None,
                derived_artifact_id=None,
            )
        )
        settings_sha256 = self._settings_sha256(limits)
        plan = build_transcript_bundle(
            parsed=parsed,
            limits=limits,
            settings_sha256=settings_sha256,
            job_id=job_id,
            source_id=observed.source_id,
            connector_instance_id=source_config.connector_instance_id,
            locator_sha256=observed.locator_sha256,
            filesystem_identity_sha256=observed.filesystem_identity_sha256,
            filesystem_mtime_ns=observed.mtime_ns,
            acquisition_id=acquisition_id,
            document_id=document_id,
            version_id=selected_version_id,
            original_id=original_id,
            acquired_at=now,
        )
        recipe = self._recipe_record(
            plan=plan,
            parsed=parsed,
            limits=limits,
            settings_sha256=settings_sha256,
            source_id=observed.source_id,
            connector_instance_id=source_config.connector_instance_id,
            original_id=original_id,
            locator_sha256=observed.locator_sha256,
            filesystem_identity_sha256=observed.filesystem_identity_sha256,
            filesystem_mtime_ns=observed.mtime_ns,
            created_at=now,
        )
        recipe_path = self.store.paths.root / self._recipe_relative(
            plan.revision_id, plan.derivation_key
        )
        if recipe_path.exists():
            if recipe_path.is_symlink() or not recipe_path.is_file():
                raise TranscriptContractError(
                    "transcript_derived_invalid", "transcript derivation recipe is unsafe"
                )
            existing_recipe = self._normalise_recipe(self._read_json(recipe_path))
            stable_recipe_fields = set(recipe) - {
                "created_at",
                "filesystem_identity_sha256",
                "filesystem_mtime_ns",
            }
            if any(
                existing_recipe.get(key) != recipe.get(key)
                for key in stable_recipe_fields
            ):
                raise TranscriptContractError(
                    "transcript_derived_invalid",
                    "transcript derivation recipe conflicts with exact-byte provenance",
                )
            recipe = existing_recipe
        if (
            existing_acquisition is not None
            and self._artifact_valid(plan.bundle_artifact.id)
            and recipe_path.is_file()
        ):
            recheck()
            if existing_document != as_record(document):
                transaction = AtomicInstanceCommit(
                    self.store,
                    InstanceLifecycleManager(self.store).control_root / "transactions",
                    profile=TRANSCRIPT_INTAKE_TRANSACTION_PROFILE,
                    owner_id=job_id,
                    error_type=TranscriptContractErrorAdapter,
                    integrity_error_type=TranscriptContractErrorAdapter,
                    limit_error_type=TranscriptContractErrorAdapter,
                )
                transaction.add(
                    self._record_path("documents", document.id),
                    _json_bytes(document),
                    immutable=False,
                )
                recheck()
                try:
                    transaction.commit()
                except AtomicCommitError as exc:
                    raise TranscriptContractError(
                        "transcript_internal_error",
                        "transcript current-version promotion failed",
                    ) from exc
            return "skipped", plan.revision_id
        revision = {
            "schema_version": TRANSCRIPT_CONTRACT_SCHEMA_VERSION,
            "id": plan.revision_id,
            "transcript_id": plan.transcript_id,
            "source_id": observed.source_id,
            "connector_instance_id": source_config.connector_instance_id,
            "locator_sha256": observed.locator_sha256,
            "document_id": document_id,
            "version_id": selected_version_id,
            "acquisition_id": acquisition_id,
            "original_id": original_id,
            "original_sha256": observed.sha256,
            "size_bytes": observed.size_bytes,
            "first_acquired_at": (
                self.store.read_canonical("transcript-revisions", plan.revision_id) or {}
            ).get("first_acquired_at", now),
            "identity_authority": "source-locator-and-exact-bytes",
            "filename_authoritative": False,
            "path_authoritative": False,
            "speaker_identity_verified": False,
            "media_existence_attested": False,
            "cross_source_merge": False,
        }
        edges = (
            _edge(
                "acquisition",
                acquisition_id,
                "captured",
                "original",
                original_id,
                created_at=acquisition.observed_at,
            ),
            _edge(
                "original",
                original_id,
                "materialized_as",
                "version",
                selected_version_id,
                created_at=acquisition.observed_at,
            ),
            _edge(
                "version",
                selected_version_id,
                "version_of",
                "document",
                document_id,
                created_at=acquisition.observed_at,
            ),
        )
        recheck()
        transaction = AtomicInstanceCommit(
            self.store,
            InstanceLifecycleManager(self.store).control_root / "transactions",
            profile=TRANSCRIPT_INTAKE_TRANSACTION_PROFILE,
            owner_id=job_id,
            error_type=TranscriptContractErrorAdapter,
            integrity_error_type=TranscriptContractErrorAdapter,
            limit_error_type=TranscriptContractErrorAdapter,
        )
        transaction.add(original.storage_ref, observed.data, immutable=True)
        transaction.add(
            self._record_path("originals", original.id), _json_bytes(original), immutable=True
        )
        transaction.add(
            self._record_path("documents", document.id), _json_bytes(document), immutable=False
        )
        transaction.add(
            self._record_path("versions", version.id), _json_bytes(version), immutable=True
        )
        transaction.add(
            self._record_path("acquisitions", acquisition.id),
            _json_bytes(acquisition),
            immutable=True,
        )
        transaction.add(
            self._record_path("transcript-revisions", plan.revision_id),
            _json_bytes(revision),
            immutable=True,
        )
        transaction.add(
            self._recipe_relative(plan.revision_id, plan.derivation_key),
            _json_bytes(recipe),
            immutable=True,
        )
        for edge in edges:
            transaction.add(
                self._record_path("provenance", edge.id), _json_bytes(edge), immutable=True
            )
        self._stage_plan(transaction, plan)
        recheck()
        try:
            transaction.commit()
        except AtomicCommitError as exc:
            raise TranscriptContractError(
                "transcript_internal_error", "transcript atomic promotion failed"
            ) from exc
        return "processed", plan.revision_id

    def _work_record(self, job_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        path = self.work / f"{job_id}.json"
        if path.exists():
            return self._read_json(path)
        value = {
            "schema_version": TRANSCRIPT_JOB_SCHEMA_VERSION,
            "job_id": job_id,
            "source_id": request["source_id"],
            "snapshot_sha256": request["snapshot_sha256"],
            "items": {},
        }
        self._write_json(path, value)
        return value

    def _write_run(
        self,
        job_id: str,
        request: Mapping[str, Any],
        *,
        status: str,
        progress: Mapping[str, int],
        error_codes: list[str],
    ) -> None:
        self._write_json(
            self.runs / f"{job_id}.json",
            {
                "schema_version": TRANSCRIPT_JOB_SCHEMA_VERSION,
                "job_id": job_id,
                "source_id": request["source_id"],
                "snapshot_sha256": request["snapshot_sha256"],
                "status": status,
                "progress": dict(progress),
                "error_codes": list(dict.fromkeys(error_codes)),
                "network_used": False,
                "private_content_logged": False,
                "completed_at": utc_now() if status != "running" else None,
            },
        )

    def execute(
        self,
        job: Mapping[str, Any],
        *,
        checkpoint: _CHECKPOINT | None = None,
    ) -> dict[str, int]:
        if job.get("job_kind") != TRANSCRIPT_JOB_KIND:
            raise TranscriptContractError(
                "transcript_internal_error", "transcript job kind is invalid"
            )
        job_id = str(job["id"])
        request, adapter, snapshot, limits = self._request_for_job(job)
        source_config = adapter.config
        deadline = time.monotonic() + limits.max_seconds_per_job
        work = self._work_record(job_id, request)
        items = work.get("items")
        if not isinstance(items, dict):
            raise TranscriptContractError(
                "transcript_internal_error", "transcript work journal is invalid"
            )
        progress = {"processed": 0, "skipped": 0, "errors": 0}
        errors: list[str] = []
        for prior in items.values():
            if isinstance(prior, Mapping) and prior.get("status") in {"processed", "skipped"}:
                progress[str(prior["status"])] += 1
            elif isinstance(prior, Mapping) and prior.get("status") == "error":
                progress["errors"] += 1
                if isinstance(prior.get("error_code"), str):
                    errors.append(str(prior["error_code"]))
        self._write_run(
            job_id, request, status="running", progress=progress, error_codes=errors
        )
        for candidate in snapshot.candidates:
            if self._cancel_requested(job_id):
                self._write_run(
                    job_id,
                    request,
                    status="cancelled",
                    progress=progress,
                    error_codes=[*errors, "transcript_cancelled"],
                )
                raise TranscriptContractError(
                    "transcript_cancelled", "transcript intake was cancelled"
                )
            if time.monotonic() > deadline:
                raise TranscriptContractError(
                    "transcript_timeout", "transcript job deadline was exceeded"
                )
            locator = candidate.locator_sha256
            prior = items.get(locator)
            if isinstance(prior, Mapping) and prior.get("status") in {"processed", "skipped"}:
                if checkpoint is not None:
                    checkpoint(dict(progress))
                continue
            if isinstance(prior, Mapping) and prior.get("status") == "error":
                progress["errors"] -= 1
                with suppress(ValueError):
                    errors.remove(str(prior.get("error_code")))
            try:
                observed = adapter.read_exact(
                    candidate,
                    limits=limits,
                    deadline=min(deadline, time.monotonic() + limits.max_seconds_per_file),
                )
                parsed = self._parse(
                    observed.data,
                    profile=source_config.profile,
                    limits=limits,
                    deadline=min(deadline, time.monotonic() + limits.max_seconds_per_file),
                )
                outcome, selected_revision = self._commit_transcript(
                    job_id=job_id,
                    source_config=source_config,
                    observed=observed,
                    parsed=parsed,
                    limits=limits,
                    recheck=lambda selected=candidate: adapter.assert_unchanged(selected),
                )
                progress[outcome] += 1
                items[locator] = {
                    "status": outcome,
                    "revision_id": selected_revision,
                    "original_sha256": observed.sha256,
                    "size_bytes": observed.size_bytes,
                }
                self._write_json(self.work / f"{job_id}.json", work)
            except TranscriptContractError as exc:
                if exc.code in {
                    "transcript_cancelled",
                    "transcript_timeout",
                    "transcript_input_changed",
                    "transcript_internal_error",
                }:
                    raise
                progress["errors"] += 1
                errors.append(exc.code)
                items[locator] = {"status": "error", "error_code": exc.code}
                self._write_json(self.work / f"{job_id}.json", work)
                if progress["errors"] > limits.max_errors_per_job:
                    raise TranscriptContractError(
                        "transcript_cue_limit_exceeded",
                        "transcript job error limit was exceeded",
                    ) from exc
            if checkpoint is not None:
                checkpoint(dict(progress))
        final_status = "completed_with_errors" if progress["errors"] else "completed"
        self._write_run(
            job_id, request, status=final_status, progress=progress, error_codes=errors
        )
        prior_state = self._source_state(source_config.source_id)
        self._write_json(
            self.source_states / f"{source_config.source_id}.json",
            {
                "schema_version": TRANSCRIPT_JOB_SCHEMA_VERSION,
                "source_id": source_config.source_id,
                "cursor_revision": int(prior_state["cursor_revision"]) + 1,
                "config_revision": source_config.config_revision,
                "snapshot_sha256": snapshot.snapshot_sha256,
                "item_count": snapshot.file_count,
                "last_job_id": job_id,
                "last_completed_at": utc_now(),
                "resync_required": bool(progress["errors"]),
                "complete": not bool(progress["errors"]),
            },
        )
        return progress

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.scheduler.get_job(job_id)
        if job is None or job.get("job_kind") != TRANSCRIPT_JOB_KIND:
            raise TranscriptContractError(
                "transcript_internal_error", "transcript job was not found"
            )
        if job["status"] == "running":
            marker = {
                "schema_version": TRANSCRIPT_JOB_SCHEMA_VERSION,
                "job_id": job_id,
                "requested_at": utc_now(),
            }
            self._write_immutable(self.cancellations / f"{job_id}.json", marker)
            return {"job_id": job_id, "status": "cancellation_requested"}
        if job["status"] in _TERMINAL_STATUSES:
            return public_job_record(job)
        try:
            return public_job_record(self.scheduler.cancel(job_id))
        except SchedulerConflictError as exc:
            raise TranscriptContractError(
                "transcript_internal_error", "transcript cancellation conflicted"
            ) from exc

    def retry(self, job_id: str) -> dict[str, Any]:
        current = self.get_job(job_id)
        if current is None:
            raise TranscriptContractError(
                "transcript_internal_error", "transcript job was not found"
            )
        if current["status"] not in _TERMINAL_STATUSES:
            raise TranscriptContractError(
                "transcript_internal_error", "transcript job is not terminal"
            )
        return self.queue(
            str(current["scope"]["id"]),
            request_key=f"retry-of:{job_id}",
            force_retry=True,
        )

    def _run_for_job(self, job_id: str) -> dict[str, Any] | None:
        path = self.runs / f"{job_id}.json"
        return self._read_json(path) if path.exists() else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.scheduler.get_job(job_id)
        if job is None or job.get("job_kind") != TRANSCRIPT_JOB_KIND:
            return None
        return {**public_job_record(job), "intake_run": self._run_for_job(job_id)}

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        jobs = [
            item
            for item in self.scheduler.list_jobs(limit=500)
            if item.get("job_kind") == TRANSCRIPT_JOB_KIND
        ]
        return [
            {**public_job_record(item), "intake_run": self._run_for_job(str(item["id"]))}
            for item in jobs[: max(0, min(limit, 500))]
        ]

    def _manifest_for_revision(self, revision: Mapping[str, Any]) -> dict[str, Any] | None:
        candidates = [
            artifact
            for artifact in self._artifact_records()
            if artifact.get("version_id") == revision.get("version_id")
            and artifact.get("kind") == TRANSCRIPT_BUNDLE_KIND
            and artifact.get("generator") == TRANSCRIPT_BUNDLE_GENERATOR
        ]
        candidates.sort(
            key=lambda value: (str(value.get("created_at", "")), str(value.get("id", ""))),
            reverse=True,
        )
        for artifact in candidates:
            if not self._artifact_valid(str(artifact["id"])):
                continue
            path = safe_instance_path(self.store.paths.root, str(artifact["storage_ref"]))
            manifest = self._read_json(path)
            if manifest.get("revision_id") == revision.get("id"):
                return manifest
        return None

    def _summary(
        self,
        revision: Mapping[str, Any],
        manifest: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        counts = manifest.get("counts", {}) if isinstance(manifest, Mapping) else {}
        recipe = self._latest_recipe(str(revision["id"]))
        parser = manifest.get("parser") if isinstance(manifest, Mapping) else None
        profile = manifest.get("profile") if isinstance(manifest, Mapping) else None
        if profile is None and recipe is not None:
            profile = recipe.get("profile")
        parser_id = parser.get("id") if isinstance(parser, Mapping) else None
        parser_version = parser.get("version") if isinstance(parser, Mapping) else None
        settings_sha256 = (
            parser.get("settings_sha256") if isinstance(parser, Mapping) else None
        )
        if recipe is not None:
            parser_id = parser_id or recipe.get("parser_id")
            parser_version = parser_version or recipe.get("parser_version")
            settings_sha256 = settings_sha256 or recipe.get("settings_sha256")
        return {
            "schema_version": TRANSCRIPT_JOB_SCHEMA_VERSION,
            "id": revision["id"],
            "transcript_id": revision["transcript_id"],
            "source_id": revision["source_id"],
            "connector_instance_id": revision["connector_instance_id"],
            "document_id": revision["document_id"],
            "version_id": revision["version_id"],
            "acquisition_id": revision["acquisition_id"],
            "original_id": revision["original_id"],
            "original_sha256": revision["original_sha256"],
            "size_bytes": revision["size_bytes"],
            "profile": profile,
            "parser_id": parser_id,
            "parser_version": parser_version,
            "settings_sha256": settings_sha256,
            "first_acquired_at": revision["first_acquired_at"],
            "cue_count": counts.get("cues"),
            "warning_count": counts.get("warnings"),
            "derived_status": (
                "complete"
                if manifest is not None
                else "removed" if recipe is not None else "unavailable"
            ),
            "source_scoped": True,
            "cross_source_merge": False,
            "private_content_included": False,
        }

    def list_revisions(
        self, *, source_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        revisions = self.store.list_canonical("transcript-revisions")
        selected = [
            revision
            for revision in revisions
            if source_id is None or revision.get("source_id") == source_id
        ]
        selected.sort(
            key=lambda item: (str(item["first_acquired_at"]), str(item["id"])),
            reverse=True,
        )
        return [
            self._summary(revision, self._manifest_for_revision(revision))
            for revision in selected[: max(0, min(limit, 500))]
        ]

    def get_revision(
        self, revision_id_value: str, *, include_content: bool = False
    ) -> dict[str, Any] | None:
        revision = self.store.read_canonical("transcript-revisions", revision_id_value)
        if revision is None:
            return None
        manifest = self._manifest_for_revision(revision)
        result = self._summary(revision, manifest)
        if not include_content or manifest is None:
            return result
        representations = manifest["representations"]
        cues_path = safe_instance_path(
            self.store.paths.root, str(representations["cues"]["storage_ref"])
        )
        text_path = safe_instance_path(
            self.store.paths.root, str(representations["text"]["storage_ref"])
        )
        try:
            cues_data = cues_path.read_bytes()
            text_data = text_path.read_bytes()
            cues = json.loads(cues_data.decode("utf-8"))
            text = text_data.decode("utf-8")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TranscriptContractError(
                "transcript_derived_invalid",
                "transcript representation cannot be inspected safely",
            ) from exc
        for key, data in (("cues", cues_data), ("text", text_data)):
            evidence = representations[key]
            if (
                len(data) != evidence.get("size_bytes")
                or hashlib.sha256(data).hexdigest() != evidence.get("sha256")
            ):
                raise TranscriptContractError(
                    "transcript_derived_invalid",
                    "transcript representation integrity check failed",
                )
        if not isinstance(cues, Mapping) or not isinstance(cues.get("cues"), list):
            raise TranscriptContractError(
                "transcript_derived_invalid", "transcript cue representation is invalid"
            )
        return {
            **result,
            "manifest": manifest,
            "cues": cues["cues"],
            "text": text,
            "private_content_included": True,
        }

    def original_bytes(self, revision_id_value: str) -> tuple[dict[str, Any], bytes]:
        revision = self.store.read_canonical("transcript-revisions", revision_id_value)
        if revision is None:
            raise TranscriptContractError(
                "transcript_source_missing", "transcript revision was not found"
            )
        original = self.store.read_canonical("originals", str(revision["original_id"]))
        if original is None:
            raise TranscriptContractError(
                "transcript_derived_invalid", "transcript Original record is missing"
            )
        data = self.store.original_bytes(str(original["id"]))
        if (
            hashlib.sha256(data).hexdigest() != original["sha256"]
            or len(data) != original["size_bytes"]
        ):
            raise TranscriptContractError(
                "transcript_derived_invalid", "transcript Original integrity check failed"
            )
        return dict(original), data

    def remove_derived(self, revision_id_value: str) -> dict[str, Any]:
        revision = self.store.read_canonical("transcript-revisions", revision_id_value)
        if revision is None:
            raise TranscriptContractError(
                "transcript_source_missing", "transcript revision was not found"
            )
        artifacts = [
            item
            for item in self._artifact_records()
            if item.get("version_id") == revision.get("version_id")
            and item.get("generator") == TRANSCRIPT_BUNDLE_GENERATOR
        ]
        if not artifacts:
            return {**self._summary(revision, None), "removed_files": 0}
        artifact_ids = {str(item["id"]) for item in artifacts}
        refs: set[str] = set()
        expected_prefix = f"state/derived/transcripts/{revision_id_value}/"
        for artifact in artifacts:
            reference = str(artifact.get("storage_ref", ""))
            if not reference.startswith(expected_prefix):
                raise TranscriptContractError(
                    "transcript_derived_invalid",
                    "transcript representation escaped its revision boundary",
                )
            refs.add(reference)
            if artifact.get("kind") != TRANSCRIPT_BUNDLE_KIND:
                continue
            if not self._artifact_valid(str(artifact["id"])):
                raise TranscriptContractError(
                    "transcript_derived_invalid",
                    "transcript representation failed integrity verification",
                )
            manifest_path = safe_instance_path(self.store.paths.root, reference)
            manifest = self._read_json(manifest_path)
            if manifest.get("revision_id") != revision_id_value:
                raise TranscriptContractError(
                    "transcript_derived_invalid",
                    "transcript representation revision binding is invalid",
                )
            for key in ("cues", "text"):
                selected_ref = str(manifest["representations"][key]["storage_ref"])
                if not selected_ref.startswith(expected_prefix):
                    raise TranscriptContractError(
                        "transcript_derived_invalid",
                        "transcript representation escaped its revision boundary",
                    )
                refs.add(selected_ref)
        removed = 0
        roots: set[Path] = set()
        for ref in sorted(refs):
            path = safe_instance_path(self.store.paths.root, ref)
            roots.add(path.parent)
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise TranscriptContractError(
                        "transcript_derived_invalid", "transcript representation path is unsafe"
                    )
                path.unlink()
                removed += 1
        for artifact_id in artifact_ids:
            path = self.store.paths.derived_artifacts / f"{artifact_id}.json"
            if path.is_file() and not path.is_symlink():
                path.unlink()
        for edge in self.store.list_derived_provenance():
            if edge.get("from_id") in artifact_ids or edge.get("to_id") in artifact_ids:
                path = self.store.paths.derived_provenance / f"{edge['id']}.json"
                if path.is_file() and not path.is_symlink():
                    path.unlink()
        for root in sorted(roots, key=lambda value: len(value.parts), reverse=True):
            with suppress(OSError):
                root.rmdir()
        return {**self._summary(revision, None), "removed_files": removed}

    def rebuild_derived(self, revision_id_value: str) -> dict[str, Any]:
        revision = self.store.read_canonical("transcript-revisions", revision_id_value)
        if revision is None:
            raise TranscriptContractError(
                "transcript_source_missing", "transcript revision was not found"
            )
        if self._manifest_for_revision(revision) is not None:
            return self.get_revision(revision_id_value) or {}
        recipe = self._latest_recipe(revision_id_value)
        if recipe is None:
            raise TranscriptContractError(
                "transcript_derived_invalid", "transcript derivation recipe is missing"
            )
        if (
            recipe["parser_id"] != self.parser.parser_id
            or recipe["parser_version"] != self.parser.parser_version
            or recipe["parser_protocol_version"]
            != self.parser.parser_protocol_version
        ):
            raise TranscriptContractError(
                "transcript_profile_unsupported",
                "the parser recorded by this transcript recipe is not installed",
            )
        _original, data = self.original_bytes(revision_id_value)
        limits = TranscriptLimits.from_mapping(recipe["limits"])
        parsed = self._parse(data, profile=str(recipe["profile"]), limits=limits)
        acquisition = self.store.read_canonical("acquisitions", str(revision["acquisition_id"]))
        if acquisition is None:
            raise TranscriptContractError(
                "transcript_derived_invalid", "transcript acquisition is missing"
            )
        job_id = _stable(
            "job",
            f"transcript-derived-rebuild:{revision_id_value}:{recipe['derivation_key']}",
        )
        plan = build_transcript_bundle(
            parsed=parsed,
            limits=limits,
            settings_sha256=str(recipe["settings_sha256"]),
            job_id=job_id,
            source_id=str(revision["source_id"]),
            connector_instance_id=str(revision["connector_instance_id"]),
            locator_sha256=str(recipe["locator_sha256"]),
            filesystem_identity_sha256=str(recipe["filesystem_identity_sha256"]),
            filesystem_mtime_ns=int(recipe["filesystem_mtime_ns"]),
            acquisition_id=str(revision["acquisition_id"]),
            document_id=str(revision["document_id"]),
            version_id=str(revision["version_id"]),
            original_id=str(revision["original_id"]),
            acquired_at=utc_now(),
        )
        if plan.derivation_key != recipe["derivation_key"]:
            raise TranscriptContractError(
                "transcript_derived_invalid",
                "transcript rebuild did not reproduce the recorded derivation",
            )
        transaction = AtomicInstanceCommit(
            self.store,
            InstanceLifecycleManager(self.store).control_root / "transactions",
            profile=TRANSCRIPT_INTAKE_TRANSACTION_PROFILE,
            owner_id=job_id,
            error_type=TranscriptContractErrorAdapter,
            integrity_error_type=TranscriptContractErrorAdapter,
            limit_error_type=TranscriptContractErrorAdapter,
        )
        self._stage_plan(transaction, plan)
        transaction.commit()
        return self.get_revision(revision_id_value) or {}


class TranscriptContractErrorAdapter(AtomicCommitError):
    """Path-free error used internally by the atomic journal."""

    code = "transcript_internal_error"
    safe_message = "The transcript atomic commit failed closed."


__all__ = [
    "TRANSCRIPT_CONTRACT_VERSION",
    "TRANSCRIPT_JOB_SCHEMA_VERSION",
    "TranscriptJobManager",
]


def transcript_state_findings(
    store: InstanceStore,
    records: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[dict[str, str]]:
    """Deep validation findings for canonical bindings and content-free job state."""

    findings: list[dict[str, str]] = []

    def finding(code: str, message: str, path: str) -> None:
        findings.append({"code": code, "message": message, "path": path})

    manager = TranscriptJobManager(store)
    configured = store.read_config().get("transcript_sources")
    if configured is not None and not isinstance(configured, Mapping):
        finding(
            "transcript_source_config_invalid",
            "Transcript Source configuration must be an object",
            "provelume.yml",
        )
        configured = {}
    for source_id in configured or {}:
        try:
            manager.sources.public_view(str(source_id))
        except (TranscriptContractError, ValueError):
            finding(
                "transcript_source_config_invalid",
                "Transcript Source and connector configuration are inconsistent",
                "provelume.yml",
            )

    revision_fields = {
        "schema_version",
        "id",
        "transcript_id",
        "source_id",
        "connector_instance_id",
        "locator_sha256",
        "document_id",
        "version_id",
        "acquisition_id",
        "original_id",
        "original_sha256",
        "size_bytes",
        "first_acquired_at",
        "identity_authority",
        "filename_authoritative",
        "path_authoritative",
        "speaker_identity_verified",
        "media_existence_attested",
        "cross_source_merge",
    }
    recipes_by_revision: dict[str, dict[str, dict[str, Any]]] = {}
    for record_id, revision in records["transcript-revisions"].items():
        path = f"knowledge/transcript-revisions/{record_id}.json"
        source_id = str(revision.get("source_id"))
        locator_sha256 = str(revision.get("locator_sha256"))
        original_sha256 = str(revision.get("original_sha256"))
        document = records["documents"].get(str(revision.get("document_id")))
        version = records["versions"].get(str(revision.get("version_id")))
        acquisition = records["acquisitions"].get(str(revision.get("acquisition_id")))
        original = records["originals"].get(str(revision.get("original_id")))
        source = records["sources"].get(source_id)
        expected_transcript_id = transcript_id(source_id, locator_sha256)
        expected_revision_id = revision_id(expected_transcript_id, original_sha256)
        valid = (
            set(revision) == revision_fields
            and revision.get("schema_version") == TRANSCRIPT_CONTRACT_SCHEMA_VERSION
            and record_id == expected_revision_id
            and revision.get("transcript_id") == expected_transcript_id
            and source is not None
            and source.get("source_kind") == "transcript"
            and source.get("connector_instance_id") == revision.get("connector_instance_id")
            and document is not None
            and document.get("source_id") == source_id
            and document.get("locator") == f"transcript-locator:sha256:{locator_sha256}"
            and document.get("media_type") == "application/octet-stream"
            and version is not None
            and version.get("document_id") == revision.get("document_id")
            and version.get("content_hash") == original_sha256
            and version.get("original_id") == revision.get("original_id")
            and version.get("media_type") == "application/octet-stream"
            and acquisition is not None
            and acquisition.get("acquisition_kind") == "transcript"
            and acquisition.get("source_id") == source_id
            and acquisition.get("connector_instance_id")
            == revision.get("connector_instance_id")
            and acquisition.get("document_id") == revision.get("document_id")
            and acquisition.get("version_id") == revision.get("version_id")
            and acquisition.get("original_id") == revision.get("original_id")
            and acquisition.get("content_hash") == original_sha256
            and acquisition.get("response_size_bytes") == revision.get("size_bytes")
            and acquisition.get("media_type") == "application/octet-stream"
            and acquisition.get("content_encoding") is None
            and acquisition.get("derived_status") is None
            and acquisition.get("derived_artifact_id") is None
            and acquisition.get("requested_url") is None
            and acquisition.get("final_url") is None
            and acquisition.get("authorized_origins") == []
            and original is not None
            and original.get("sha256") == original_sha256
            and original.get("size_bytes") == revision.get("size_bytes")
            and revision.get("identity_authority") == "source-locator-and-exact-bytes"
            and revision.get("filename_authoritative") is False
            and revision.get("path_authoritative") is False
            and revision.get("speaker_identity_verified") is False
            and revision.get("media_existence_attested") is False
            and revision.get("cross_source_merge") is False
        )
        if not valid:
            finding(
                "transcript_revision_invalid",
                "Transcript revision identity or canonical binding is invalid",
                path,
            )
            continue
        try:
            recipes = manager._recipes_for_revision(record_id)
        except TranscriptContractError:
            finding(
                "transcript_recipe_invalid",
                "Transcript derivation recipe is unreadable or invalid",
                f"state/transcript-intake/recipes/{record_id}",
            )
            continue
        if not recipes:
            finding(
                "transcript_recipe_missing",
                "Transcript revision has no reproducible derivation recipe",
                f"state/transcript-intake/recipes/{record_id}",
            )
            continue
        selected_recipes: dict[str, dict[str, Any]] = {}
        for recipe in recipes:
            if (
                recipe.get("revision_id") != record_id
                or recipe.get("transcript_id") != expected_transcript_id
                or recipe.get("source_id") != source_id
                or recipe.get("connector_instance_id")
                != revision.get("connector_instance_id")
                or recipe.get("original_id") != revision.get("original_id")
                or recipe.get("original_sha256") != original_sha256
                or recipe.get("locator_sha256") != locator_sha256
            ):
                finding(
                    "transcript_recipe_invalid",
                    "Transcript derivation recipe is bound to the wrong revision",
                    f"state/transcript-intake/recipes/{record_id}",
                )
                continue
            selected_recipes[str(recipe["derivation_key"])] = recipe
        recipes_by_revision[record_id] = selected_recipes

    artifacts = manager._artifact_records()
    revisions_by_version = {
        str(revision.get("version_id")): (record_id, revision)
        for record_id, revision in records["transcript-revisions"].items()
    }
    for artifact in artifacts:
        if artifact.get("kind") != TRANSCRIPT_BUNDLE_KIND:
            continue
        revision_pair = revisions_by_version.get(str(artifact.get("version_id")))
        artifact_path = f"state/derived/artifacts/{artifact.get('id')}.json"
        if revision_pair is None:
            finding(
                "transcript_bundle_orphaned",
                "Transcript representation has no canonical revision",
                artifact_path,
            )
            continue
        record_id, revision = revision_pair
        if not manager._artifact_valid(str(artifact.get("id"))):
            finding(
                "transcript_bundle_invalid",
                "Transcript representation failed integrity verification",
                artifact_path,
            )
            continue
        try:
            manifest_path = safe_instance_path(
                store.paths.root, str(artifact.get("storage_ref"))
            )
            manifest = manager._read_json(manifest_path)
            derivation = manifest_path.parent.name
        except (TranscriptContractError, UnsafePathError):
            finding(
                "transcript_bundle_invalid",
                "Transcript representation manifest is invalid",
                artifact_path,
            )
            continue
        recipe = recipes_by_revision.get(record_id, {}).get(derivation)
        parser = manifest.get("parser")
        if (
            recipe is None
            or not isinstance(parser, Mapping)
            or manifest.get("revision_id") != record_id
            or manifest.get("transcript_id") != revision.get("transcript_id")
            or manifest.get("source_id") != revision.get("source_id")
            or manifest.get("connector_instance_id")
            != revision.get("connector_instance_id")
            or manifest.get("document_id") != revision.get("document_id")
            or manifest.get("version_id") != revision.get("version_id")
            or manifest.get("acquisition_id") != revision.get("acquisition_id")
            or manifest.get("original_id") != revision.get("original_id")
            or manifest.get("original_sha256") != revision.get("original_sha256")
            or manifest.get("profile") != recipe.get("profile")
            or manifest.get("format") != recipe.get("format")
            or parser.get("id") != recipe.get("parser_id")
            or parser.get("version") != recipe.get("parser_version")
            or parser.get("protocol_version")
            != recipe.get("parser_protocol_version")
            or parser.get("settings_sha256") != recipe.get("settings_sha256")
            or manifest.get("complete") is not True
            or manifest.get("active_content_executed") is not False
            or manifest.get("remote_resources_fetched") is not False
            or manifest.get("network_used") is not False
            or manifest.get("runtime_downloads") is not False
            or manifest.get("remote_fallback") is not False
        ):
            finding(
                "transcript_bundle_invalid",
                "Transcript representation is incomplete or incorrectly bound",
                artifact_path,
            )

    forbidden_keys = {
        "content",
        "filename",
        "meeting",
        "name",
        "participant",
        "path",
        "secret",
        "speaker",
        "text",
        "title",
        "token",
        "url",
    }

    def has_private_key(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(
                str(key).casefold() in forbidden_keys or has_private_key(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(has_private_key(item) for item in value)
        return False

    if manager.root.exists():
        for path in sorted(manager.root.rglob("*.json")):
            relative = path.relative_to(store.paths.root).as_posix()
            try:
                value = manager._read_json(path)
            except TranscriptContractError:
                finding(
                    "transcript_operational_state_invalid",
                    "Transcript operational state is unreadable",
                    relative,
                )
                continue
            if has_private_key(value):
                finding(
                    "transcript_operational_private_content",
                    "Transcript operational state contains a forbidden private field",
                    relative,
                )
            if path.parent == manager.source_states:
                source_id = str(value.get("source_id"))
                if path.stem != source_id or source_id not in records["sources"]:
                    finding(
                        "transcript_cursor_scope_invalid",
                        "Transcript cursor is not confined to one Source",
                        relative,
                    )
    return findings


__all__.append("transcript_state_findings")
