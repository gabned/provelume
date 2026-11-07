from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from scripts import concordia_kernel_native as native


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux process-limit envelope")
def test_original_complete_limits_survive_actual_launcher_without_raising_any_limit():
    limits = native.process_limits()
    assert "locks" in limits and "memlock" in limits and "nofile" in limits
    observed = subprocess.check_output([*native.limit_command(limits), sys.executable, "-c",
        "import json;from scripts.concordia_kernel_native import process_limits;"
        "print(json.dumps(process_limits()))"], cwd=native.ROOT, text=True)
    assert json.loads(observed) == limits


def test_markers_select_only_the_original_cold_probe_and_restore_methods_on_error():
    events = []

    class Adapter:
        def submit(self):
            return "unchanged submit"

        def process(self):
            return "unchanged process"

    adapter = Adapter()
    error = OSError("original failure")

    def probe(instance, number):
        assert instance is adapter
        assert adapter.submit() == "unchanged submit"
        assert adapter.process() == "unchanged process"
        if number == 810:
            raise error
        return {"sample": number}

    synthesis = SimpleNamespace(deterministic_probe=probe)
    originals = Adapter.submit, Adapter.process
    with pytest.raises(OSError) as observed, native.capture_marks(
            Adapter, synthesis, events.append) as selected:
        for number in (0, 1, 2, 800, 801, 802):
            assert synthesis.deterministic_probe(adapter, number) == {"sample": number}
        assert events == []
        synthesis.deterministic_probe(adapter, 810)
    assert observed.value is error and selected == [810]
    assert events == [9, 1, 2, 3, 4, 10]
    assert (Adapter.submit, Adapter.process) == originals
    assert synthesis.deterministic_probe is probe


def test_repeated_cold_sample_refuses_before_a_second_frame():
    adapter = SimpleNamespace(submit=lambda: 1, process=lambda: 2)
    result = {"sample": 810}
    synthesis = SimpleNamespace(deterministic_probe=lambda *_: (adapter.submit(),
                                adapter.process(), result)[-1])
    events = []
    with native.capture_marks(adapter, synthesis, events.append):
        assert synthesis.deterministic_probe(None, 810) is result
        assert synthesis.deterministic_probe(None, 811) is result
        with pytest.raises(ValueError, match="repeated"):
            synthesis.deterministic_probe(None, 810)
    assert events == [9, 1, 2, 3, 4, 10]


def test_inventory_requires_every_owned_exit_and_each_original_trace_exit(tmp_path):
    trace = tmp_path / "network.12"
    trace.write_text("+++ exited with 0 +++\n")
    rows = [["F", 1, 10, 11], ["F", 2, 11, 12],
            ["X", 3, 12], ["X", 4, 11], ["X", 5, 10]]
    assert native.inventory(rows, [trace])["owned_tasks"] == 3
    with pytest.raises(ValueError, match="fork/exit"):
        native.inventory(rows[:-1], [trace])
    trace.write_text("unfinished original trace\n")
    with pytest.raises(ValueError, match="strace exit"):
        native.inventory(rows, [trace])


def test_syscalls_crossing_window_boundaries_still_need_real_paired_events():
    rows = [["U", 1, 11, 1], ["U", 4, 11, 0],
            ["D", 4, 11, 1], ["D", 8, 11, 0]]
    assert native.syscall_pairs(rows, 2, 6) == {"U": 1, "D": 1}
    for bad in (rows[1:], rows[:-1], [*rows, rows[-1]]):
        with pytest.raises(ValueError, match="pairing"):
            native.syscall_pairs(bad, 2, 6)


def test_native_missing_host_capability_retains_refusal_before_any_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "sources", lambda: {"baseline": native.BASE})
    def unavailable():
        raise ValueError("native host capability absent")
    monkeypatch.setattr(native, "host", unavailable)
    output = tmp_path / "admission"
    assert native.admit(output) == 1
    receipt = json.loads((output / "admission.json").read_text())
    assert receipt["native_inference"] == "NOT_RUN" and receipt["status"] == "NOT_ADMITTED"
    assert not receipt["qualification_eligible"]
    with pytest.raises(FileExistsError):
        native.admit(output)


def test_native_selector_is_exclusive_and_keeps_original_execution_bounds():
    path = native.ROOT / ".github/workflows/ai-runtime-candidate.yml"
    workflow = yaml.safe_load(path.read_text())
    jobs = workflow["jobs"]
    condition = jobs["concordia-kernel-native"]["if"]
    assert "inputs.concordia_observer_source == 'native-cold-810'" in condition
    assert "github.run_attempt == 1" in condition
    assert "inputs.concordia_observer_source != 'native-cold-810'" in jobs[
        "concordia-kernel-control"]["if"]
    steps = jobs["concordia-kernel-native"]["steps"]
    commands = [s.get("run", "") for s in steps]
    admission = next(i for i, s in enumerate(commands) if "native.py admit" in s)
    acquire = next(i for i, s in enumerate(commands) if "ai_runtime_acquire.py" in s)
    measure = next(i for i, s in enumerate(commands) if "native.py run" in s)
    assert admission < acquire < measure
