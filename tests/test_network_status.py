from __future__ import annotations

import copy
import json

from provelume.network_status import declared_network_status


def test_default_filesystem_instance_is_local_only_and_redacts_paths() -> None:
    config = {
        "schema_version": 1,
        "network": {"external_access": False, "update_checks": False},
        "sources": {
            "private-files": {
                "kind": "filesystem",
                "name": "Private files",
                "path": "/srv/private/never-return-this",
            }
        },
    }
    original = copy.deepcopy(config)

    result = declared_network_status(config)

    assert result["schema_version"] == 1
    assert result["status"] == "local_only"
    assert result["policy"] == {"external_access": False, "effective": "local_only"}
    assert result["summary"] == {
        "configured_components": 2,
        "enabled_external_components": 0,
        "enabled_unknown_components": 0,
        "conflicts": 0,
    }
    assert result["observed_activity"]["status"] == "not_instrumented"
    assert result["network_used"] is False
    assert result["components"][1]["network_capability"] == "local_only"
    assert result["components"][1]["endpoint"] is None
    assert "/srv/private" not in json.dumps(result)
    assert config == original


def test_enabled_update_check_reports_only_safe_declared_origin() -> None:
    result = declared_network_status(
        {
            "network": {
                "external_access": True,
                "update_checks": True,
                "update_endpoint": "https://updates.example.test/releases?token=private#latest",
                "update_data_categories": ["runtime.version", "release_channel"],
            }
        }
    )

    assert result["status"] == "external_access_allowed"
    assert result["summary"]["enabled_external_components"] == 1
    assert result["conflicts"] == []
    update = result["components"][0]
    assert update["endpoint"] == "https://updates.example.test"
    assert update["data_categories"] == ["runtime.version", "release_channel"]
    assert "private" not in json.dumps(result)


def test_enabled_update_check_fails_visibly_without_endpoint_or_policy() -> None:
    result = declared_network_status(
        {"network": {"external_access": False, "update_checks": True}}
    )

    assert result["status"] == "attention"
    assert {item["code"] for item in result["conflicts"]} == {
        "missing_external_endpoint",
        "external_component_blocked_by_policy",
    }


def test_unknown_provider_is_undeclared_not_silently_local() -> None:
    result = declared_network_status(
        {
            "network": {"external_access": True, "update_checks": False},
            "providers": {
                "assistant": {
                    "kind": "future-ai",
                    "enabled": True,
                    "endpoint": "https://provider.example.test/v1",
                    "data_categories": ["document.text"],
                }
            },
        }
    )

    provider = next(item for item in result["components"] if item["id"] == "provider.assistant")
    assert provider["network_capability"] == "unknown"
    assert provider["declaration_state"] == "undeclared"
    assert provider["endpoint"] == "https://provider.example.test"
    assert result["summary"]["enabled_unknown_components"] == 1
    assert result["conflicts"][0]["code"] == "undeclared_component_type"
    assert result["status"] == "attention"


def test_invalid_or_credential_bearing_endpoint_is_not_exposed() -> None:
    result = declared_network_status(
        {
            "network": {
                "external_access": True,
                "update_checks": True,
                "update_endpoint": "https://user:secret@updates.example.test/releases",
            }
        }
    )

    update = result["components"][0]
    assert update["endpoint"] is None
    assert "secret" not in json.dumps(result)
    assert {item["code"] for item in result["conflicts"]} == {
        "invalid_external_endpoint",
        "missing_external_endpoint",
    }
