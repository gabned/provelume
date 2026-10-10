"""Topology admission and two-core isolation; no model/performance claims."""
from __future__ import annotations

import ctypes as c
from types import SimpleNamespace

import pytest

from provelume import ai_runtime_cpu as cpu


@pytest.mark.parametrize("allowed,cores,expected,shared", [
    ({0, 1, 2, 3}, [{0, 1}, {2, 3}], [0, 2], True),
    ({0, 1, 2, 3}, [{2, 3}, {0, 1}], [0, 2], True),
    ({1, 3}, [{1}, {3}], [1, 3], False),
    ({2, 8, 20, 21}, [{2, 20}, {8, 21}], [2, 8], False),
    ({0, 1, 2, 3}, [{0}, {1}, {2}, {3}], [0, 1], False),
])
def test_avoids_smt_siblings_without_widening_inherited_affinity(allowed, cores, expected, shared):
    pair, evidence = cpu.select_pair(allowed, cores)
    assert pair == expected and len(pair) == 2 and set(pair) <= allowed
    assert all(not set(pair) <= core for core in cores)
    assert evidence['first_logical_pair_shares_core'] is shared
    assert evidence['allowed_physical_cores'] == len(cores)
    assert evidence['selected_logical_cpus'] == pair


@pytest.mark.parametrize("allowed,cores", [
    ({0, 1}, [{0, 1}]), ({0, 1, 2}, [{0}, {1}]),
    ({0, 1, 2}, [{0, 1}, {1, 2}]), ({0, 1}, [{0}, {1, 2}]),
    ({0, 1}, [{0}, set(), {1}]), ({False, 1}, [{0}, {1}]),
    ({0, 1}, [{False}, {1}]), ({0, 4096}, [{0}, {4096}]),
])
def test_unknown_overlapping_incomplete_or_single_core_is_refused(allowed, cores):
    with pytest.raises(ValueError, match='CPU topology unavailable'):
        cpu.select_pair(allowed, cores)


def test_linux_package_identity_keeps_equal_core_ids_on_different_sockets_distinct(
    tmp_path, monkeypatch,
):
    from pathlib import Path

    for number, package in ((4, 0), (8, 0), (20, 1), (24, 1)):
        root = tmp_path / f'cpu{number}' / 'topology'
        root.mkdir(parents=True)
        (root / 'physical_package_id').write_text(str(package) + '\n')
        (root / 'core_id').write_text('0\n')
    monkeypatch.setattr(cpu, 'Path', lambda name: tmp_path / Path(name).relative_to(
        '/sys/devices/system/cpu'))
    pair, evidence = cpu.linux_pair({4, 8, 20, 24})
    assert pair == [4, 20] and evidence['first_logical_pair_shares_core'] is True
    (tmp_path / 'cpu20/topology/core_id').write_text('-1\n')
    with pytest.raises(ValueError):
        cpu.linux_pair({4, 8, 20, 24})


def kernel_fixture(monkeypatch, records, *, initial_size=None, final_size=None, error=122):
    rows = (cpu._ProcessorInformation * len(records))()
    for row, (mask, relationship) in zip(rows, records, strict=True):
        row.mask, row.relationship = mask, relationship
    calls = []

    def get(buffer, size):
        size = c.cast(size, c.POINTER(c.c_uint32))
        calls.append(buffer is None)
        if buffer is None:
            size.contents.value = c.sizeof(rows) if initial_size is None else initial_size
            return 0
        assert size.contents.value >= c.sizeof(rows)
        c.memmove(buffer, rows, c.sizeof(rows))
        size.contents.value = c.sizeof(rows) if final_size is None else final_size
        return 1

    monkeypatch.setattr(c, 'get_last_error', lambda: error, raising=False)
    return SimpleNamespace(GetLogicalProcessorInformation=get), calls


def test_windows_uses_core_relationships_and_allowed_mask_not_cache_or_record_order(monkeypatch):
    kernel, calls = kernel_fixture(monkeypatch, [(15, 2), (12, 0), (3, 0), (15, 3)])
    pair, evidence = cpu.windows_pair(kernel, 15)
    assert pair == [0, 2] and evidence['first_logical_pair_shares_core'] is True
    assert calls == [True, False]
    assert cpu.windows_pair(kernel, 10)[0] == [1, 3]


@pytest.mark.parametrize('change', [
    {'initial_size': 65537}, {'initial_size': 0}, {'initial_size': 65},
    {'final_size': 65}, {'final_size': 33}, {'error': 5},
])
def test_windows_size_race_malformed_or_failed_observation_is_refused(monkeypatch, change):
    kernel, calls = kernel_fixture(monkeypatch, [(3, 0), (12, 0)], **change)
    with pytest.raises(ValueError, match='CPU topology unavailable'):
        cpu.windows_pair(kernel, 15)
    assert len(calls) <= 2


@pytest.mark.parametrize('records', [[(3, 0)], [(3, 0), (6, 0)], [(3, 2), (12, 3)]])
def test_windows_cannot_infer_missing_or_ambiguous_physical_cores(monkeypatch, records):
    kernel, _ = kernel_fixture(monkeypatch, records)
    with pytest.raises(ValueError):
        cpu.windows_pair(kernel, 15)
