"""Closed, retained routing rule and placement history contracts."""

from __future__ import annotations

import re

from .action_center_model import bounded_json, request_identifier, revision
from .hierarchy_model import classification_id
from .review_effects import ReviewError, ReviewUnavailable, relative_path

MAX_RULES = 500
MAX_NODES = 500
MAX_SECONDARY = 32
_PATTERNS = {
    "document": r"doc_[0-9a-f]{32}",
    "source": r"src_[0-9a-f]{32}",
    "version": r"ver_[0-9a-f]{32}",
    "original": r"sha256_[0-9a-f]{64}",
    "rule": r"routing_[0-9a-f]{32}",
    "node": r"(?:area|project|collection)_[0-9a-f]{32}",
}


def identifier(value, kind: str) -> str:
    if not isinstance(value, str) or re.fullmatch(_PATTERNS[kind], value) is None:
        raise ReviewError(f"Invalid {kind} identity")
    return value


def placement_parameters(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"primary_node_id", "secondary_node_ids"}:
        raise ReviewError("Placement requires explicit primary and secondary destinations")
    primary = identifier(value["primary_node_id"], "node")
    if primary.startswith("collection_"):
        raise ReviewError("Primary placement must be an Area or Project")
    secondary = value["secondary_node_ids"]
    if (
        not isinstance(secondary, list)
        or len(secondary) > MAX_SECONDARY
        or len(set(identifier(item, "node") for item in secondary)) != len(secondary)
        or primary in secondary
    ):
        raise ReviewError("Invalid secondary destinations")
    return {"primary_node_id": primary, "secondary_node_ids": sorted(secondary)}


def selector_prefix(value: str) -> str:
    if value == "":
        return ""
    selected = relative_path(value)
    if any(char in selected for char in "*?[]"):
        raise ReviewError("Routing uses literal relative path prefixes, not patterns")
    return selected


def validate_rule(value: dict) -> None:
    fields = {
        "schema_version",
        "id",
        "revision",
        "source_id",
        "path_prefix",
        "destinations",
        "enabled",
        "automatic_enabled",
        "created_at",
        "updated_at",
        "principal",
    }
    try:
        if (
            not isinstance(value, dict)
            or set(value) != fields
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise ValueError("rule schema")
        identifier(value["id"], "rule")
        identifier(value["source_id"], "source")
        if type(value["revision"]) is not int or not 1 <= value["revision"] <= 2**31 - 1:
            raise ValueError("rule revision")
        if selector_prefix(value["path_prefix"]) != value["path_prefix"]:
            raise ValueError("selector")
        if placement_parameters(value["destinations"]) != value["destinations"]:
            raise ValueError("destinations")
        if type(value["enabled"]) is not bool or type(value["automatic_enabled"]) is not bool:
            raise ValueError("rule flags")
        if value["principal"] not in {"local_browser", "local_cli"}:
            raise ValueError("rule actor")
        if any(
            not isinstance(value[key], str) or not value[key] or len(value[key]) > 80
            for key in ("created_at", "updated_at")
        ):
            raise ValueError("rule time")
        bounded_json(value)
    except (ValueError, TypeError, KeyError) as exc:
        raise ReviewUnavailable("Retained routing rule is invalid") from exc


def validate_history(value: dict) -> None:
    fields = {
        "schema_version",
        "domain",
        "subject",
        "action",
        "request_id",
        "principal",
        "recorded_at",
        "input_revision",
        "plan_revision",
        "before",
        "after",
        "rule_id",
    }
    try:
        if (
            set(value) != fields
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise ValueError("history schema")
        domain, action = value["domain"], value["action"]
        if (domain, action) not in {
            ("placement", "classify"),
            ("routing", "save_rule"),
            ("routing", "revoke_rule"),
            ("routing", "apply_rule"),
        }:
            raise ValueError("history domain")
        identifier(
            value["subject"], "rule" if action in {"save_rule", "revoke_rule"} else "document"
        )
        revision(value["input_revision"])
        revision(value["plan_revision"])
        if value["rule_id"] is not None:
            identifier(value["rule_id"], "rule")
        request_identifier(value["request_id"])
        principal = value["principal"]
        if principal not in {"local_browser", "local_cli"} and not (
            action == "apply_rule" and principal == "rule:" + str(value["rule_id"])
        ):
            raise ValueError("history actor")
        if (
            not isinstance(value["recorded_at"], str)
            or not value["recorded_at"]
            or len(value["recorded_at"]) > 80
        ):
            raise ValueError("history time")
        if not isinstance(value["after"], dict):
            raise ValueError("history result")
        for state in (value["before"], value["after"]):
            if state is None:
                continue
            if action in {"save_rule", "revoke_rule"}:
                validate_rule(state)
                if state["id"] != value["subject"]:
                    raise ValueError("history rule subject")
            else:
                if (
                    not isinstance(state, dict)
                    or set(state)
                    != {
                        "schema_version",
                        "id",
                        "document_id",
                        "primary_node_id",
                        "secondary_node_ids",
                        "created_at",
                        "updated_at",
                    }
                    or type(state["schema_version"]) is not int
                    or state["schema_version"] != 1
                ):
                    raise ValueError("history classification")
                if state["document_id"] != value["subject"] or state["id"] != classification_id(
                    value["subject"]
                ):
                    raise ValueError("history classification subject")
                identifier(state["primary_node_id"], "node")
                if (
                    not isinstance(state["secondary_node_ids"], list)
                    or len(state["secondary_node_ids"]) > MAX_SECONDARY
                ):
                    raise ValueError("history secondary destinations")
                if any(
                    identifier(node, "node") == state["primary_node_id"]
                    for node in state["secondary_node_ids"]
                ):
                    raise ValueError("history duplicate primary")
                if len(set(state["secondary_node_ids"])) != len(state["secondary_node_ids"]):
                    raise ValueError("history duplicate secondary")
        bounded_json(value)
    except (ValueError, TypeError, KeyError) as exc:
        raise ReviewUnavailable("Retained placement/routing history is invalid") from exc


def matches(rule: dict, source_id: str, locator: str) -> bool:
    prefix = rule["path_prefix"]
    return bool(
        rule["enabled"]
        and rule["source_id"] == source_id
        and (not prefix or locator == prefix or locator.startswith(prefix + "/"))
    )
