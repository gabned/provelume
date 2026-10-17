"""Explicit frozen-runtime access to the existing six Instance operator commands."""

from __future__ import annotations

import argparse
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from .instance_cli import add_instance_lifecycle_commands, handle_instance_lifecycle_command


def run_instance_command(arguments: list[str], result_file: Path) -> int:
    """No GUI/server or shell dispatch; report creation must succeed before mutation."""
    parser = argparse.ArgumentParser(prog="Provelume --instance-command")
    add_instance_lifecycle_commands(parser.add_subparsers(dest="command", required=True))
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(io.StringIO()):
        try:
            options = parser.parse_args(arguments)
        except SystemExit:
            return 2
    try:
        if result_file.is_symlink() or result_file.is_junction():
            return 2
        instance = options.instance.expanduser().resolve()
        destination = result_file.expanduser().resolve()
    except (OSError, ValueError):
        return 2
    if destination == instance or destination.is_relative_to(instance):
        return 2
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        return 2
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            with redirect_stdout(output):
                try:
                    code = handle_instance_lifecycle_command(options)
                except Exception as exc:
                    # An unexpected failure is never success or an automatic retry.
                    # The native lifecycle retains its backup/journal evidence.
                    output = io.StringIO(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "status": "error",
                                "error_type": type(exc).__name__,
                            }
                        )
                    )
                    code = 2
            payload = output.getvalue()
            json.loads(payload)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return code if code in (0, 2) else 2
    except (OSError, ValueError):
        return 2
