from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dependabot_proposes_bounded_weekly_updates() -> None:
    configuration = yaml.safe_load(
        (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    )

    assert configuration["version"] == 2
    assert "registries" not in configuration
    updates = configuration["updates"]
    assert {item["package-ecosystem"] for item in updates} == {
        "pip",
        "github-actions",
    }
    for update in updates:
        assert update["directory"] == "/"
        assert update["schedule"]["interval"] == "weekly"
        assert update["schedule"]["day"] == "monday"
        assert update["schedule"]["timezone"] == "Europe/Rome"
        assert 1 <= update["open-pull-requests-limit"] <= 5


def test_security_policy_keeps_preview_and_serving_boundaries_explicit() -> None:
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "latest published preview line" in policy
    assert "single-user, local application" in policy
    assert "private vulnerability reporting" in policy
    assert "currently unsigned" in policy
    assert "does not provide account" in policy


def test_maintainability_map_preserves_deferred_ownership() -> None:
    contract = (
        ROOT / "docs" / "architecture" / "maintainability-boundaries.md"
    ).read_text(encoding="utf-8")

    assert "#84" in contract
    assert "#85" in contract
    assert "#1" in contract
    assert "None of these issues is activated" in contract
    assert "canonical JSON" in contract
