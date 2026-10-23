"""One bounded native capture of an explicitly owned Windows process; no privilege changes.

Temporary diagnostic code. A minidump retains native contexts/stack bytes, not a
symbolized or complete managed stack. WCT and dump failures remain observations.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

MAX_DUMP = 16 * 1024 * 1024
WORKER_SECONDS = 2.0


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def api(dll, name, arguments, result):
    function = getattr(ctypes.WinDLL(dll, use_last_error=True), name)
    function.argtypes, function.restype = arguments, result
    return function


def process_birth(handle):
    from ctypes import wintypes as w

    values = [w.FILETIME() for _ in range(4)]
    function = api(
        "kernel32", "GetProcessTimes", [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4, w.BOOL
    )
    if not function(handle, *(ctypes.byref(value) for value in values)):
        raise ctypes.WinError(ctypes.get_last_error())
    return (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime


def pipe_name(handle):
    from ctypes import wintypes as w

    function = api(
        "kernel32",
        "GetFileInformationByHandleEx",
        [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD],
        w.BOOL,
    )
    buffer = ctypes.create_string_buffer(8192)
    if not function(handle, 2, buffer, len(buffer)):  # FileNameInfo
        return {"available": False, "winerror": ctypes.get_last_error()}
    size = struct.unpack_from("<I", buffer.raw)[0]
    if size > len(buffer) - 4:
        return {"available": False, "reason": "NAME_CAP"}
    return {"available": True, "name": buffer.raw[4 : 4 + size].decode("utf-16-le")}


def reader_identity(thread):
    from ctypes import wintypes as w

    handle = api("kernel32", "OpenThread", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)(
        0x0800, False, thread.native_id
    )
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        values = [w.FILETIME() for _ in range(4)]
        get = api(
            "kernel32", "GetThreadTimes", [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4, w.BOOL
        )
        if not get(handle, *(ctypes.byref(v) for v in values)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {
            "tid": thread.native_id,
            "birth": (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime,
        }
    finally:
        api("kernel32", "CloseHandle", [w.HANDLE], w.BOOL)(handle)


def duplicated_pipe_names(request):
    from ctypes import wintypes as w

    close = api("kernel32", "CloseHandle", [w.HANDLE], w.BOOL)
    parent = api("kernel32", "OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)(
        0x0440, False, request["parent_pid"]
    )
    if not parent:
        raise ctypes.WinError(ctypes.get_last_error())
    rows = []
    try:
        if process_birth(parent) != request["parent_birth"]:
            raise ValueError("Parent birth mismatch")
        current = api("kernel32", "GetCurrentProcess", [], w.HANDLE)()
        duplicate = api(
            "kernel32",
            "DuplicateHandle",
            [w.HANDLE, w.HANDLE, w.HANDLE, ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD],
            w.BOOL,
        )
        for pipe in request.get("pipes", []):
            target = w.HANDLE()
            if not duplicate(parent, pipe["handle"], current, ctypes.byref(target), 0, False, 2):
                rows.append({**pipe, "available": False, "winerror": ctypes.get_last_error()})
                continue
            try:
                rows.append({**pipe, **pipe_name(target)})
            finally:
                close(target)
        return rows
    finally:
        close(parent)


def dump_inventory(path):
    """Parse retained minidump directory, native contexts/stacks and handle names."""
    raw = Path(path).read_bytes()
    if not 32 <= len(raw) <= MAX_DUMP or raw[:4] != b"MDMP":
        raise ValueError("Invalid or over-budget native minidump")
    count, directory = struct.unpack_from("<II", raw, 8)
    if count > 64 or directory + count * 12 > len(raw):
        raise ValueError("Minidump directory bounds")
    streams = {}
    for i in range(count):
        kind, size, offset = struct.unpack_from("<III", raw, directory + 12 * i)
        if kind in streams or offset + size > len(raw):
            raise ValueError("Minidump stream bounds/duplicate")
        streams[kind] = (offset, size)

    def string(offset):
        if not offset:
            return None
        size = struct.unpack_from("<I", raw, offset)[0]
        if size > 8192 or offset + 4 + size > len(raw):
            raise ValueError("Minidump string bounds")
        return raw[offset + 4 : offset + 4 + size].decode("utf-16-le")

    threads, handles = [], []
    if 3 in streams:
        offset, size = streams[3]
        n = struct.unpack_from("<I", raw, offset)[0]
        if n > 64 or 4 + n * 48 > size:
            raise ValueError("Native thread cap/bounds")
        for i in range(n):
            row = offset + 4 + i * 48
            tid = struct.unpack_from("<I", raw, row)[0]
            stack_start, stack_size, stack_rva, context_size, context_rva = struct.unpack_from(
                "<QIIII", raw, row + 24
            )
            if stack_rva + stack_size > len(raw) or context_rva + context_size > len(raw):
                raise ValueError("Native stack/context bounds")
            threads.append(
                {
                    "tid": tid,
                    "stack_start": stack_start,
                    "stack_bytes": stack_size,
                    "stack_rva": stack_rva,
                    "context_bytes": context_size,
                    "context_rva": context_rva,
                }
            )
    if 12 in streams:
        offset, size = streams[12]
        header, stride, n = struct.unpack_from("<III", raw, offset)
        if stride < 32 or n > 2048 or header + stride * n > size:
            raise ValueError("Native handle cap/bounds")
        for i in range(n):
            value, type_rva, name_rva = struct.unpack_from(
                "<QII", raw, offset + header + i * stride
            )
            handles.append({"handle": value, "type": string(type_rva), "name": string(name_rva)})
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "streams": sorted(streams),
        "threads": threads,
        "handles": handles,
        "stack_semantics": "RAW_NATIVE_CONTEXT_AND_STACK_BYTES_NOT_SYMBOLIZED_NOT_JS_STACK",
    }


def thread_ids(pid):
    from ctypes import wintypes as w

    class Entry(ctypes.Structure):
        _fields_ = [
            ("size", w.DWORD),
            ("usage", w.DWORD),
            ("tid", w.DWORD),
            ("pid", w.DWORD),
            ("base", w.LONG),
            ("delta", w.LONG),
            ("flags", w.DWORD),
        ]

    snapshot = api("kernel32", "CreateToolhelp32Snapshot", [w.DWORD, w.DWORD], w.HANDLE)(4, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    close = api("kernel32", "CloseHandle", [w.HANDLE], w.BOOL)
    first = api("kernel32", "Thread32First", [w.HANDLE, ctypes.POINTER(Entry)], w.BOOL)
    next_row = api("kernel32", "Thread32Next", [w.HANDLE, ctypes.POINTER(Entry)], w.BOOL)
    found = []
    try:
        row = Entry()
        row.size = ctypes.sizeof(row)
        okay = first(snapshot, ctypes.byref(row))
        scanned = 0
        while okay and scanned < 4096:
            scanned += 1
            if row.pid == pid:
                found.append(row.tid)
                if len(found) > 64:
                    raise RuntimeError("Owned thread cap")
            okay = next_row(snapshot, ctypes.byref(row))
        code = ctypes.get_last_error()
        return {
            "tids": found,
            "scanned_rows": scanned,
            "complete": not okay and code == 18,
            "last_error": code,
        }
    finally:
        close(snapshot)


def wait_chain(tid, expected_pid, expected_birth=None):
    from ctypes import wintypes as w

    class Lock(ctypes.Structure):
        _fields_ = [("name", w.WCHAR * 128), ("timeout", ctypes.c_longlong), ("alertable", w.BOOL)]

    class Thread(ctypes.Structure):
        _fields_ = [("pid", w.DWORD), ("tid", w.DWORD), ("wait_ms", w.DWORD), ("switches", w.DWORD)]

    class Value(ctypes.Union):
        _fields_ = [("lock", Lock), ("thread", Thread)]

    class Node(ctypes.Structure):
        _fields_ = [("kind", ctypes.c_int), ("status", ctypes.c_int), ("value", Value)]

    open_thread = api("kernel32", "OpenThread", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
    close = api("kernel32", "CloseHandle", [w.HANDLE], w.BOOL)
    handle = open_thread(0x0800, False, tid)
    record = {"tid": tid, "expected_pid": expected_pid, "available": False}
    if not handle:
        return {**record, "winerror": ctypes.get_last_error()}
    session = None
    try:
        owner = api("kernel32", "GetProcessIdOfThread", [w.HANDLE], w.DWORD)(handle)
        times = [w.FILETIME() for _ in range(4)]
        get_times = api(
            "kernel32", "GetThreadTimes", [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4, w.BOOL
        )
        if not get_times(handle, *(ctypes.byref(value) for value in times)):
            return {**record, "winerror": ctypes.get_last_error()}
        birth = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        record.update(owner_pid=owner, birth=birth, expected_birth=expected_birth)
        if owner != expected_pid or expected_birth is not None and birth != expected_birth:
            return {**record, "reason": "THREAD_IDENTITY_MISMATCH"}
        session = api(
            "advapi32", "OpenThreadWaitChainSession", [w.DWORD, ctypes.c_void_p], w.HANDLE
        )(0, None)
        if not session:
            return {**record, "winerror": ctypes.get_last_error()}
        count, cycle, nodes = w.DWORD(16), w.BOOL(), (Node * 16)()
        get = api(
            "advapi32",
            "GetThreadWaitChain",
            [
                w.HANDLE,
                ctypes.c_size_t,
                w.DWORD,
                w.DWORD,
                ctypes.POINTER(w.DWORD),
                ctypes.POINTER(Node),
                ctypes.POINTER(w.BOOL),
            ],
            w.BOOL,
        )
        # Out-of-process traversal; no COM/network callbacks or privilege enabling.
        if not get(session, 0, 1, tid, ctypes.byref(count), nodes, ctypes.byref(cycle)):
            return {**record, "winerror": ctypes.get_last_error()}
        if count.value > 16:
            return {**record, "reason": "WAIT_NODE_CAP", "count": count.value}
        rows = []
        for node in nodes[: count.value]:
            row = {"kind": node.kind, "status": node.status}
            if node.kind == 8:
                row.update(
                    pid=node.value.thread.pid,
                    tid=node.value.thread.tid,
                    wait_ms=node.value.thread.wait_ms,
                    switches=node.value.thread.switches,
                )
            else:
                row["object_name"] = node.value.lock.name
            rows.append(row)
        return {**record, "available": True, "cycle": bool(cycle.value), "nodes": rows}
    finally:
        if session:
            api("advapi32", "CloseThreadWaitChainSession", [w.HANDLE], None)(session)
        close(handle)


def capture(request, output):
    import msvcrt
    from ctypes import wintypes as w

    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    record = {
        "request": request,
        "pid": os.getpid(),
        "errors": [],
        "schema": "reader415-native-capture/v1",
        "privilege_adjustment_calls": 0,
        "started_perf_ns": wall,
        "qualification": "NOT_GRANTED",
    }
    handle = None
    snapshot = ctypes.c_void_p()
    try:
        handle = api("kernel32", "OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)(
            0x04D0, False, request["pid"]
        )
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        birth = process_birth(handle)
        record["actual_birth"] = birth
        if birth != request["birth"]:
            raise ValueError("Owned process birth mismatch")
        record["parent_pipes"] = duplicated_pipe_names(request)
        census = thread_ids(request["pid"])
        record["owned_thread_census"] = census
        record["wait_chains"] = [wait_chain(tid, request["pid"]) for tid in census["tids"]]
        record["reader_wait_chains"] = [
            wait_chain(r["tid"], request["parent_pid"], r["birth"])
            for r in request.get("readers", [])
        ]
        function = api(
            "dbghelp",
            "MiniDumpWriteDump",
            [
                w.HANDLE,
                w.DWORD,
                w.HANDLE,
                w.DWORD,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ],
            w.BOOL,
        )
        snapshot_function = api(
            "kernel32",
            "PssCaptureSnapshot",
            [w.HANDLE, w.DWORD, w.DWORD, ctypes.POINTER(w.HANDLE)],
            w.DWORD,
        )
        # VA clone plus handles/names/basic/type and threads/contexts. No breakaway flags.
        code = snapshot_function(handle, 0x1BD, 0x10001F, ctypes.byref(snapshot))
        record["snapshot"] = {
            "error_code": code,
            "flags": 0x1BD,
            "context_flags": 0x10001F,
            "live_dump_fallback": False,
        }
        if code:
            raise ctypes.WinError(code)

        class CallbackHeader(ctypes.Structure):
            _pack_ = 4
            _fields_ = [("pid", w.DWORD), ("process", w.HANDLE), ("kind", w.DWORD)]

        callback_type = ctypes.WINFUNCTYPE(
            w.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )
        record["snapshot_callback_seen"] = False

        def callback(parameter, incoming, outgoing):
            header = ctypes.cast(incoming, ctypes.POINTER(CallbackHeader)).contents
            if header.kind == 16:  # IsProcessSnapshotCallback
                ctypes.cast(outgoing, ctypes.POINTER(w.LONG)).contents.value = 1  # S_FALSE
                record["snapshot_callback_seen"] = True
            return True

        callback_ref = callback_type(callback)

        class CallbackInfo(ctypes.Structure):
            _fields_ = [("routine", callback_type), ("parameter", ctypes.c_void_p)]

        callback_info = CallbackInfo(callback_ref, None)
        with (output / "native.dmp").open("xb") as stream:
            okay = function(
                snapshot,
                request["pid"],
                msvcrt.get_osfhandle(stream.fileno()),
                0x1004,
                None,
                None,
                ctypes.byref(callback_info),
            )  # HandleData + ThreadInfo; no full heap/token.
            record["dump_call"] = {
                "okay": bool(okay),
                "winerror": None if okay else ctypes.get_last_error(),
            }
        if okay and not record["snapshot_callback_seen"]:
            raise RuntimeError("Snapshot identity callback absent; no live fallback")
        if okay:
            record["dump"] = dump_inventory(output / "native.dmp")
    except Exception as exc:
        record["errors"].append({"type": type(exc).__name__, "message": str(exc)})
    finally:
        if snapshot.value:
            current = api("kernel32", "GetCurrentProcess", [], w.HANDLE)()
            code = api("kernel32", "PssFreeSnapshot", [w.HANDLE, w.HANDLE], w.DWORD)(
                current, snapshot
            )
            record["snapshot_free_error_code"] = code
            if code:
                record["errors"].append({"type": "PssFreeSnapshot", "winerror": code})
        if handle:
            api("kernel32", "CloseHandle", [w.HANDLE], w.BOOL)(handle)
        record.update(
            wall_ns=time.perf_counter_ns() - wall,
            cpu_ns=time.process_time_ns() - cpu,
            completed_perf_ns=time.perf_counter_ns(),
        )
        save(output / "capture.json", record)


def bounded_capture(request, output):
    """Separate owned worker, finite time/size. Preserve partial evidence on timeout."""
    output = Path(output)
    save(output.with_suffix(".request.json"), request)
    started = time.perf_counter_ns()
    worker = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "capture",
            str(output.with_suffix(".request.json")),
            str(output),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    timed_out, size_exceeded, errors = False, False, []
    try:
        while worker.poll() is None:
            if time.perf_counter_ns() - started > int(WORKER_SECONDS * 1e9):
                timed_out = True
                worker.kill()
                break
            dump = output / "native.dmp"
            if dump.exists() and dump.stat().st_size > MAX_DUMP:
                size_exceeded = True
                worker.kill()
                break
            time.sleep(0.025)
    except Exception as exc:
        errors.append({"type": type(exc).__name__, "message": str(exc)})
        if worker.poll() is None:
            worker.kill()
    _, stderr = worker.communicate(timeout=1)
    output.mkdir(exist_ok=True)
    (output / "worker.stderr").write_bytes(stderr)
    record = {
        "started_perf_ns": started,
        "wall_ns": time.perf_counter_ns() - started,
        "worker_pid": worker.pid,
        "returncode": worker.returncode,
        "timeout": timed_out,
        "size_exceeded": size_exceeded,
        "errors": errors,
        "limit_seconds": WORKER_SECONDS,
    }
    save(output / "supervisor.json", record)
    return record


def probe(output):
    import msvcrt

    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for kind in ("busy", "waiting"):
        arm = output / kind
        arm.mkdir()
        ready = arm / "ready.json"
        source = """const fs=require('node:fs');
