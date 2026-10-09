"""Closed S05 candidate identity. Import never probes or acquires."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from importlib.resources import files

from .ai_models import check
from .ai_synthesis_profile import PROFILE, framing_identity

RUNTIME_ID = "llama.cpp"
RUNTIME_VERSION = "b11379"
MODEL_ID = "qwen3-1.7b-q4-k-m"
MODEL_FORMAT = "gguf-v3-q4_k_m"
MODEL_SIZE = 1107408544
MODEL_SHA256 = "228fb5627f7510b8b3516cdb6435e4b0d2a2bf330fe5b0ab19284a3570a8bb1f"
MODEL_LICENSE = "qwen3-LICENSE.txt"
MODEL_URL = ("https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/"
             "7fb011e9aee6e4dc7adf8430df9ea8de6a466aa3/Qwen3-1.7B-Q4_K_M.gguf")


@dataclass(frozen=True, slots=True)
class NativeModelPin:
    id: str
    format: str
    size: int
    sha256: str
    url: str
    license_file: str
    evidence: str


NATIVE_MODEL_PINS = (
    NativeModelPin(MODEL_ID, MODEL_FORMAT, MODEL_SIZE, MODEL_SHA256, MODEL_URL,
                   MODEL_LICENSE, "repository:docs/adr/0039-bounded-selection-assessment.md"),
    NativeModelPin(
        "qwen3-4b-instruct-2507-q2-k", "gguf-v3-q2_k", 1669499616,
        "7f9efe8a86c1d200139801642dcf8c0d9f2cf09c89ef4e8f0ea525536368c4ca",
        "https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/"
        "ac104788567ef76beaf5f30b6cccb1f99a69afbe/Qwen_Qwen3-4B-Instruct-2507-Q2_K.gguf",
        "qwen-LICENSE.txt", "repository:docs/adr/0038-qwen3-instruct-synthesis-candidate.md",
    ),
    NativeModelPin(
        "qwen2.5-1.5b-instruct-q4-k-m", "gguf-v3-q4_k_m", 1117320736,
        "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
        "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
        "91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "qwen-LICENSE.txt", "repository:docs/adr/0031-cpu-local-runtime-candidate.md",
    ),
)
RETIRED_MODEL_IDS = tuple(pin.id for pin in NATIVE_MODEL_PINS if pin.id != MODEL_ID)


def native_model_pin(identifier):
    pin = next((item for item in NATIVE_MODEL_PINS if item.id == identifier), None)
    check(pin is not None, "compatibility")
    return pin


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
    "synthesis_format": PROFILE,
    "synthesis_instructions": {str(cap): framing_identity(cap) for cap in (2, 3)},
    "chat_template": "qwen3-nonthinking-v1",
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
