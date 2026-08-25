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

    serve = subparsers.add_parser("serve", help="Run Knowledge API and browser")
    serve.add_argument("instance", type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)

    subparsers.add_parser(
        "verify-installation",
        help="verify installed Provelume package files without network access",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify-installation":
        result = verify_current_installation()
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
    if args.command == "serve":
        uvicorn.run(create_app(args.instance), host=args.host, port=args.port)
        return 0
    raise RuntimeError(f"unsupported command: {args.command}")