fs.writeFileSync(process.argv[1],JSON.stringify({pid:process.pid,version:process.version}));
if(process.argv[2]==='busy'){const end=Date.now()+8000;while(Date.now()<end){}}
else{Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,8000);}
console.log('synthetic native control complete');
"""
        child = subprocess.Popen(
            ["node", "-e", source, str(ready), kind], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        row = {"kind": kind, "usable": False, "errors": []}
        readers = []
        for pipe in (child.stdout, child.stderr):
            thread = threading.Thread(target=pipe.read, daemon=True)
            thread.start()
            readers.append(thread)
        try:
            deadline = time.perf_counter() + 3
            while not ready.exists() and child.poll() is None and time.perf_counter() < deadline:
                time.sleep(0.025)
            admission = ready.exists() and child.poll() is None
            request = {
                "pid": child.pid,
                "birth": process_birth(child._handle),
                "parent_pid": os.getpid(),
                "parent_birth": process_birth(-1),
                "pipes": [
                    {"stream": label, "handle": msvcrt.get_osfhandle(p.fileno())}
                    for label, p in (("stdout", child.stdout), ("stderr", child.stderr))
                ],
                "readers": [reader_identity(t) for t in readers],
                "synthetic_kind": kind,
            }
            result = bounded_capture(request, arm / "capture") if admission else None
            row = {
                "kind": kind,
                "admitted_live_ready": admission,
                "supervisor": result,
                "ready": json.loads(ready.read_text()) if ready.exists() else None,
            }
            details = arm / "capture/capture.json"
            if details.exists():
                detail = json.loads(details.read_text())
                row["native"] = detail
                threads = detail.get("dump", {}).get("threads", [])
                names = [h["name"] for h in detail.get("dump", {}).get("handles", []) if h["name"]]
                expected = [p["name"] for p in detail.get("parent_pipes", []) if p["available"]]
                matches = [p for p in expected if any(n.endswith(p) for n in names)]
                row["pipe_name_matches"] = matches
                row["usable"] = bool(
                    admission
                    and result
                    and not result["timeout"]
                    and not result["size_exceeded"]
                    and result["returncode"] == 0
                    and result["wall_ns"] <= 2_000_000_000
                    and not detail["errors"]
                    and detail["owned_thread_census"]["complete"]
                    and threads
                    and all(t["stack_bytes"] > 0 and t["context_bytes"] > 0 for t in threads)
                    and len(matches) == 2
                    and any(w["available"] and w.get("nodes") for w in detail["wait_chains"])
                )
            else:
                row["usable"] = False
        except Exception as exc:
            row["usable"] = False
            row["errors"] = [{"type": type(exc).__name__, "message": str(exc)}]
        finally:
            if child.poll() is None:
                child.kill()  # Owned synthetic controls only, never an ordinary target.
            child.wait(timeout=2)
            for thread in readers:
                thread.join(timeout=2)
        row["child_exit"] = child.returncode
        row["readers_ended"] = all(not t.is_alive() for t in readers)
        save(arm / "result.json", row)
        rows.append(row)
    usable = len(rows) == 2 and all(r["usable"] and r["readers_ended"] for r in rows)
    result = {
        "schema": "reader415-native-feasibility/v1",
        "usable": usable,
        "rows": rows,
        "monetary_cost": "UNKNOWN",
        "qualification": "NOT_GRANTED",
    }
    save(output / "feasibility.json", result)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write("usable=" + str(usable).lower() + "\n")
    print(
        json.dumps(
            {
                "usable": usable,
                "controls": [{"kind": r["kind"], "usable": r["usable"]} for r in rows],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["probe", "capture"])
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    arguments = parser.parse_args()
    if arguments.operation == "probe":
        probe(arguments.input)
    else:
        capture(json.loads(arguments.input.read_text()), arguments.output)
