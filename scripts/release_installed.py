"""Check installed AI evidence against the exact release-pipeline installer offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CHECKS = {
    "installed_exact_source", "ordinary_network_denial",
    "ordinary_download_revoke_cancel_verify_remove", "ordinary_offline_import",
    "ordinary_self_test", "external_appcontainer_token_observation",
    "ordinary_activation", "ordinary_guided_enablement",
    "ordinary_document_synthesis_32_cases", "kill_on_parent_death",
    "ordinary_installed_restart_off_without_replay", "restart_session_off",
}


def installer_identity(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("installer_identity")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"name": path.name, "sha256": digest, "size_bytes": path.stat().st_size}


def build_identity(identity: dict, *, version: str, commit: str, channel: str) -> dict:
    if channel not in {"development", "preview", "stable"}:
        raise ValueError("installed_identity")
    official = channel != "development"
    expected = {
        "version": version, "commit": commit, "channel": channel,
        "source_repository": "gabned/provelume",
        "tag": f"v{version}" if official else None,
        "official_build_metadata": official,
        "build_identity_status": "official_metadata_present" if official else "development_build",
    }
    about = identity.get("about") or {}
    if identity.get("frozen") is not True or any(
        about.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("installed_identity")
    return expected


def verify(report: dict, installer: Path, corpus: Path, *, version: str,
           commit: str, channel: str) -> None:
    if (report.get("schema_version") != 1 or report.get("status") != "PASS"
            or report.get("phase") != "completed" or report.get("source_commit") != commit
            or report.get("checks") != dict.fromkeys(CHECKS, "PASS")):
        raise ValueError("installed_qualification")
    if report.get("installer") != installer_identity(installer):
        raise ValueError("installer_identity")
    if installer.name != f"Provelume-Setup-{version}-x64.exe":
        raise ValueError("installer_identity")
    build_identity({"frozen": True, "about": report.get("installed_build")},
                   version=version, commit=commit, channel=channel)
    expected = json.loads(corpus.read_text(encoding="utf-8"))
    rows = report.get("synthesis", [])
    if len(expected) != 32 or [row.get("case") for row in rows] != [c["id"] for c in expected]:
        raise ValueError("installed_corpus")
    if not all(row.get("status") == "succeeded" and row.get("valid") is True
               and row.get("gold") is True and row.get("attempts") == 1 for row in rows):
        raise ValueError("installed_synthesis")
    if (report.get("private_content_logged") is not False
            or report.get("model_weights_in_artifact") is not False):
        raise ValueError("installed_evidence_boundary")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "installer", "corpus"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("version", "commit", "channel"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    verify(json.loads(args.report.read_text(encoding="utf-8")), args.installer, args.corpus,
           version=args.version, commit=args.commit, channel=args.channel)
    print("Installed AI qualification matches the exact installer and source identity.")


if __name__ == "__main__":
    main()
