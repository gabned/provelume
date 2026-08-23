#!/usr/bin/env python3
"""Verify installed Provelume Core files without network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from provelume.installation_verification import (
    verify_installed_distribution,
    verify_record_installation,
)

EXIT_CODES = {
    "verified": 0,
    "modified": 1,
    "unavailable": 2,
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--distribution", default="provelume")
    value.add_argument("--expected-version")
    value.add_argument(
        "--release-bundle",
        type=Path,
        help="Optional offline-verified release bundle for wheel byte comparison",
    )
    value.add_argument(
        "--root",
        type=Path,
        help="Advanced: explicit site-packages root for verification",
    )
    value.add_argument(
        "--record",
        type=Path,
        help="Advanced: explicit installed .dist-info/RECORD path",
    )
    value.add_argument("--json", action="store_true")
    return value


def _plain_output(payload: dict[str, object]) -> str:
    lines = [
        f"Status: {str(payload['status']).upper()}",
        f"Distribution: {payload['distribution']}",
    ]
    if payload.get("version"):
        lines.append(f"Installed version: {payload['version']}")
    if payload.get("installation_root"):
        lines.append(f"Installation root: {payload['installation_root']}")
    lines.append(f"Checked files: {payload['checked_files']}")
    lines.append(f"Core files: {payload['core_files']}")
    lines.append(f"Release wheel: {payload['release_wheel_status']}")
    if payload.get("matched_release_wheel"):
        lines.append(f"Matched artifact: {payload['matched_release_wheel']}")
    lines.append("Findings:")
    findings = payload.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            location = f" [{finding['path']}]" if finding.get("path") else ""
            lines.append(
                f"- {str(finding['severity']).upper()} {finding['code']}{location}: "
                f"{finding['message']}"
            )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if (arguments.root is None) != (arguments.record is None):
        parser().error("--root and --record must be supplied together")

    if arguments.root is not None and arguments.record is not None:
        result = verify_record_installation(
            arguments.root,
            arguments.record,
            distribution_name=arguments.distribution,
            expected_version=arguments.expected_version,
            release_bundle=arguments.release_bundle,
        )
    else:
        result = verify_installed_distribution(
            arguments.distribution,
            expected_version=arguments.expected_version,
            release_bundle=arguments.release_bundle,
        )

    payload = result.as_dict()
    if arguments.json:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(_plain_output(payload))
    return EXIT_CODES[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
