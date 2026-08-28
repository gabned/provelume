from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from . import __version__
from .about import current_about
from .build_info import current_build_info
from .ingest import DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_FILES, IngestionRetryError
from .installation import verify_current_installation
from .service import ProvelumeInstance
from .updates import UpdateError, check_for_updates
from .web import create_app


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="provelume", description="Run a local Provelume Instance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "build-info",
        help="Print embedded build identity without making a network request",
    )
    subparsers.add_parser(
        "about",
        help="Print installed product, runtime and update capability information offline",
    )

    check_updates = subparsers.add_parser(
        "check-updates",
        help="Explicitly contact GitHub Releases and check for a newer version",
    )
    check_updates.add_argument(
        "--channel",
        choices=("stable", "preview"),
        default="preview",
    )

    init = subparsers.add_parser("init", help="Initialize an Instance directory")
    init.add_argument("instance", type=Path)
    init.add_argument("--name", default="Provelume Instance")

    ingest = subparsers.add_parser("ingest", help="Ingest a local file or directory")
    ingest.add_argument("instance", type=Path)
    ingest.add_argument("source", type=Path)
    ingest.add_argument("--name", dest="source_name")
    ingest.add_argument(
        "--max-file-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_FILE_BYTES,
    )
    ingest.add_argument("--max-files", type=_positive_int, default=DEFAULT_MAX_FILES)

    runs = subparsers.add_parser(
        "ingestion-runs",
        help="List durable local ingestion runs without reading source files",
    )
    runs.add_argument("instance", type=Path)
    runs.add_argument("--limit", type=_positive_int, default=50)

    run = subparsers.add_parser(
        "ingestion-run",
        help="Show one durable ingestion run and its item results",
    )
    run.add_argument("instance", type=Path)
    run.add_argument("run_id")

    retry = subparsers.add_parser(
        "retry-ingestion",
        help="Retry only failed or interrupted items from one ingestion run",
    )
    retry.add_argument("instance", type=Path)
    retry.add_argument("run_id")

    rebuild = subparsers.add_parser("rebuild-index", help="Rebuild derived local search state")
    rebuild.add_argument("instance", type=Path)

    health = subparsers.add_parser("health", help="Print knowledge health")
    health.add_argument("instance", type=Path)

    network_status = subparsers.add_parser(
        "network-status",
        help="Describe configured network capability without making a network request",
    )
    network_status.add_argument("instance", type=Path)

    serve = subparsers.add_parser("serve", help="Run Knowledge API and browser")
    serve.add_argument("instance", type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    serve.add_argument(
        "--release-bundle",
        type=Path,
        help=(
            "optional trusted local release bundle verified once when the server starts"
        ),
    )
    serve.add_argument(
        "--expected-manifest-sha256",
        help=(
            "optional release-manifest SHA-256 obtained through a separate channel"
        ),
    )

    verify_installation = subparsers.add_parser(
        "verify-installation",
        help="verify installed Provelume package files without network access",
    )
    verify_installation.add_argument(
        "--release-bundle",
        type=Path,
        help="optional path to a local Provelume release bundle",
    )
    verify_installation.add_argument(
        "--expected-manifest-sha256",
        help="optional release-manifest SHA-256 obtained through a separate channel",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify-installation":
        if args.release_bundle is None and args.expected_manifest_sha256 is None:
            result = verify_current_installation()
        else:
            result = verify_current_installation(
                release_bundle=args.release_bundle,
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        if result.get("status") == "package_integrity_verified":
            return 0
        if result.get("status") == "modified_installation":
            return 2
        return 3

    if args.command == "build-info":
        print(json.dumps(current_build_info(), indent=2, sort_keys=True))
        return 0
    if args.command == "about":
        print(json.dumps(current_about(), indent=2, sort_keys=True))
        return 0
    if args.command == "check-updates":
        try:
            result = check_for_updates(
                current_version=__version__,
                channel=args.channel,
            )
        except UpdateError as exc:
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "error",
                        "current_version": __version__,
                        "channel": args.channel,
                        "network_attempted": True,
                        "instance_content_sent": False,
                        "error": str(exc),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 4
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "init":
        instance = ProvelumeInstance.initialise(args.instance, name=args.name)
        print(instance.root)
        return 0
    if args.command == "ingest":
        instance = ProvelumeInstance(args.instance)
        try:
            result = instance.ingest_run(
                args.source,
                source_name=args.source_name,
                max_file_bytes=args.max_file_bytes,
                max_files=args.max_files,
            )
        except (OSError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result["run"]["status"] == "completed" else 2
    if args.command == "ingestion-runs":
        instance = ProvelumeInstance(args.instance)
        print(json.dumps(instance.list_ingestion_runs(limit=args.limit), indent=2))
        return 0
    if args.command == "ingestion-run":
        instance = ProvelumeInstance(args.instance)
        result = instance.get_ingestion_run(args.run_id)
        if result is None:
            print(
                json.dumps(
                    {"status": "not_found", "run_id": args.run_id},
                    indent=2,
                )
            )
            return 3
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "retry-ingestion":
        instance = ProvelumeInstance(args.instance)
        try:
            result = instance.retry_ingestion(args.run_id)
        except IngestionRetryError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
            return 3
        print(json.dumps(result, indent=2))
        return 0 if result["run"]["status"] == "completed" else 2
    if args.command == "rebuild-index":
        instance = ProvelumeInstance(args.instance)
        print(json.dumps({"documents_indexed": instance.rebuild_index()}))
        return 0
    if args.command == "health":
        instance = ProvelumeInstance(args.instance)
        print(json.dumps(instance.knowledge_health(), indent=2))
        return 0
    if args.command == "network-status":
        instance = ProvelumeInstance(args.instance)
        print(json.dumps(instance.network_status(), indent=2, sort_keys=True))
        return 0
    if args.command == "serve":
        app = create_app(
            args.instance,
            release_bundle=args.release_bundle,
            expected_manifest_sha256=args.expected_manifest_sha256,
        )
        uvicorn.run(app, host=args.host, port=args.port)
        return 0
    raise RuntimeError(f"unsupported command: {args.command}")
