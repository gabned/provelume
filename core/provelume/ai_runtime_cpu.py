"""Worker bootstrap CPU topology. No application imports or affinity mutation."""

from __future__ import annotations

import ctypes as c
from pathlib import Path

SELECTION = "distinct-physical-cores-v1"
_MAX_CPUS = 4096


def _require(condition):
    if not condition:
        raise ValueError("CPU topology unavailable")


def select_pair(allowed, cores):
    """Choose two independent cores, never CPUs outside the inherited mask."""
    _require(type(allowed) in (set, frozenset) and 2 <= len(allowed) <= _MAX_CPUS)
    _require(all(type(cpu) is int and 0 <= cpu < _MAX_CPUS for cpu in allowed))
    _require(type(cores) in (list, tuple) and 2 <= len(cores) <= len(allowed))
    covered = set()
    for core in cores:
        _require(type(core) in (set, frozenset) and bool(core) and core <= allowed)
        _require(all(type(cpu) is int for cpu in core))
        _require(not covered.intersection(core))
        covered.update(core)
    _require(covered == allowed)
    ordered = sorted(cores, key=min)
    selected = [min(core) for core in ordered[:2]]
    old = set(sorted(allowed)[:2])
    return selected, {
        "selection": SELECTION,
        "allowed_logical_cpus": len(allowed),
        "allowed_physical_cores": len(cores),
        "selected_logical_cpus": selected,
        "selected_physical_cores": 2,
        "first_logical_pair_shares_core": any(old <= core for core in cores),
    }


def linux_pair(allowed):
    _require(type(allowed) is set and 2 <= len(allowed) <= _MAX_CPUS)
    _require(all(type(cpu) is int and 0 <= cpu < _MAX_CPUS for cpu in allowed))
    cores = {}
    for cpu in sorted(allowed):
        root = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        identity = []
        for name in ("physical_package_id", "core_id"):
            with (root / name).open(encoding="ascii") as stream:
                raw = stream.read(32).strip()
            _require(raw.isascii() and raw.isdecimal() and len(raw) <= 10)
            identity.append(int(raw))
        cores.setdefault(tuple(identity), set()).add(cpu)
    return select_pair(allowed, list(cores.values()))


class _ProcessorInformation(c.Structure):
    # The reserved union member supplies its documented size and alignment.
    _fields_ = [("mask", c.c_size_t), ("relationship", c.c_uint32),
                ("reserved", c.c_uint64 * 2)]


def windows_pair(kernel, allowed_mask):
    """Current processor group only, matching the existing process-affinity scope."""
    _require(c.sizeof(c.c_void_p) == 8 and type(allowed_mask) is int
             and 0 < allowed_mask < 2**64)
    get = kernel.GetLogicalProcessorInformation
    get.argtypes = [c.c_void_p, c.POINTER(c.c_uint32)]
    get.restype = c.c_int
    size = c.c_uint32()
    _require(not get(None, c.byref(size)) and c.get_last_error() == 122)
    row_size = c.sizeof(_ProcessorInformation)
    _require(row_size == 32 and 0 < size.value <= 64 * 1024 and size.value % row_size == 0)
    capacity = size.value
    records = (_ProcessorInformation * (capacity // row_size))()
    _require(bool(get(records, c.byref(size))))
    _require(0 < size.value <= capacity and size.value % row_size == 0)
    allowed = {cpu for cpu in range(64) if allowed_mask & (1 << cpu)}
    cores = []
    for row in records[:size.value // row_size]:
        if row.relationship == 0:  # RelationProcessorCore, not cache/package sharing.
            _require(row.mask != 0)
            members = {cpu for cpu in allowed if row.mask & (1 << cpu)}
            if members:
                cores.append(members)
    return select_pair(allowed, cores)
