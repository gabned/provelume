from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import uvicorn

from .service import ProvelumeInstance
from .web import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="provelume", description="Run a local Provelume Instance")
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
