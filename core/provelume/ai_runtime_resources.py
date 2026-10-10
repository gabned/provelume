"""Observed Linux cgroup v2 bounds; no host-capacity claim for a limited container."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from .ai_models import ModelError, check


def _read(path, maximum=4096):
    with path.open("r", encoding="ascii") as stream:
        value = stream.read(maximum + 1)
    check(len(value) <= maximum, "compatibility")
    return value.strip()


def _integer(value):
    check(re.fullmatch(r"[0-9]{1,20}", value) is not None, "compatibility")
    return int(value)


def _cpuset(value):
    check(bool(value), "compatibility")
    selected = set()
    for item in value.split(","):
        parts = item.split("-")
        check(len(parts) in (1, 2), "compatibility")
        first = _integer(parts[0])
        last = _integer(parts[-1])
        check(first <= last < 65536 and last - first < 8192, "compatibility")
        values = set(range(first, last + 1))
        check(not selected.intersection(values), "compatibility")
        selected.update(values)
        check(len(selected) <= 8192, "compatibility")
    return selected


def _mount_path(value):
    # mountinfo uses octal escapes, never shell escaping.
    decoded = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)
    path = PurePosixPath(decoded)
    check(path.is_absolute() and ".." not in path.parts, "compatibility")
    return path


def _location(proc):
    membership = _read(proc / "self/cgroup")
    rows = membership.splitlines()
    if not rows:
        return None
    check(len(rows) == 1 and rows[0].startswith("0::"), "compatibility")
    group = _mount_path(rows[0][3:])
    mounts = []
    for line in _read(proc / "self/mountinfo", 1024 * 1024).splitlines():
        left, separator, right = line.partition(" - ")
        if not separator or not right.startswith("cgroup2 "):
            continue
        fields = left.split()
        check(len(fields) >= 6, "compatibility")
        mount = Path(str(_mount_path(fields[4])))
        if group == PurePosixPath("/"):
            # In a cgroup namespace / is the visible root, even when mountinfo
            # reports an ancestor as /... or /.../.. outside that namespace.
            relative = PurePosixPath(".")
        else:
            source_root = _mount_path(fields[3])
            if not group.is_relative_to(source_root):
                continue
            relative = group.relative_to(source_root)
        mounts.append((mount, mount / str(relative)))
    check(len(mounts) == 1, "compatibility")
    return mounts[0]


def effective_limits(total, available, affinity, *, proc=Path("/proc")):
    """Intersect host observations with every visible applicable ancestor bound.

    Limits outside the mounted cgroup namespace are not claimed to be observed.
    Missing/unreadable/malformed applicable files fail closed, never restore host RAM.
    """
    try:
        location = _location(proc)
        selected = set(affinity)
        quota = len(selected)
        count = 0
        if location is not None:
            mount, current = location
            check(current.is_relative_to(mount), "compatibility")
            while True:
                count += 1
                check(count <= 64, "compatibility")
                is_root = current == mount
                controllers = set(_read(current / "cgroup.controllers").split())
                maximum = current / "memory.max"
                if maximum.exists() or (not is_root and "memory" in controllers):
                    limit = _read(maximum)
                    used = _integer(_read(current / "memory.current"))
                    if limit != "max":
                        capacity = _integer(limit)
                        total = min(total, capacity)
                        available = min(available, max(0, capacity - used))
                cpu = current / "cpu.max"
                if cpu.exists() or (not is_root and "cpu" in controllers):
                    parts = _read(cpu).split()
                    check(len(parts) == 2, "compatibility")
                    period = _integer(parts[1])
                    check(period > 0, "compatibility")
                    if parts[0] != "max":
                        quota = min(quota, _integer(parts[0]) // period)
                cpus = current / "cpuset.cpus.effective"
                if cpus.exists() or (not is_root and "cpuset" in controllers):
                    selected.intersection_update(_cpuset(_read(cpus)))
                if is_root:
                    break
                current = current.parent
        return {
            "ram_total": total, "ram_available": min(total, available),
            "logical_cpus": min(quota, len(selected)),
            "resource_observation": "host-and-visible-cgroup-v2-ancestors",
            "cgroup_ancestors_observed": count,
            "unmounted_ancestors": "NOT_OBSERVED",
        }
    except ModelError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise ModelError("compatibility") from None
