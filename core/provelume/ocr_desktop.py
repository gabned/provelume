"""Explicit frozen OCR operator entry: bounded JSON result, no GUI/server dispatch."""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from .ocr_cli import add_ocr_commands, handle_ocr_command
from .ocr_kit import OcrKitError, _safe, active_kit, host_root, import_kit, remove_kit
from .publication import PublicationError


def run_ocr_command(arguments: list[str], result_file: Path) -> int:
    parser = argparse.ArgumentParser(prog="Provelume --ocr-command")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("kit-import")
    install.add_argument("archive", type=Path)
    install.add_argument("--receipt", type=Path)
    install.add_argument("--development", action="store_true")
    install.add_argument("--expected-sha256")
    commands.add_parser("kit-status")
    commands.add_parser("kit-remove")
    add_ocr_commands(commands)
    try:
        options = parser.parse_args(arguments)
        destination = _safe(result_file)
        if destination.is_relative_to(_safe(host_root())):
            return 2
        if hasattr(options, "instance") and destination.is_relative_to(_safe(options.instance)):
            return 2
        # The output must be available before any operation changes state.
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            try:
                if options.command == "kit-import":
                    result = import_kit(
                        options.archive,
                        receipt_path=options.receipt,
                        expected_sha256=options.expected_sha256,
                        development=options.development,
                    )
                elif options.command == "kit-remove":
                    result = remove_kit()
                elif options.command == "kit-status":
                    kit = active_kit()
                    manifest = kit.verify()
                    result = {
                        "status": "present-verified",
                        "sha256": kit.sha256,
                        "commit": manifest["commit"],
                        "network_used": False,
                        "ocr_enablement_changed": False,
                    }
                else:
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = handle_ocr_command(options)
                    stream.write(output.getvalue())
                    return code if code in (0, 2) else 2
                json.dump(result, stream, sort_keys=True)
                stream.write("\n")
                return 0
            except (OSError, ValueError, KeyError, TypeError, OcrKitError, PublicationError) as exc:
                json.dump(
                    {
                        "status": "unavailable",
                        "code": getattr(exc, "code", "invalid_kit"),
                        "network_used": False,
                    },
                    stream,
                )
                stream.write("\n")
                return 2
    except (OSError, ValueError, OcrKitError):
        return 2
