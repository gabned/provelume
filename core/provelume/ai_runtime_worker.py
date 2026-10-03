"""Private stdio worker. No product route, network client or acquisition code."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from .ai_model_file import verify_stream
from .ai_models import ModelError, ModelRegistry, check
from .ai_runtime_contract import MODEL_ID, runtime_lock
from .ai_runtime_limits import contain, memory_observation
from .maintenance_local_files import open_local_file


def emit(value):
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    check(len(raw) < 32768, "limit")
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def read():
    raw = sys.stdin.buffer.readline(32769)
    check(0 < len(raw) <= 32768 and raw.endswith(b"\n"), "limit")
    return json.loads(raw)


def main():
    started = time.monotonic()
    try:
        initial = read()
        check(set(initial) == {"runtime", "model"}, "state")
        job, limits = contain()
        entry = ModelRegistry.packaged().entry(MODEL_ID)
        with ExitStack() as stack:
            source = stack.enter_context(open_local_file(initial["model"]))
            verify_stream(source, entry)
            model_path = initial["model"]
            if os.name != "nt":
                import fcntl

                # Immutable file-backed snapshot, bounded chunks and fixed size.
                descriptor = os.memfd_create("provelume-model", os.MFD_ALLOW_SEALING)
                snapshot = stack.enter_context(os.fdopen(descriptor, "w+b"))
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    snapshot.write(block)
                snapshot.flush()
                verify_stream(snapshot, entry)
                fcntl.fcntl(
                    descriptor,
                    fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE
                    | fcntl.F_SEAL_GROW
                    | fcntl.F_SEAL_SHRINK
                    | fcntl.F_SEAL_SEAL,
                )
                model_path = f"/proc/self/fd/{descriptor}"
            directory = Path(initial["runtime"])
            system = "windows" if os.name == "nt" else "linux"
            inventory = runtime_lock()["platforms"][system]
            check({p.name for p in directory.iterdir()} == set(inventory), "untrusted")
            for name, expected in inventory.items():
                stream = stack.enter_context(open_local_file(directory / name))
                check(os.fstat(stream.fileno()).st_nlink == 1, "unsafe_path")
                check(
                    os.fstat(stream.fileno()).st_size == expected["size"]
                    and hashlib.file_digest(stream, "sha256").hexdigest() == expected["sha256"],
                    "integrity",
                )
            # Keep job handle and deny-write model/library descriptors alive.
            check(job is not False, "state")
            from .ai_llama import Llama

            engine = Llama(directory, model_path)
            emit(
                {
                    "event": "loaded",
                    "seconds": time.monotonic() - started,
                    "memory": memory_observation(),
                    "limits": limits,
                    "pid": os.getpid(),
                }
            )
            while True:
                request = read()
                if request == {"operation": "unload"}:
                    engine.close()
                    emit({"event": "unloaded", "memory": memory_observation()})
                    return
                check(set(request) == {"prompt"} and type(request["prompt"]) is str, "state")
                check(0 < len(request["prompt"].encode("utf-8")) <= 4096, "limit")
                result = engine.generate(request["prompt"], emit)
                result["memory"] = memory_observation()
                emit(result)
    except Exception as exc:
        emit({"event": "error", "code": exc.code if isinstance(exc, ModelError) else "state"})
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
