"""Data-free acquisition receipts; never a native-inference qualification."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def origin(url):
    try:
        parsed = urlsplit(url)
        return ("https://" + parsed.hostname
                if parsed.scheme == "https" and parsed.hostname else None)
    except ValueError:
        return None


def source_identity():
    root = Path(__file__).absolute().parents[1]
    result = {}
    for key, selector in (("commit", "HEAD"), ("tree", "HEAD^{tree}")):
        value = subprocess.check_output(
            ["git", "rev-parse", "--verify", selector], cwd=root,
            stderr=subprocess.DEVNULL, timeout=5, text=True,
        ).strip()
        if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("acquisition source identity")
        result[key] = value
    return result


def save(path, resources, *, failure, source):
    run = {}
    for key, name in (("id", "GITHUB_RUN_ID"), ("attempt", "GITHUB_RUN_ATTEMPT")):
        value = os.environ.get(name, "")
        run[key] = value if value.isdecimal() and len(value) <= 20 else None
    event = os.environ.get("GITHUB_EVENT_NAME")
    run["event"] = event if event in {
        "push", "pull_request", "workflow_dispatch", "workflow_call"} else None
    record = {
        "schema": "provelume-native-acquisition/v1",
        "result": "CANCELLED" if isinstance(failure, (KeyboardInterrupt, SystemExit)) else (
            "FAIL" if failure is not None else "PASS"),
        "source": source,
        "run": run,
        "exception": type(failure).__name__ if failure is not None else None,
        "resources": resources,
        "model_or_runtime_bytes_in_receipt": False,
        "native_inference": "NOT_RUN_BY_ACQUISITION",
        "qualification_eligible": False,
        "authority": "NOT_GRANTED",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # One exclusive final receipt; no overwritten earlier attempt or raw URL,
    # signed query, header, body, credential, model or partial artifact enters it.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
