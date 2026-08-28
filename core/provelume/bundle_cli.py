from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .bundles import (
    DEFAULT_MAX_BUNDLE_DOCUMENTS,
    BundleBuildError,
    DocumentBundleManager,
)
from .storage import InstanceStore


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def add_bundle_commands(subparsers: Any) -> None:
    build = subparsers.add_parser(
        "bundle-build",
        help="Build a deterministic Markdown bundle for one Document",
    )
    build.add_argument("instance", type=Path)
    build.add_argument("document_id")
    build.add_argument("--version-id")

    build_all = subparsers.add_parser(
        "bundle-build-all",
        help="Build current document bundles with per-document failure isolation",
    )
    build_all.add_argument("instance", type=Path)
    build_all.add_argument(
        "--max-documents",
        type=_positive_int,
        default=DEFAULT_MAX_BUNDLE_DOCUMENTS,
    )

    bundles = subparsers.add_parser(
        "bundles",
        help="List materialized document bundles",
    )
    bundles.add_argument("instance", type=Path)
    bundles.add_argument("--limit", type=_positive_int, default=100)

    bundle = subparsers.add_parser(
        "bundle",
        help="Show a bundle manifest, page map and optional Markdown",
    )
    bundle.add_argument("instance", type=Path)
    bundle.add_argument("version_id")
    bundle.add_argument("--include-markdown", action="store_true")


def handle_bundle_command(args: argparse.Namespace) -> int | None:
    if args.command not in {
        "bundle-build",
        "bundle-build-all",
        "bundles",
        "bundle",
    }:
        return None

    store = InstanceStore(args.instance)
    store.validate()
    manager = DocumentBundleManager(store)

    if args.command == "bundle-build":
        try:
            result = manager.build_document(
                args.document_id,
                version_id=args.version_id,
            )
        except BundleBuildError as exc:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    },
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["operation"]["status"] == "completed" else 2

    if args.command == "bundle-build-all":
        try:
            result = manager.build_all(max_documents=args.max_documents)
        except BundleBuildError as exc:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    },
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["operation"]["status"] == "completed" else 2

    if args.command == "bundles":
        print(json.dumps(manager.list(limit=args.limit), indent=2))
        return 0

    record = manager.get(args.version_id)
    if record is None:
        print(
            json.dumps(
                {"status": "not_found", "version_id": args.version_id},
                indent=2,
            )
        )
        return 3
    result = {
        **record,
        "page_map": manager.read_page_map(args.version_id),
    }
    if args.include_markdown:
        result["markdown"] = manager.read_markdown(args.version_id)
    print(json.dumps(result, indent=2))
    return 0
