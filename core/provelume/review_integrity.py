"""Read-only validation of retained reviewed effects and explicit Version origins."""

from __future__ import annotations

import re

from .review_decisions import checked_path, read_bytes, read_json, validate_receipt
from .review_effects import ReviewUnavailable, sha256

CAPABILITIES = {
    "placement": ("classify",),
    "routing": ("save_rule", "revoke_rule", "apply_rule"),
    "duplicates": ("link_exact", "relate", "keep_separate", "new_version"),
    "versions": ("select_current", "new_version"),
    "annotations": ("save", "undo"),
}


def validate_review_origin(store, origin, records):
    fields = {
        "schema_version",
        "id",
        "source_version_id",
        "source_document_id",
        "target_document_id",
        "previous_current_version_id",
        "original_id",
        "content_hash",
        "history_ref",
        "history_sha256",
        "principal",
        "recorded_at",
    }
    try:
        if (
            set(origin) != fields
            or type(origin["schema_version"]) is not int
            or origin["schema_version"] != 1
        ):
            raise ValueError("origin schema")
        for key in ("id", "source_version_id", "previous_current_version_id"):
            if (
                not isinstance(origin[key], str)
                or re.fullmatch(r"ver_[0-9a-f]{32}", origin[key]) is None
            ):
                raise ValueError("origin Version identity")
        for key in ("source_document_id", "target_document_id"):
            if origin[key] not in records["documents"]:
                raise ValueError("origin Document missing")
        version = records["versions"].get(origin["id"])
        source = records["versions"].get(origin["source_version_id"])
        previous = records["versions"].get(origin["previous_current_version_id"])
        original = records["originals"].get(origin["original_id"])
        if not all(isinstance(row, dict) for row in (version, source, previous, original)):
            raise ValueError("origin input missing")
        if (
            version["document_id"] != origin["target_document_id"]
            or source["document_id"] != origin["source_document_id"]
            or previous["document_id"] != origin["target_document_id"]
            or version["id"] in {source["id"], previous["id"]}
            or version["original_id"] != source["original_id"]
            or source["original_id"] != original["id"]
            or version["content_hash"] != source["content_hash"]
            or source["content_hash"] != origin["content_hash"]
            or original["sha256"] != origin["content_hash"]
            or version["size_bytes"] != source["size_bytes"]
            or source["size_bytes"] != original["size_bytes"]
            or version["media_type"] != source["media_type"]
            or version["acquired_at"] != source["acquired_at"]
            or type(version["sequence"]) is not int
            or type(previous["sequence"]) is not int
            or version["sequence"] <= previous["sequence"]
            or origin["principal"] not in {"local_browser", "local_cli"}
        ):
            raise ValueError("origin provenance mismatch")
        if not re.fullmatch(
            r"state/review/(duplicates|versions)/review_[0-9a-f]{32}\.json", origin["history_ref"]
        ):
            raise ValueError("origin history path")
        raw = read_bytes(store, origin["history_ref"])
        history = read_json(store, origin["history_ref"])
        if raw is None or sha256(raw) != origin["history_sha256"] or history is None:
            raise ValueError("origin history missing or changed")
        if (
            history.get("action") != "new_version"
            or history.get("selected_version_id") != origin["id"]
            or history.get("previous_current_version_id") != origin["previous_current_version_id"]
            or history.get("principal") != origin["principal"]
            or history.get("recorded_at") != origin["recorded_at"]
        ):
            raise ValueError("origin history binding")
        receipt = read_json(
            store, "state/review/receipts/" + origin["history_ref"].rsplit("/", 1)[1]
        )
        if receipt is None:
            raise ValueError("origin has no committed receipt")
        validate_receipt(receipt, instance_id=store.read_config()["instance"]["id"])
        if (
            receipt["history_ref"] != origin["history_ref"]
            or receipt["history_sha256"] != origin["history_sha256"]
            or receipt["result"].get("version_id") != origin["id"]
        ):
            raise ValueError("origin receipt differs from effect")
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewUnavailable("Retained reviewed Version origin is invalid") from exc


def review_state_findings(store, records):
    from .annotation_store import annotation_state_findings
    from .review_authority import ReviewAuthority
    from .review_routing import RoutingProvider

    findings = []

    def add(message, path="state/review"):
        findings.append({"code": "review_state_invalid", "message": str(message), "path": path})

    try:
        ReviewAuthority(store, CAPABILITIES).read()
        RoutingProvider(store).rules()
        root = checked_path(store, "state/review/receipts")
        if root.exists():
            if not root.is_dir():
                raise ReviewUnavailable("Review receipts are not a directory")
            for index, path in enumerate(root.iterdir()):
                if index >= 10_000 or re.fullmatch(r"review_[0-9a-f]{32}\.json", path.name) is None:
                    raise ReviewUnavailable("Review receipt inventory is invalid or incomplete")
                receipt = read_json(store, f"state/review/receipts/{path.name}")
                validate_receipt(receipt, instance_id=store.read_config()["instance"]["id"])
                if receipt["id"] != path.stem:
                    raise ReviewUnavailable("Review receipt identity differs from its path")
                raw = read_bytes(store, receipt["history_ref"])
                if raw is None or sha256(raw) != receipt["history_sha256"]:
                    raise ReviewUnavailable("Review receipt refers to missing or changed history")
                if (
                    receipt["domain"] in {"duplicates", "versions"}
                    and receipt["action"] == "new_version"
                ):
                    identifier = receipt["result"].get("version_id")
                    if identifier not in records.get("review-origins", {}):
                        raise ReviewUnavailable("Committed reviewed Version has lost its origin")
        for origin in records.get("review-origins", {}).values():
            validate_review_origin(store, origin, records)
        for message in annotation_state_findings(store, deep=True):
            add(message, "state/review/annotations")
    except (ReviewUnavailable, OSError, ValueError, TypeError, KeyError) as exc:
        add(exc)
    return findings
