"""Bounded, read-only Operations and Maintenance projections of existing journals."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .scheduler import SchedulerStore, _receipt_matches_terminal_job, public_job_record
from .scheduler_control import public_control_progress
from .scheduler_model import (
    SCHEDULER_JOB_KINDS,
    TERMINAL_JOB_STATUSES,
    SchedulerError,
    validate_job_record,
    validate_policy_record,
    validate_receipt_record,
)
from .storage import InstanceStore

MAX_VIEW_RECORDS = 10_000
MAX_VIEW_RECORD_BYTES = 4 * 1024 * 1024
MAX_VIEW_TOTAL_BYTES = 64 * 1024 * 1024


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _link(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
    )


class OperationsMaintenance:
    """Observe validated producer records without opening/recovering an Instance."""

    def __init__(self, store: InstanceStore):
        self.store = store
        self.journal = SchedulerStore(store)

    def _directory(self, path: Path) -> tuple[dict[str, tuple], set[str]]:
        problems: set[str] = set()
        try:
            root = self.store.paths.root
            parents = (root, *(root / p for p in reversed(path.relative_to(root).parents)), path)
            for parent in parents:
                try:
                    details = parent.lstat()
                except FileNotFoundError:
                    return {}, problems
                if _link(details) or not stat.S_ISDIR(details.st_mode):
                    return {}, {"unsafe_directory"}
            result = {}
            with os.scandir(path) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_VIEW_RECORDS:
                        problems.add("record_limit")
                        break
                    # Windows DirEntry's cached stat omits device/inode; lstat
                    # provides the same real identity as the opened descriptor.
                    details = Path(entry.path).lstat()
                    if _link(details) or not stat.S_ISREG(details.st_mode):
                        problems.add("invalid_entry")
                        continue
                    if not entry.name.endswith(".json"):
                        problems.add("invalid_entry")
                        continue
                    result[entry.name] = _identity(details)
            return result, problems
        except OSError:
            return {}, {"unavailable"}

    def _records(self, path: Path, validator, *, initial=None) -> tuple[list[dict], dict[str, Any]]:
        before, initial_problems = initial if initial is not None else self._directory(path)
        problems = set(initial_problems)
        records = []
        consumed = 0
        for name, expected in sorted(before.items()):
            try:
                if expected[2] > MAX_VIEW_RECORD_BYTES:
                    problems.add("record_byte_limit")
                    continue
                if consumed + expected[2] > MAX_VIEW_TOTAL_BYTES:
                    problems.add("total_byte_limit")
                    break
                target = path / name
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(target, flags)
                with os.fdopen(descriptor, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if _identity(opened) != expected or not stat.S_ISREG(opened.st_mode):
                        problems.add("changed_during_observation")
                        continue
                    data = stream.read(MAX_VIEW_RECORD_BYTES + 1)
                    consumed += len(data)
                    final = os.fstat(stream.fileno())
                if len(data) > MAX_VIEW_RECORD_BYTES:
                    problems.add("record_byte_limit")
                    continue
                if _identity(final) != expected or _identity(target.lstat()) != expected:
                    problems.add("changed_during_observation")
                    continue
                value = validator(json.loads(data))
                if name != value["id"] + ".json":
                    problems.add("record_identity_mismatch")
                    continue
                records.append(value)
            except (OSError, UnicodeError, ValueError, KeyError, TypeError):
                problems.add("record_invalid")
        after, more = self._directory(path)
        problems.update(more)
        if after != before:
            problems.add("changed_during_observation")
        complete = not problems
        return records, {
            "status": "complete" if complete else "partial" if records else "unavailable",
            "complete": complete,
            "observed_count": len(records),
            "total": len(records) if complete else None,
            "limit": MAX_VIEW_RECORDS,
            "reasons": sorted(problems),
        }

    @staticmethod
    def _latest(values) -> str | None:
        return max(
            (v for v in values if isinstance(v, str)),
            key=lambda v: datetime.fromisoformat(v).astimezone(UTC),
            default=None,
        )

    def _instance_id(self) -> str:
        path = self.store.paths.config
        try:
            details = path.lstat()
            if (
                _link(details)
                or not stat.S_ISREG(details.st_mode)
                or details.st_size > MAX_VIEW_RECORD_BYTES
            ):
                raise ValueError
            with path.open("rb") as stream:
                data = stream.read(MAX_VIEW_RECORD_BYTES + 1)
            if len(data) > MAX_VIEW_RECORD_BYTES or _identity(path.lstat()) != _identity(details):
                raise ValueError
            config = yaml.safe_load(data)
            instance_id = config["instance"]["id"]
            if not isinstance(instance_id, str) or not re.fullmatch(
                r"inst_[0-9a-f]{32}", instance_id
            ):
                raise ValueError
            return instance_id
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
            raise SchedulerError("Instance identity unavailable") from exc

    @staticmethod
    def _source(value):
        if (
            not isinstance(value, dict)
            or not re.fullmatch(r"src_[0-9a-f]{32}", str(value.get("id")))
            or any(
                not isinstance(value.get(key), str) or not value[key].strip()
                for key in ("kind", "name", "created_at")
            )
        ):
            raise ValueError("source identity unavailable")
        return {"id": value["id"]}

    @staticmethod
    def _problem(coverage: dict, reason: str) -> None:
        coverage.update(complete=False, total=None)
        coverage["status"] = "partial" if coverage["observed_count"] else "unavailable"
        coverage["reasons"] = sorted(set(coverage["reasons"]) | {reason})

    @staticmethod
    def _job(job: dict, receipt: dict | None) -> dict:
        public = public_job_record(job)
        proof = bool(receipt and _receipt_matches_terminal_job(receipt, job))
        view = {
            **public,
            "display_state": {"succeeded": "completed", "manual_intervention": "blocked"}.get(
                job["status"], job["status"]
            ),
            "last_attempt_at": job["attempts"][-1]["started_at"] if job["attempts"] else None,
            "last_success_at": receipt["completed_at"]
            if proof and job["status"] == "succeeded"
            else None,
            "terminal_receipt": receipt if proof else None,
            "terminal_receipt_status": "verified" if proof else "unavailable",
            "evidence_url": "/api/v1/scheduler/jobs/" + job["id"],
            "detail_url": "/maintenance/jobs/" + job["id"],
            "progress_view": {
                "processed": job["progress"]["processed"],
                "skipped": job["progress"]["skipped"],
                "errors": job["progress"]["errors"],
                **public_control_progress(job),
            },
        }
        return view

    def _snapshot(self, *, limit: int, offset: int, job_id: str | None = None) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 500 or type(offset) is not int or offset < 0:
            raise ValueError("invalid Operations and Maintenance pagination")
        instance_id = self._instance_id()
        source_root = self.store.paths.canonical_dir("sources")
        paths = {
            "sources": source_root,
            "policies": self.journal.policies,
            "jobs": self.journal.jobs,
            "receipts": self.journal.receipts,
        }
        initial = {key: self._directory(path) for key, path in paths.items()}
        sources, source_coverage = self._records(
            source_root, self._source, initial=initial["sources"]
        )
        source_ids = {s["id"] for s in sources}
        policies, policy_coverage = self._records(
            self.journal.policies,
            lambda value: validate_policy_record(
                value, instance_id=instance_id, known_source_ids=source_ids
            ),
            initial=initial["policies"],
        )
        jobs, job_coverage = self._records(
            self.journal.jobs, validate_job_record, initial=initial["jobs"]
        )
        receipts, receipt_coverage = self._records(
            self.journal.receipts, validate_receipt_record, initial=initial["receipts"]
        )

        def belongs(record):
            scope = record["scope"]
            return (
                scope["id"] == instance_id
                if scope["kind"] == "instance"
                else scope["id"] in source_ids
            )

        for records, coverage in ((jobs, job_coverage), (receipts, receipt_coverage)):
            accepted = [record for record in records if belongs(record)]
            if len(accepted) != len(records):
                records[:] = accepted
                coverage["observed_count"] = len(accepted)
                self._problem(coverage, "instance_or_source_mismatch")
        coverages = {
            "sources": source_coverage,
            "policies": policy_coverage,
            "jobs": job_coverage,
            "receipts": receipt_coverage,
        }
        for key, path in paths.items():
            final = self._directory(path)
            if final != initial[key]:
                self._problem(coverages[key], "changed_during_observation")
        if self._instance_id() != instance_id:
            raise SchedulerError("Instance identity changed during observation")
        by_receipt = {r["id"]: r for r in receipts}
        views = []
        for job in jobs:
            reference = job.get("receipt_ref")
            receipt = by_receipt.get(Path(reference).stem) if reference else None
            view = self._job(job, receipt)
            if job["status"] in TERMINAL_JOB_STATUSES and view["terminal_receipt"] is None:
                self._problem(receipt_coverage, "terminal_receipt_unproven")
            if not job_coverage["complete"] or not receipt_coverage["complete"]:
                # Keep producer status while withholding a current terminal proof.
                view.update(
                    terminal_receipt=None,
                    terminal_receipt_status="unavailable",
                    last_success_at=None,
                )
            views.append(view)
        job_ids = {job["id"] for job in jobs}
        if any(receipt["job_id"] not in job_ids for receipt in receipts):
            self._problem(receipt_coverage, "receipt_job_unavailable")
        if not job_coverage["complete"] or not receipt_coverage["complete"]:
            for view in views:
                view.update(
                    terminal_receipt=None,
                    terminal_receipt_status="unavailable",
                    last_success_at=None,
                )
        views.sort(key=lambda j: (j["created_at"], j["id"]), reverse=True)
        complete = all(c["complete"] for c in coverages.values())
        policy_views = []
        for policy in policies:
            matching = [
                j
                for j in views
                if j["policy_id"] == policy["id"]
                and j["scope"] == policy["scope"]
                and j["job_kind"] == policy["job_kind"]
            ]
            policy_views.append(
                {
                    **policy,
                    "last_attempt_at": self._latest(j["last_attempt_at"] for j in matching),
                    "last_success_at": self._latest(j["last_success_at"] for j in matching),
                    "history_complete": job_coverage["complete"] and receipt_coverage["complete"],
                    "evidence_url": "/api/v1/scheduler/policies/" + policy["id"],
                }
            )
        kind_views = []
        for kind in SCHEDULER_JOB_KINDS:
            matching = [j for j in views if j["job_kind"] == kind]
            kind_views.append(
                {
                    "kind": kind,
                    "observed_jobs": len(matching),
                    "states": dict(Counter(j["display_state"] for j in matching)),
                    "last_attempt_at": self._latest(j["last_attempt_at"] for j in matching),
                    "last_success_at": self._latest(j["last_success_at"] for j in matching),
                    "history_complete": job_coverage["complete"] and receipt_coverage["complete"],
                }
            )
        binding = json.dumps(
            {
                "instance_id": instance_id,
                "sources": sources,
                "policies": policies,
                "jobs": jobs,
                "receipts": receipts,
                "coverage": coverages,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return {
            "schema_version": 1,
            "instance_id": instance_id,
            "observed_at": datetime.now(UTC).isoformat(),
            "revision": hashlib.sha256(binding).hexdigest(),
            "complete": complete,
            "coverage": coverages,
            "policies": policy_views,
            "job_kinds": kind_views,
            "jobs": [job for job in views if job["id"] == job_id]
            if job_id
            else views[offset : offset + limit],
            "observed_jobs": len(views),
            "total_jobs": len(views) if job_coverage["complete"] else None,
            "offset": offset,
            "limit": limit,
            "network_used": False,
            "canonical_mutation": False,
        }

    def snapshot(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._snapshot(limit=limit, offset=offset)

    def job(self, job_id: str) -> dict[str, Any] | None:
        if not isinstance(job_id, str) or not re.fullmatch(r"job_[0-9a-f]{32}", job_id):
            return None
        # Same bounded snapshot contract, including jobs beyond the first page.
        result = self._snapshot(limit=1, offset=0, job_id=job_id)
        if result["jobs"]:
            return {
                **result["jobs"][0],
                "observation_complete": result["complete"],
                "coverage": result["coverage"],
            }
        if not result["complete"]:
            raise SchedulerError("job evidence is unavailable")
        return None
