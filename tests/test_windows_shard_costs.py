from __future__ import annotations

from collections import Counter

import pytest

from provelume import pytest_windows_shard as sharding


def _nodes(sizes: dict[str, int]) -> list[str]:
    return [
        f"{source}::test_case_{index}" for source, size in sizes.items() for index in range(size)
    ]


def test_cost_hints_separate_expensive_modules_without_changing_membership(monkeypatch):
    sizes = {f"tests/test_cost_{index}.py": 10 for index in range(8)}
    costs = (100000, 90000, 10000, 10000, 80000, 70000, 10000, 10000)
    heavy = [f"tests/test_cost_{index}.py" for index in (0, 1, 4, 5)]
    hints = tuple((source, sizes[source], cost) for source, cost in zip(sizes, costs, strict=True))
    nodeids = _nodes(sizes)
    monkeypatch.setattr(sharding, "_MODULE_COST_HINTS", ())
    count_only = sharding.balanced_shard_assignments(nodeids, 4)
    assert len({count_only[source] for source in heavy}) == 2
    monkeypatch.setattr(sharding, "_MODULE_COST_HINTS", hints)
    assigned = sharding.balanced_shard_assignments(nodeids, 4)
    assert assigned == sharding.balanced_shard_assignments(list(reversed(nodeids)), 4)
    assert set(assigned) == set(sizes)
    assert set(assigned.values()) == set(range(4))
    assert len({assigned[source] for source in heavy}) == 4
    selected = [[node for node in nodeids if assigned[node.split("::")[0]] == i] for i in range(4)]
    assert Counter(node for group in selected for node in group) == Counter(nodeids)


def test_unknown_modules_and_changed_counts_retain_count_only_allocation(monkeypatch):
    sizes = {f"tests/test_count_{index}.py": size for index, size in enumerate((31, 29, 23, 19))}
    nodes = _nodes(sizes)
    monkeypatch.setattr(sharding, "_MODULE_COST_HINTS", ())
    count_only = sharding.balanced_shard_assignments(nodes, 4)
    monkeypatch.setattr(
        sharding,
        "_MODULE_COST_HINTS",
        (("tests/test_count_0.py", 30, 1000000), ("tests/test_not_collected.py", 99, 1000000)),
    )
    assert sharding.balanced_shard_assignments(nodes, 4) == count_only
    assert "tests/test_not_collected.py" not in count_only


def test_hints_do_not_change_targeted_invocation_or_empty_shard_behavior(monkeypatch):
    monkeypatch.delenv(sharding.FORCE_ENV, raising=False)
    monkeypatch.delenv(sharding.CHILD_ENV, raising=False)
    monkeypatch.delenv(sharding.DISABLE_ENV, raising=False)
    node = (
        "tests/test_agent_protocol_v1_2.py::"
        "test_recovery_effect_profile_is_exact_and_keeps_unknown_paths_closed"
    )
    assert sharding._should_orchestrate((node,)) is False
    assert sharding.balanced_shard_assignments([node], 4) == {node.split("::")[0]: 0}
    assert sharding.balanced_shard_assignments([], 4) == {}


@pytest.mark.parametrize(
    "hints",
    [
        [],
        (("tests/test_valid.py", 1),),
        (("tests/test_valid.py", True, 10),),
        (("tests/test_valid.py", 1, False),),
        (("tests/test_valid.py", 0, 10),),
        (("tests/test_valid.py", 1, -1),),
        (("tests/test_valid.py", 1, 1.0),),
        (("tests/test_valid.py", 1, 10), ("tests/test_valid.py", 1, 20)),
        (("tests/../test_other.py", 1, 10),),
        (("tests//test_other.py", 1, 10),),
        (("/tests/test_other.py", 1, 10),),
        (("tests\\test_other.py", 1, 10),),
        (("tests/test_other.py\n", 1, 10),),
        (("tests/C:test_other.py", 1, 10),),
        ((1, 1, 10),),
    ],
)
def test_malformed_hints_fail_before_any_allocation_even_when_not_collected(monkeypatch, hints):
    monkeypatch.setattr(sharding, "_MODULE_COST_HINTS", hints)
    with pytest.raises(ValueError, match="allocation hint"):
        sharding.balanced_shard_assignments(["tests/test_unrelated.py::test_one"], 4)
