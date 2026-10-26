"""Portable planning and refusal controls; no model, capture or qualification."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "core")]

from provelume.ai_runtime_cpu import select_pair  # noqa: E402
from scripts import diagnose_concordia_cpu as diagnostic  # noqa: E402


class PortableTopologyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def topology(self, rows):
        for cpu, package, core in rows:
            directory = self.root / f"cpu{cpu}" / "topology"
            directory.mkdir(parents=True)
            (directory / "physical_package_id").write_text(str(package))
            (directory / "core_id").write_text(str(core))
        return {row[0] for row in rows}

    def plan(self, rows):
        allowed = self.topology(rows)
        result = diagnostic.portable_tracer_plan(allowed, self.root)
        native_pair, _ = select_pair(allowed, [set(core) for core in result["cores"]])
        self.assertEqual(result["worker_cpus"], native_pair)
        self.assertEqual(result["allowed"], sorted(allowed))
        return result

    def test_smt_uses_the_two_workers_siblings(self):
        result = self.plan([(0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 1)])
        self.assertEqual(result["worker_cpus"], [0, 2])
        self.assertEqual(result["portable_foreground"], 1)
        self.assertEqual(result["tracer_other"], 3)
        self.assertEqual(result["layout"], "worker-smt-siblings")

    def test_four_physical_cores_keep_capture_and_other_tracer_off_workers(self):
        result = self.plan([(0, 0, 0), (1, 0, 1), (2, 0, 2), (3, 0, 3)])
        self.assertEqual(result["worker_cpus"], [0, 1])
        self.assertEqual(result["portable_foreground"], 2)
        self.assertEqual(result["tracer_other"], 3)
        self.assertEqual(result["layout"], "separate-physical-cores")

    def test_noncontiguous_cpus_and_package_identity_match_native_selection(self):
        result = self.plan([(4, 0, 6), (7, 0, 6), (8, 1, 6), (9, 1, 6)])
        self.assertEqual(result["worker_cpus"], [4, 8])
        self.assertEqual(result["cores"], [[4, 7], [8, 9]])
        self.assertEqual((result["portable_foreground"], result["tracer_other"]), (7, 9))

    def test_a_larger_allowed_mask_is_recorded_without_narrowing_it(self):
        result = self.plan([(cpu, 0, cpu // 2) for cpu in range(8)])
        self.assertEqual(result["allowed"], list(range(8)))
        self.assertEqual(result["worker_cpus"], [0, 2])
        self.assertEqual((result["portable_foreground"], result["tracer_other"]), (1, 3))

    def test_asymmetric_worker_cores_use_two_separate_unused_cores(self):
        result = self.plan([(0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 2), (4, 0, 3)])
        self.assertEqual(result["worker_cpus"], [0, 2])
        self.assertEqual((result["portable_foreground"], result["tracer_other"]), (3, 4))

    def test_insufficient_allowed_mask_is_refused_before_topology_guessing(self):
        with self.assertRaisesRegex(ValueError, "four allowed logical CPUs"):
            diagnostic.portable_tracer_plan({0, 1, 2}, self.root)

    def test_an_unbalanced_three_core_layout_is_refused(self):
        allowed = self.topology([(0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 2)])
        with self.assertRaisesRegex(ValueError, "two worker siblings or four physical"):
            diagnostic.portable_tracer_plan(allowed, self.root)

    def test_missing_topology_is_an_error_instead_of_a_fabricated_plan(self):
        with self.assertRaises(FileNotFoundError):
            diagnostic.portable_tracer_plan({0, 1, 2, 3}, self.root)

    def test_invalid_physical_identity_is_refused(self):
        allowed = self.topology([(0, 0, 0), (1, 0, 1), (2, 0, 2), (3, 0, 3)])
        (self.root / "cpu2/topology/core_id").write_text("-1")
        with self.assertRaisesRegex(ValueError, "topology unavailable"):
            diagnostic.portable_tracer_plan(allowed, self.root)

    def test_actual_model_is_retained_without_an_original_model_requirement(self):
        cpuinfo = self.root / "cpuinfo"
        cpuinfo.write_text("model name: AMD EPYC 9V45 96-Core Processor\nflags: avx avx2\n")
        observed = diagnostic.portable_environment(cpuinfo)
        self.assertEqual(observed["cpu_models"], ["AMD EPYC 9V45 96-Core Processor"])
        self.assertTrue(observed["avx2"])
        self.assertFalse(observed["original_profile_required"])
        with self.assertRaisesRegex(ValueError, "original EPYC"):
            diagnostic.require_original_cpu(cpuinfo)

    def test_missing_avx2_is_observed_as_unavailable(self):
        cpuinfo = self.root / "cpuinfo"
        cpuinfo.write_text("model name: observed synthetic CPU\nflags: avx\n")
        self.assertFalse(diagnostic.portable_environment(cpuinfo)["avx2"])

    def test_unavailable_native_accounting_cannot_be_faked(self):
        with patch.object(diagnostic, "resource", None):
            with self.assertRaisesRegex(RuntimeError, "accounting unavailable"):
                diagnostic.accounting()

    @unittest.skipUnless(sys.platform == "win32", "actual Windows refusal control")
    def test_windows_admission_stops_before_model_acquisition(self):
        output = self.root / "admission.json"
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/diagnose_concordia_cpu.py"),
             "portable-topology", "--output", str(output)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        report = json.loads(output.read_text())
        self.assertEqual(report["status"], "CAPABILITY_MISSING")
        self.assertEqual(report["model_acquisition"], "NOT_RUN")
        self.assertFalse(report["qualification_eligible"])


if __name__ == "__main__":
    unittest.main()
