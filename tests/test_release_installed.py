from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release_installed import CHECKS, build_identity, installer_identity, verify

COMMIT = "a" * 40
CORPUS = Path("tests/fixtures/ai_synthesis_quality.json")


@pytest.fixture
def evidence(tmp_path: Path) -> tuple[dict, Path]:
    installer = tmp_path / "Provelume-Setup-0.12.0-x64.exe"
    installer.write_bytes(b"synthetic installer")
    about = {
        "version": "0.12.0", "commit": COMMIT, "channel": "preview",
        "source_repository": "gabned/provelume", "tag": "v0.12.0",
        "official_build_metadata": True, "build_identity_status": "official_metadata_present",
    }
    return {
        "schema_version": 1, "status": "PASS", "phase": "completed", "source_commit": COMMIT,
        "checks": dict.fromkeys(CHECKS, "PASS"), "installer": installer_identity(installer),
        "installed_build": about, "private_content_logged": False,
        "model_weights_in_artifact": False,
        "synthesis": [{"case": c["id"], "status": "succeeded", "valid": True,
                       "gold": True, "attempts": 1} for c in json.loads(CORPUS.read_text())],
    }, installer


def check(report: dict, installer: Path) -> None:
    verify(report, installer, CORPUS, version="0.12.0", commit=COMMIT, channel="preview")


def test_same_installer_and_complete_official_identity(evidence) -> None:
    check(*evidence)


def test_changed_installer_cannot_reuse_report(evidence) -> None:
    report, installer = evidence
    installer.write_bytes(b"different installer")
    with pytest.raises(ValueError, match="installer_identity"):
        check(report, installer)


@pytest.mark.parametrize("mutation", ["version", "commit", "channel", "tag",
                                      "official_build_metadata", "build_identity_status"])
def test_mixed_identity_cannot_qualify_official_installer(evidence, mutation) -> None:
    report, installer = evidence
    report["installed_build"][mutation] = "development"
    with pytest.raises(ValueError, match="installed_identity"):
        check(report, installer)


@pytest.mark.parametrize("mutation", ["failed", "missing_check", "missing_case",
                                      "reordered_cases", "retry", "invalid"])
def test_partial_failed_or_retried_evidence_is_rejected(evidence, mutation) -> None:
    report, installer = evidence
    if mutation == "failed":
        report["status"] = "FAIL"
    elif mutation == "missing_check":
        report["checks"].pop("ordinary_self_test")
    elif mutation == "missing_case":
        report["synthesis"].pop()
    elif mutation == "reordered_cases":
        report["synthesis"].reverse()
    elif mutation == "retry":
        report["synthesis"][0]["attempts"] = 2
    else:
        report["synthesis"][0]["valid"] = False
    with pytest.raises(ValueError):
        check(report, installer)


def test_development_is_valid_only_as_development(evidence) -> None:
    about = evidence[0]["installed_build"]
    about.update(channel="development", tag=None, official_build_metadata=False,
                 build_identity_status="development_build")
    build_identity({"frozen": True, "about": about}, version="0.12.0", commit=COMMIT,
                   channel="development")
    with pytest.raises(ValueError, match="installed_identity"):
        build_identity({"frozen": True, "about": about}, version="0.12.0", commit=COMMIT,
                       channel="preview")
