"""Closed host rules; model confidence never supplies classification authority."""

import re
from datetime import UTC, datetime, timedelta

from .action_center_model import digest, revision
from .review_effects import ReviewError, ReviewUnavailable
from .review_routing_model import identifier, selector_prefix

MODES = {"disabled", "proposal-only", "confirm-each", "controlled-automatic"}
MAX_POLICIES = 128
MAX_APPLICATIONS = 1000
IMPACT = "classification-metadata-only"
POLICY_FIELDS = {
    "schema_version", "id", "revision", "source_id", "path_prefix", "target_hashes",
    "profile_fingerprint", "languages", "expires_at", "mode", "impact", "max_applications",
    "used", "quality_revision", "last_receipt", "principal", "created_at", "updated_at",
}


def policy_identifier(value):
    if not isinstance(value, str) or re.fullmatch(r"autonomy_[0-9a-f]{32}", value) is None:
        raise ReviewError("Invalid classification policy identity")
    return value


def instant(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ReviewError("An explicit UTC expiry is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("UTC required")
    except ValueError as exc:
        raise ReviewError("An explicit UTC expiry is required") from exc
    return parsed.astimezone(UTC)


def utc(value):
    return instant(value).isoformat().replace("+00:00", "Z")


def quality_scope(profile, targets, languages):
    """Missing real qualification is a bound fact, never a caller-supplied flag.

    S05 must establish real scoped evidence. A later evidence revision invalidates
    these reviewed policies until the user explicitly reviews the changed scope.
    """
    return {
        "revision": digest(["iudicium-quality-not-evaluated", profile, targets, languages]),
        "qualification": "NOT_EVALUATED", "confidence": None, "automatic_allowed": False,
    }


def validate_policy(value):
    try:
        if not isinstance(value, dict) or set(value) != POLICY_FIELDS:
            raise ValueError("policy fields")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("policy schema")
        policy_identifier(value["id"])
        identifier(value["source_id"], "source")
        if (type(value["revision"]) is not int or not 1 <= value["revision"] <= 2**31 - 1
                or selector_prefix(value["path_prefix"]) != value["path_prefix"]):
            raise ValueError("policy revision or prefix")
        targets = value["target_hashes"]
        if not isinstance(targets, dict) or not 1 <= len(targets) <= 64:
            raise ValueError("target scope")
        for target, hashed in targets.items():
            identifier(target, "node")
            revision(hashed)
        revision(value["profile_fingerprint"])
        revision(value["quality_revision"])
        if (not isinstance(value["languages"], list) or not value["languages"]
                or value["languages"] != sorted(set(value["languages"]))
                or not set(value["languages"]) <= {"en", "it"}):
            raise ValueError("task language scope")
        if (value["mode"] not in MODES or value["impact"] != IMPACT
                or type(value["max_applications"]) is not int
                or not 1 <= value["max_applications"] <= MAX_APPLICATIONS
                or type(value["used"]) is not int
                or not 0 <= value["used"] <= value["max_applications"]):
            raise ValueError("policy impact or budget")
        if re.fullmatch(r"review_[0-9a-f]{32}", value["last_receipt"]) is None:
            raise ValueError("policy receipt")
        if value["principal"] not in {"local_browser", "local_cli"}:
            raise ValueError("policy reviewer")
        for key in ("created_at", "updated_at", "expires_at"):
            if utc(value[key]) != value[key]:
                raise ValueError("noncanonical policy time")
    except (ValueError, TypeError, KeyError) as exc:
        raise ReviewUnavailable("Classification policy is invalid or unsupported") from exc


def eligible(policy, *, source_id, locator, profile, language, target_hashes, now):
    """Evaluate only host-owned coordinates; original policy is never mutated."""
    validate_policy(policy)
    prefix = policy["path_prefix"]
    if (policy["mode"] in {"disabled", "proposal-only"}
            or instant(policy["expires_at"]) <= now
            or policy["used"] >= policy["max_applications"]):
        raise ReviewError("Classification policy is disabled, expired or exhausted")
    if (source_id != policy["source_id"]
            or (prefix and locator != prefix and not locator.startswith(prefix + "/"))
            or profile != policy["profile_fingerprint"]
            or language not in policy["languages"]
            or target_hashes != policy["target_hashes"]):
        raise ReviewError("Classification source, target or profile scope changed")
    quality = quality_scope(profile, target_hashes, policy["languages"])
    if quality["revision"] != policy["quality_revision"]:
        raise ReviewError("Changed quality evidence requires a new policy review")
    return quality
