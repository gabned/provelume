"""Closed Git failure context, without messages, paths or command arguments."""

import subprocess
from pathlib import Path


def git_failure_evidence(error):
    from .mirror_git_runtime import GitSession, tree_storage_bound

    known_sites = {
        GitSession.__init__.__code__: "session_initialization",
        GitSession.run.__code__: "session_run",
        tree_storage_bound.__code__: "storage_scan",
        Path.open.__code__: "file_open",
        Path.stat.__code__: "file_stat",
        Path.read_bytes.__code__: "file_read",
        Path.write_bytes.__code__: "file_write",
    }
    operations = {
        "--version", "init", "config", "hash-object", "cat-file", "mktree",
        "commit-tree", "rev-parse", "update-ref", "symbolic-ref", "show-ref",
        "for-each-ref", "ls-tree", "ls-remote", "fetch", "push", "write-tree",
        "read-tree", "update-index", "check-ref-format",
    }
    kinds = {
        OSError: "OSError", FileNotFoundError: "FileNotFoundError",
        PermissionError: "PermissionError", ProcessLookupError: "ProcessLookupError",
        subprocess.SubprocessError: "SubprocessError",
        subprocess.TimeoutExpired: "TimeoutExpired",
        subprocess.CalledProcessError: "CalledProcessError",
    }
    operation, sites, original = "OTHER", set(), None
    seen = set()
    for _ in range(8):
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        if original is None and isinstance(error, (OSError, subprocess.SubprocessError)):
            original = error
        frame = error.__traceback__
        for _ in range(32):
            if frame is None:
                break
            code = frame.tb_frame.f_code
            if code in known_sites:
                sites.add(known_sites[code])
            if code is GitSession.run.__code__:
                arguments = frame.tb_frame.f_locals.get("arguments")
                if (
                    type(arguments) in {list, tuple} and arguments
                    and type(arguments[0]) is str and arguments[0] in operations
                ):
                    operation = arguments[0]
            frame = frame.tb_next
        error = error.__context__
    if not sites.intersection({"session_initialization", "session_run"}):
        return None

    def number(name):
        value = getattr(original, name, None)
        return value if type(value) is int and 0 <= value <= 65535 else None

    return {
        "schema": "provelume-git-failure/v1",
        "result": "UNKNOWN",
        "operation": operation,
        "sites": sorted(sites),
        "error_type": kinds.get(type(original), "OSError" if isinstance(original, OSError)
                                else "SubprocessError" if original is not None
                                else "NO_OS_CONTEXT"),
        "errno": number("errno"),
        "winerror": number("winerror"),
        "raw_message_and_arguments": "EXCLUDED",
    }
