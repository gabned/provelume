"""A changed native wait policy must be applied and observed before inference."""

from types import SimpleNamespace

import pytest

from provelume.ai_llama import _configure_windows_openmp_wait
from provelume.ai_models import ModelError


class NativeFunction:
    def __init__(self, function):
        self.function = function

    def __call__(self, *arguments):
        return self.function(*arguments)


def test_wait_policy_applies_zero_and_verifies_native_readback():
    state = {"blocktime": 200, "calls": []}

    def set_value(value):
        state["calls"].append(("set", value))
        state["blocktime"] = value

    def get_value():
        state["calls"].append(("get", state["blocktime"]))
        return state["blocktime"]

    library = SimpleNamespace(kmp_set_blocktime=NativeFunction(set_value),
                              kmp_get_blocktime=NativeFunction(get_value))
    _configure_windows_openmp_wait(library)
    assert state["calls"] == [("set", 0), ("get", 0)]


@pytest.mark.parametrize("library", [
    SimpleNamespace(),
    SimpleNamespace(kmp_set_blocktime=NativeFunction(lambda _: None)),
    SimpleNamespace(kmp_set_blocktime=NativeFunction(lambda _: None),
                    kmp_get_blocktime=NativeFunction(lambda: 200)),
])
def test_unavailable_or_ineffective_wait_policy_refuses_native_use(library):
    with pytest.raises(ModelError) as raised:
        _configure_windows_openmp_wait(library)
    assert raised.value.code == "compatibility"


def test_changed_wait_policy_cannot_silently_use_this_implementation(monkeypatch):
    from provelume.ai_runtime_contract import CONFIGURATION

    monkeypatch.setitem(CONFIGURATION, "windows_openmp_wait", "unqualified-policy")
    with pytest.raises(ModelError) as raised:
        _configure_windows_openmp_wait(SimpleNamespace())
    assert raised.value.code == "compatibility"
