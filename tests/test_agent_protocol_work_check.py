"""Process/log conformance with explicitly synthetic local scripts, never app CI."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import agent_protocol_work_check as runner
import agent_protocol_work_source as source


class PortableCheckTests(unittest.TestCase):
    def test_collector_conformance_in_provided_node_runtime(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Work collector conformance requires the provided Node runtime")
        candidates = [Path(__file__).with_name(name) for name in (
            "test_agent_protocol_work_collect.mjs", "agent_protocol_work_collect_test.mjs",
        )]
        present = [path for path in candidates if path.is_file()]
        self.assertEqual(len(present), 1, "one repository-local collector suite is required")
        test_file = present[0]
        result = subprocess.run(
            [node, "--test", str(test_file)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unsupported_host_fails_before_execution_or_output_creation(self):
        root = Path("unused-synthetic-path")
        with (
            patch.object(runner, "os", SimpleNamespace(name="nt")),
            self.assertRaisesRegex(source.EvidenceError, "POSIX"),
        ):
            runner.run_check(root, root, root, root, workstream="PROTOCOL", suite="FULL")


@unittest.skipUnless(os.name == "posix", "POSIX process supervisor conformance")
class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.base = self.parent / "base"
        (self.base / "tools").mkdir(parents=True)
        (self.base / "tools/agent-check").write_text(
            "echo synthetic-out\necho synthetic-error >&2\nexit 7\n"
        )
        entries = source.inventory(self.base)
        tree = source.tree_identity(entries, verify=True)
        self.snapshot = self.parent / "snapshot.json"
        self.snapshot.write_text(
            json.dumps(
                {
                    "schema": source.SCHEMA,
                    "repository": "brickms/brickms",
                    "commit_sha": "a" * 40,
                    "tree_sha": tree,
                    "tree": {"sha": tree, "truncated": False, "tree": list(entries.values())},
                }
            )
        )
        self.candidate = self.parent / "candidate"
        shutil.copytree(self.base, self.candidate)

    def run_fixture(self, **kwargs):
        return runner.run_check(
            self.snapshot,
            self.base,
            self.candidate,
            self.parent / "result",
            workstream="PROTOCOL",
            suite="PROTOCOL_ONLY",
            **kwargs,
        )

    def test_real_nonzero_exit_and_both_streams_preserved(self):
        result, code = self.run_fixture()
        self.assertEqual((result["exit_code"], code), (7, 2))
        self.assertEqual((self.parent / "result/stdout.log").read_text(), "synthetic-out\n")
        self.assertEqual((self.parent / "result/stderr.log").read_text(), "synthetic-error\n")
        self.assertFalse(result["push_qualified"])

    def test_vendor_update_requires_both_independent_inputs(self):
        with self.assertRaisesRegex(source.EvidenceError, "supplied together"):
            self.run_fixture(canonical_snapshot=self.snapshot)
        self.assertFalse((self.parent / "result").exists())

    def test_vendor_update_rejects_noncanonical_repository(self):
        with self.assertRaisesRegex(source.EvidenceError, "canonical vendor repository"):
            self.run_fixture(canonical_snapshot=self.snapshot, canonical_anchor=self.snapshot)
        self.assertFalse((self.parent / "result").exists())

    def test_product_cannot_select_protocol_vendor_adoption(self):
        with self.assertRaisesRegex(source.EvidenceError, "requires PROTOCOL"):
            runner.run_check(
                self.snapshot, self.base, self.candidate, self.parent / "result",
                workstream="PRODUCT", suite="FULL", canonical_snapshot=self.snapshot,
                canonical_anchor=self.snapshot,
            )
        self.assertFalse((self.parent / "result").exists())

    def test_successful_child_cannot_hide_source_change(self):
        (self.candidate / "tools/agent-check").write_text("echo changed > new-file\nexit 0\n")
        result, code = self.run_fixture()
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["source_unchanged"])
        self.assertEqual(code, 2)

    def test_previous_output_is_preserved(self):
        (self.parent / "result").mkdir()
        (self.parent / "result/old").write_text("retained")
        with self.assertRaises(source.EvidenceError):
            self.run_fixture()
        self.assertEqual((self.parent / "result/old").read_text(), "retained")

    def test_external_adapter_cannot_be_candidate_controlled(self):
        with self.assertRaisesRegex(source.EvidenceError, "outside source directories"):
            self.run_fixture(adapter_root=self.candidate)
        self.assertFalse((self.parent / "result").exists())

    def test_external_adapter_is_passed_explicitly_to_local_guard(self):
        external = self.parent / "canonical"
        external.mkdir()
        result, code = self.run_fixture(adapter_root=external)
        at = result["command"].index("--work-tools")
        self.assertEqual(result["command"][at + 1], str(external.resolve()))
        self.assertEqual((result["exit_code"], code), (7, 2))

    def test_evidence_cannot_pollute_source(self):
        with self.assertRaises(source.EvidenceError):
            runner.run_check(
                self.snapshot,
                self.base,
                self.candidate,
                self.candidate / "result",
                workstream="PROTOCOL",
                suite="PROTOCOL_ONLY",
            )

    def test_timeout_records_real_terminal_code(self):
        (self.candidate / "tools/agent-check").write_text("sleep 10\n")
        result, code = self.run_fixture(timeout=1)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["exit_code"], -15)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
