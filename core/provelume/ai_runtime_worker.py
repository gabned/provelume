"""Private stdio worker. No product route, network client or acquisition code."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from contextlib import ExitStack, nullcontext
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


def sealed_snapshot(stack, source, size, digest):
    """Bounded immutable Linux file, retained until worker exit; no pathname reload."""
    import fcntl

    descriptor = os.memfd_create("provelume-input", os.MFD_ALLOW_SEALING)
    snapshot = stack.enter_context(os.fdopen(descriptor, "w+b"))
    source.seek(0)
    count, observed = 0, hashlib.sha256()
    while block := source.read(1024 * 1024):
        count += len(block)
        check(count <= size, "limit")
        snapshot.write(block)
        observed.update(block)
    check(count == size and observed.hexdigest() == digest, "integrity")
    snapshot.flush()
    fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS,
                fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
    return f"/proc/self/fd/{descriptor}"


def pinned_input(stack, path):
    # Windows must retain deny-write/delete handles. Linux retains only the sealed
    # snapshot after copying; retaining every ancestor for every library exhausted
    # the fixed 64-descriptor ceiling on ordinary deep CI paths.
    return (nullcontext(stack.enter_context(open_local_file(path)))
            if os.name == "nt" else open_local_file(path))


def main(*, containment=None, inherited_model=False):
    started = time.monotonic()
    phase = "initialization"
    try:
        initial = read()
        check(set(initial) == {"runtime", "model_handle" if inherited_model else "model"}, "state")
        job, limits = containment if containment is not None else contain()
        phase = "model_verification"
        entry = ModelRegistry.packaged().entry(MODEL_ID)
        with ExitStack() as stack:
            model_stream = None
            if inherited_model:
                import msvcrt

                from .ai_windows_api import libraries

                handle = initial["model_handle"]
                kernel, _, _, _ = libraries()
                check(type(handle) is int and 0 < handle < 2**64
                      and kernel.GetFileType(handle) == 1, "unsafe_path")
                source = stack.enter_context(os.fdopen(msvcrt.open_osfhandle(
                    handle, os.O_BINARY | os.O_RDONLY), "rb"))
                verify_stream(source, entry)
                model_stream, model_path = source, None
            else:
                with pinned_input(stack, initial["model"]) as source:
                    verify_stream(source, entry)
                    model_path = initial["model"]
                    phase = "model_snapshot"
                    if os.name != "nt":
                        model_path = sealed_snapshot(
                            stack, source, entry.model_size, entry.model_sha256)
            directory = Path(initial["runtime"])
            if inherited_model:
                check(directory == Path(sys._MEIPASS) / "provelume/native-ai/windows",
                      "unsafe_path")
            system = "windows" if os.name == "nt" else "linux"
            inventory = runtime_lock()["platforms"][system]
            library_paths = {}
            phase = "runtime_verification"
            check({p.name for p in directory.iterdir()} == set(inventory), "untrusted")
            for name, expected in inventory.items():
                # The broker pins every public ancestor and byte for this lifetime.
                # The capability-free child must not list private user ancestors.
                access = ((directory / name).open("rb") if inherited_model
                          else pinned_input(stack, directory / name))
                with access as stream:
                    check(os.fstat(stream.fileno()).st_nlink == 1, "unsafe_path")
                    check(
                        os.fstat(stream.fileno()).st_size == expected["size"]
                        and hashlib.file_digest(stream, "sha256").hexdigest() == expected["sha256"],
                        "integrity",
                    )
                    library_paths[name] = (directory / name if os.name == "nt" else
                        sealed_snapshot(stack, stream, expected["size"], expected["sha256"]))
            # Keep job handle and deny-write model/library descriptors alive.
            check(job is not False, "state")
            from .ai_llama import Llama

            phase = "native_load"
            engine = Llama(directory, model_path, library_paths, model_stream=model_stream)
            stack.callback(engine.close)
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
                phase = "idle"
                request = read()
                if request == {"operation": "unload"}:
                    engine.close()
                    emit({"event": "unloaded", "memory": memory_observation()})
                    return
                check({"prompt", "request"} <= set(request)
                      and set(request) <= {"prompt", "request", "scope", "response_format"}
                      and type(request["prompt"]) is str, "state")
                request_id = request["request"]
                check(type(request_id) is str and len(request_id) == 32
                      and all(ch in "0123456789abcdef" for ch in request_id), "state")
                check(0 < len(request["prompt"].encode("utf-8")) <= 4096, "limit")
                phase = "generation"

                def observe(value, request_id=request_id):
                    if value["event"] == "prefill":
                        value = {**value, "request": request_id, "pid": os.getpid()}
                    emit(value)

                result = engine.generate(request["prompt"], observe, scope=request.get("scope"),
                                         response_format=request.get("response_format"))
                result["memory"] = memory_observation()
                emit(result)
    except Exception as exc:
        emit({"event": "error", "code": exc.code if isinstance(exc, ModelError) else "state",
              "phase": phase, "failure_type": type(exc).__name__})
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
