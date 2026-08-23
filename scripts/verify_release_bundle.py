#!/usr/bin/env python3
"""Verify a Provelume release bundle without network access or GitHub."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from provelume.release_verification import SOURCE_REPOSITORY, verify_release_bundle

EXIT_CODES = {
    "verified": 0,
    "modified": 1,
    "unavailable": 2,
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("bundle", type=Path, help="Directory containing release assets")
    value.add_argument(
        "--expected-repository",
        default=SOURCE_REPOSITORY,
        help="Canonical source repository recorded in the release manifest",
    )
    value.add_argument(
        "--json",
        action="store_true",
        help="Write the stable machine-readable verification result",
    )
    return value


def _plain_output(payload: dict[str, object]) -> str:
    lines = [
        f"Status: {str(payload['status']).upper()}",
        f"Bundle: {payload['bundle']}",
    ]
    if payload.get("version"):
        lines.append(f"Version: {payload['version']} ({payload.get('tag')})")
    if payload.get("commit"):
        lines.append(f"Source: {payload.get('source_repository')}@{payload['commit']}")
    lines.append(
        "Deterministic Python distributions: "
        + str(payload["deterministic_python_distributions"])
    )
    lines.append(f"Checked files: {payload['checked_files']}")
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
    result = verify_release_bundle(
        arguments.bundle,
        expected_repository=arguments.expected_repository,
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
