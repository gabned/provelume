from __future__ import annotations

import hashlib
import json
import platform
import re
from datetime import datetime
from pathlib import Path

from .build_info import current_build_info
from .storage import utc_now

EVENTS = {"connected", "tested", "disconnected", "project_revoked", "offline", "online"}


class GoogleConnectionEvidence:
    """Bounded operational observations, separate from release qualification claims."""

    def __init__(self, store):
        self.store = store
        self.path = store.paths.state / "google-adapters" / "connection-evidence.json"

    def read(self):
        if not self.path.is_file():
            return []
        if self.path.is_symlink() or self.path.stat().st_size > 128 * 1024:
            raise ValueError("google_qualification_evidence_invalid")
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict) or envelope.get("schema_version") != 1:
            raise ValueError("google_qualification_evidence_invalid")
        value = envelope.get("events")
        if not isinstance(value, list) or len(value) > 128:
            raise ValueError("google_qualification_evidence_invalid")
        fields = {
            "event",
            "capability",
            "source_identity_sha256",
            "observed_at",
            "build_commit",
            "provider_observation",
        }
        for item in value:
            if (
                not isinstance(item, dict)
                or set(item) != fields
                or item["event"] not in EVENTS
                or item["capability"] not in {None, "gmail", "drive"}
                or item["provider_observation"] not in {"google_rest", "local_or_synthetic"}
            ):
                raise ValueError("google_qualification_evidence_invalid")
            for key, length in (("source_identity_sha256", 64), ("build_commit", 40)):
                selected = item[key]
                if selected is not None and (
                    not isinstance(selected, str)
                    or re.fullmatch(rf"[0-9a-f]{{{length}}}", selected) is None
                ):
                    raise ValueError("google_qualification_evidence_invalid")
            if (
                not isinstance(item["observed_at"], str)
                or len(item["observed_at"]) > 40
                or datetime.fromisoformat(item["observed_at"]).tzinfo is None
            ):
                raise ValueError("google_qualification_evidence_invalid")
        return value

    def record(self, event, *, capability=None, source_id=None, live=False):
        if event not in EVENTS or capability not in {None, "gmail", "drive"}:
            raise ValueError("google_qualification_evidence_invalid")
        build = current_build_info()
        entry = {
            "event": event,
            "capability": capability,
            "source_identity_sha256": hashlib.sha256(source_id.encode()).hexdigest()
            if source_id
            else None,
            "observed_at": utc_now(),
            "build_commit": build.get("commit"),
            "provider_observation": "google_rest" if live else "local_or_synthetic",
        }
        self.store._atomic_json(
            self.path, {"schema_version": 1, "events": [*self.read(), entry][-128:]}
        )

    def report(self, *, expected_head, jobs):
        build = current_build_info()
        if (
            not isinstance(expected_head, str)
            or len(expected_head) != 40
            or any(char not in "0123456789abcdef" for char in expected_head)
            or build.get("source_repository") != "gabned/provelume"
            or build.get("commit") != expected_head
            or not build.get("metadata_present")
        ):
            raise ValueError("google_qualification_exact_head_required")
        events = [item for item in self.read() if item["build_commit"] == expected_head]
        checks = {}
        for capability in ("gmail", "drive"):
            connected = [
                item
                for item in events
                if item["event"] == "connected"
                and item["capability"] == capability
                and item["provider_observation"] == "google_rest"
            ]
            tested = any(
                item["event"] == "tested"
                and item["capability"] == capability
                and item["provider_observation"] == "google_rest"
                for item in events
            )
            reads = [
                job
                for job in jobs
                if job.get("status") == "succeeded"
                and (job.get("google_run") or {}).get("capability") == capability
                and job["google_run"].get("build_commit") == expected_head
                and job["google_run"].get("execution_adapter") == "google_rest"
                and job["google_run"].get("limits", {}).get("max_items_per_run") == 50
                and job["google_run"].get("limits", {}).get("max_pages_per_run") == 2
                and job["google_run"].get("limits", {}).get("max_total_bytes_per_run") == 67108864
                and job["google_run"].get("error_codes") == []
                and job["google_run"].get("progress", {}).get("errors") == 0
            ]
            checks[capability] = {
                "connected": bool(connected),
                "connection_test": tested,
                "bounded_read": any(
                    job["google_run"]["progress"]["processed"] > 0 for job in reads
                ),
                "processed_items": sum(job["google_run"]["progress"]["processed"] for job in reads),
            }
        reconnect = any(
            sum(
                item["event"] == "connected"
                and item["source_identity_sha256"] == source
                and item["provider_observation"] == "google_rest"
                for item in events
            )
            >= 2
            for source in {
                item["source_identity_sha256"] for item in events if item["source_identity_sha256"]
            }
        )
        passed = (
            all(
                all(row[key] for key in ("connected", "connection_test", "bounded_read"))
                for row in checks.values()
            )
            and reconnect
        )
        return {
            "schema_version": 1,
            "repository": "gabned/provelume",
            "exact_head": expected_head,
            "status": "OBSERVED" if passed else "INCOMPLETE",
            "platform": platform.system(),
            "observed_at": utc_now(),
            "checks": checks,
            "stable_reconnect_observed": reconnect,
            "private_content_in_report": False,
            "tokens_in_report": False,
            "release_qualification": "NOT_ASSERTED",
            "events": events,
        }


def main():
    import argparse

    from .service import ProvelumeInstance

    parser = argparse.ArgumentParser(description="Export redacted Google exact-build observations")
    parser.add_argument("--instance", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    instance = ProvelumeInstance(args.instance)
    report = GoogleConnectionEvidence(instance.store).report(
        expected_head=args.expected_head, jobs=instance.list_google_jobs(limit=500)
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
