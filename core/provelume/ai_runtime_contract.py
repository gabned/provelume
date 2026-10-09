"""Closed S05 candidate identity. Import never probes or acquires."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from importlib.resources import files

from .ai_models import check

RUNTIME_ID = "llama.cpp"
RUNTIME_VERSION = "b11379"
MODEL_ID = "qwen2.5-1.5b-instruct-q4-k-m"
MODEL_FORMAT = "gguf-v3-q4_k_m"
MODEL_SIZE = 1117320736
MODEL_SHA256 = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
LOCK_SHA256 = "0e508965cddc60d6cfb57c42d2c4039c637e8812bb25cc21b525b6d6047a4404"
CONFIGURATION = {
    "schema_version": 1,
    "purpose": "internal-runtime-qualification-only",
    "runtime_lock": LOCK_SHA256,
    "threads": 2,
    "context_tokens": 2048,
    "input_tokens": 1536,
    "input_bytes": 4096,
    "output_tokens": 128,
    "output_bytes": 4096,
    "processes": 1,
    "queue": 0,
    "gpu_layers": 0,
    "memory_bytes": 3 * 1024**3,
    "seconds": 60,
    "idle_seconds": 5,
    "termination_seconds": 2,
    "sampling": "greedy",
    "synthesis_format": "extractive-gbnf-v1",
}


def runtime_lock():
    raw = files("provelume").joinpath("ai_runtime_lock.json").read_bytes()
    check(hashlib.sha256(raw).hexdigest() == LOCK_SHA256, "untrusted")
    return json.loads(raw)


def hardware():
    """Observed resources, not qualification of a reference laptop."""
    system = platform.system().lower()
    cpu = platform.processor()
    check(not getattr(sys, "frozen", False), "compatibility")
    check(sys.version_info[:2] == (3, 12), "compatibility")
    check(system in ("windows", "linux"), "compatibility")
    check(platform.machine().lower() in ("amd64", "x86_64"), "compatibility")
    if system == "windows":
        import ctypes

        check(bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40)), "compatibility")

        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong)
                for n in (
                    "total",
                    "available",
                    "page",
                    "available_page",
                    "virtual",
                    "available_virtual",
                    "extended",
                )
            ]

        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        check(bool(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))), "state")
        total, available = memory.total, memory.available
        cpus = os.cpu_count() or 0
    else:
        values = {}
        with open("/proc/meminfo", encoding="ascii") as stream:
            for line in stream:
                key, value = line.split(":", 1)
                values[key] = int(value.split()[0]) * 1024
        total, available = values["MemTotal"], values["MemAvailable"]
        cpus = len(os.sched_getaffinity(0))
        with open("/proc/cpuinfo", encoding="ascii") as stream:
            cpuinfo = stream.read()
        cpu = next((line.split(":", 1)[1].strip() for line in cpuinfo.splitlines()
                    if line.startswith("model name")), cpu)
        flags = [set(line.split(":", 1)[1].split()) for line in cpuinfo.splitlines()
                 if line.startswith("flags")]
        check(bool(flags) and all("avx2" in row for row in flags), "compatibility")
    check(cpus >= 4 and total >= 8 * 1024**3 and available >= 4 * 1024**3, "limit")
    return {
        "os": platform.platform(),
        "platform": system,
        "architecture": platform.machine(),
        "cpu": cpu,
        "python": platform.python_version(),
        "avx2": True,
        "logical_cpus": cpus,
        "ram_total": total,
        "ram_available": available,
    }
