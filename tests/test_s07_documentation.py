from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_s07_adr_and_architecture_define_closed_endpoint_security_contract() -> None:
    adr = _read("docs/adr/0020-windows-shell-and-configurable-loopback-endpoint.md")
    english = _read("docs/architecture/windows-shell-and-endpoint.md")
    italian = _read("docs/architecture/windows-shell-and-endpoint.it.md")
    for document in (english, italian):
        for token in (
            "44851",
            "127.0.0.1",
            "1024",
            "65535",
            "loopback",
            "CSRF",
            "revision",
            "tray",
            "0.9.0",
            "unsigned",
        ):
            assert token in document
    assert "0.8.0" in adr
    assert "unsigned" in adr
    assert "random port" in english
    assert "porta casuale" in italian
    assert "firewall" in english.casefold()
    assert "firewall" in italian.casefold()
    assert "Unknown publisher" in adr
    assert "99899187383" in adr
    assert "99902830064" in adr
    assert "99906749116" in adr


def test_windows_guide_covers_install_upgrade_uninstall_transfer_and_signing_blocker() -> None:
    guide = _read("docs/windows-shell.md")
    for token in (
        "Install",
        "Upgrade, rollback and uninstall",
        "system tray",
        "set-endpoint",
        "reset-endpoint",
        "backup-shell-preferences",
        "restore-shell-preferences",
        "Unknown publisher",
        "authorized certificate",
        "valid timestamp",
        "exact SHA-256",
    ):
        assert token in guide
    assert "published with the `0.10.0 — Perceptio` preview" in guide


def test_accessibility_en_it_theme_navigation_and_inert_content_are_documented() -> None:
    accessibility = _read("docs/accessibility.md")
    architecture = _read("docs/architecture/windows-shell-and-endpoint.md")
    for token in (
        "Keyboard",
        "skip link",
        "landmarks",
        "role=alert",
        "forced colors",
        "200% zoom/reflow",
        "prefers-reduced-motion",
        "EN and IT",
        "script-like payloads inert",
    ):
        assert token in accessibility
    for group in (
        "Knowledge",
        "Operational status",
        "Configuration",
        "Maintenance",
        "Diagnostics & support",
    ):
        assert group in architecture


def test_api_privacy_packaging_and_qualification_matrix_remain_truthful() -> None:
    api = _read("docs/api.md")
    privacy = _read("docs/privacy-network.md")
    matrix = _read("docs/qualification/windows-shell-s07.md")
    release = _read("docs/releases/0.9.0.md")
    roadmap = _read("docs/roadmap.md")
    changelog = _read("CHANGELOG.md")
    assert "`GET /api/v1/shell`" in api
    assert "There is no `/api/v1/shell` POST" in api
    assert "no random port" in api
    assert "no DNS query" in privacy
    assert "never\nauthorize network access" in privacy
    assert "not a claim that a candidate or release has passed" in matrix
    assert "failure, cancellation or timeout" in matrix
    assert "PENDING_CANDIDATE_PR" not in release
    assert "#156" in release and "#156" in roadmap
    assert "#155" in release and "#155" in roadmap
    assert "release workstream #158" in release.casefold()
    assert "Release workstream" in roadmap
    assert "## 0.9.0 - 2026-09-02" in changelog


def test_published_lectio_surfaces_have_no_stale_development_identity() -> None:
    paths = (
        "docs/architecture/local-ocr-contract.md",
        "docs/architecture/local-ocr-contract.it.md",
        "docs/architecture/google-readonly-adapters.md",
        "docs/architecture/google-readonly-adapters.it.md",
        "docs/architecture/transcript-profiles.md",
        "docs/architecture/transcript-profiles.it.md",
        "docs/architecture/cross-source-qualification.md",
        "docs/architecture/cross-source-qualification.it.md",
        "docs/architecture/windows-shell-and-endpoint.md",
        "docs/architecture/windows-shell-and-endpoint.it.md",
    )
    for path in paths:
        document = _read(path)
        assert "0.9.0" in document
        assert "0.8.0" not in document
        assert "unreleased" not in document.casefold()

    readme = _read("README.md")
    for phrase in (
        "unreleased S02",
        "unreleased S03",
        "unreleased S05",
        "unreleased managed folder Source",
        "unreleased maintenance catalogue",
    ):
        assert phrase not in readme


def test_roadmap_does_not_offer_implicit_free_or_random_port_fallback() -> None:
    roadmap = _read("docs/roadmap.md")
    assert "setup proposes a validated free alternative" not in roadmap.casefold()
    assert "never proposes,\ndiscovers or persists a random/free alternative" in roadmap
