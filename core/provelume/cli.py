from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from .build_info import current_build_info
from .installation import verify_current_installation
from .service import ProvelumeInstance
from .web import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="provelume", description="Run a local Provelume Instance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "build-info",
        help="Print embedded build identity without making a network request",
    )

    init = subparsers.add_parser("init", help="Initialize an Instance directory")
    init.add_argument("instance", type=Path)
    init.add_argument("--name", default="Provelume Instance")

    ingest = subparsers.add_parser("ingest", help="Ingest a local file or directory")
    ingest.add_argument("instance", type=Path)
    ingest.add_argument("source", type=Path)
    ingest.add_argument("--name", dest="source_name")

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
    if args.command == "init":
        instance = ProvelumeInstance.initialise(args.instance, name=args.name)
        print(instance.root)
        return 0
    if args.command == "ingest":
        instance = ProvelumeInstance(args.instance)
        print(json.dumps(instance.ingest(args.source, source_name=args.source_name), indent=2))
        return 0
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
