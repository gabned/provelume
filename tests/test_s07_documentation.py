from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_s07_adr_and_architecture_define_closed_endpoint_security_contract() -> None:
    adr = _read("docs/adr/0020-windows-shell-and-configurable-loopback-endpoint.md")
    english = _read("docs/architecture/windows-shell-and-endpoint.md")
    italian = _read("docs/architecture/windows-shell-and-endpoint.it.md")
    for document in (adr, english, italian):
        for token in (
            "44851",
            "127.0.0.1",
            "1024",
            "65535",
            "loopback",
            "CSRF",
            "revision",
            "tray",
            "0.8.0",
            "unsigned",
        ):
            assert token in document
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
        "Upgrade and uninstall",
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
    assert "does not announce or publish `0.9.0`" in guide


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
    assert "PENDING_CANDIDATE_PR" in release
    assert "#155" in release and "#155" in roadmap
    assert "release-preparation" in release
    assert "does not authorize `0.9.0` publication" in roadmap
    assert "no tag" in changelog.casefold()


def test_roadmap_does_not_offer_implicit_free_or_random_port_fallback() -> None:
    roadmap = _read("docs/roadmap.md")
    assert "setup proposes a validated free alternative" not in roadmap.casefold()
    assert "never proposes,\ndiscovers or persists a random/free alternative" in roadmap
