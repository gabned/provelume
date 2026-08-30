from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .ocr_contract import (
    OCR_MODES,
    OcrContractError,
    OcrUnavailableError,
)
from .scheduler_model import SchedulerError
from .service import ProvelumeInstance


def _positive_int(value: str) -> int:
    selected = int(value)
    if selected < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return selected


def add_ocr_commands(subparsers: Any) -> None:
    capability = subparsers.add_parser(
        "ocr-capability",
        help="Probe explicitly enabled local OCR components without network access",
    )
    capability.add_argument("instance", type=Path)

    configure = subparsers.add_parser(
        "ocr-configure",
        help="Configure the optional local OCR capability explicitly",
    )
    configure.add_argument("instance", type=Path)
    configure.add_argument("--mode", choices=OCR_MODES, required=True)
    configure.add_argument("--language", action="append", dest="languages")
    configure.add_argument("--engine-executable")
    configure.add_argument("--tessdata-path")
    configure.add_argument("--render-dpi", type=_positive_int)

    queue = subparsers.add_parser(
        "ocr-queue", help="Queue local OCR for one exact DocumentVersion"
    )
    queue.add_argument("instance", type=Path)
    queue.add_argument("version_id")
    queue.add_argument("--mode", choices=OCR_MODES)
    queue.add_argument("--language", action="append", dest="languages")
    queue.add_argument("--page", action="append", type=_positive_int, dest="pages")

    run = subparsers.add_parser("ocr-run", help="Execute one queued local OCR job")
    run.add_argument("instance", type=Path)
    run.add_argument("job_id")

    jobs = subparsers.add_parser("ocr-jobs", help="List durable local OCR jobs")
    jobs.add_argument("instance", type=Path)
    jobs.add_argument("--limit", type=_positive_int, default=100)

    job = subparsers.add_parser("ocr-job", help="Show one durable local OCR job")
    job.add_argument("instance", type=Path)
    job.add_argument("job_id")

    cancel = subparsers.add_parser("ocr-cancel", help="Cancel one local OCR job")
    cancel.add_argument("instance", type=Path)
    cancel.add_argument("job_id")

    bundles = subparsers.add_parser(
        "ocr-bundles", help="List verified derived OCR document bundles"
    )
    bundles.add_argument("instance", type=Path)
    bundles.add_argument("--version-id")

    remove = subparsers.add_parser(
        "ocr-remove", help="Remove OCR-derived state without changing canonical knowledge"
    )
    remove.add_argument("instance", type=Path)
    remove.add_argument("version_id")

    rebuild = subparsers.add_parser(
        "ocr-rebuild", help="Remove and requeue a prior OCR derivation"
    )
    rebuild.add_argument("instance", type=Path)
    rebuild.add_argument("version_id")


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_ocr_command(args: argparse.Namespace) -> int | None:
    if not str(args.command).startswith("ocr-"):
        return None
    try:
        instance = ProvelumeInstance(args.instance)
        if args.command == "ocr-capability":
            result = instance.ocr_capability()
        elif args.command == "ocr-configure":
            current = instance.ocr.configured_settings()
            settings = replace(
                current,
                mode=args.mode,
                languages=(
                    current.languages
                    if args.languages is None
                    else tuple(sorted(set(args.languages)))
                ),
                engine_executable=(
                    current.engine_executable
                    if args.engine_executable is None
                    else args.engine_executable
                ),
                tessdata_path=(
                    current.tessdata_path
                    if args.tessdata_path is None
                    else args.tessdata_path
                ),
                render_dpi=(
                    current.render_dpi
                    if args.render_dpi is None
                    else args.render_dpi
                ),
            )
            result = instance.configure_ocr(settings)
        elif args.command == "ocr-queue":
            result = instance.queue_ocr(
                args.version_id,
                mode=args.mode,
                languages=args.languages,
                pages=tuple(sorted(args.pages or [])),
            )
        elif args.command == "ocr-run":
            result = instance.run_ocr_job(args.job_id)
            if result is None:
                _print({"status": "not_found", "job_id": args.job_id})
                return 3
        elif args.command == "ocr-jobs":
            result = instance.list_ocr_jobs(limit=args.limit)
        elif args.command == "ocr-job":
            result = instance.get_ocr_job(args.job_id)
            if result is None:
                _print({"status": "not_found", "job_id": args.job_id})
                return 3
        elif args.command == "ocr-cancel":
            result = instance.cancel_ocr_job(args.job_id)
        elif args.command == "ocr-bundles":
            result = instance.list_ocr_bundles(args.version_id)
        elif args.command == "ocr-remove":
            result = instance.remove_ocr(args.version_id)
        elif args.command == "ocr-rebuild":
            result = instance.rebuild_ocr(args.version_id)
        else:
            return None
    except (OcrContractError, OcrUnavailableError, SchedulerError, OSError) as exc:
        code = getattr(exc, "code", "ocr_internal_error")
        _print({"status": "error", "code": code, "error": str(exc)})
        return 2
    _print(result)
    if args.command == "ocr-run" and isinstance(result, dict):
        return 0 if result.get("status") == "succeeded" else 2
    return 0


__all__ = ["add_ocr_commands", "handle_ocr_command"]
