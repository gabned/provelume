"""Portable synthetic conformance; no network, private data or platform mutations."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "execution147", ROOT / "tools/agent_protocol_v1_4_7.py"
)
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


class ExecutionConformance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.rows = []
        for identity, role, phases in (
            ("safety", "ALWAYS", ["START"]),
            ("work", "PROCEDURE", ["RESUME"]),
            ("archive", "HISTORICAL", ["START"]),
        ):
            content = (identity + " rules\n").encode()
            (self.root / (identity + ".md")).write_bytes(content)
            self.rows.append(
                {
                    "id": identity,
                    "path": identity + ".md",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "role": role,
                    "workstreams": ["PROTOCOL"],
                    "phases": phases,
                    "hosts": ["WORK"],
                    "requires": [],
                }
            )
        self.manifest = {
            "schema": "agent-documents/v1",
            "protocol_version": "1.4.7",
            "documents": self.rows,
            "repository_policy": {},
        }

    def select(self, **kwargs):
        return p.select_documents(
            self.root,
            self.manifest,
            p.digest(self.manifest),
            workstream="PROTOCOL",
            phase=kwargs.pop("phase", "START"),
            **kwargs,
        )

    def test_always_rules_and_selection_are_deterministic(self):
        first = self.select()
        self.assertEqual([r["id"] for r in first["documents"]], ["safety"])
        self.assertEqual(first, self.select())
        self.assertFalse(first["push_qualified"])
        self.assertLess(first["model_bytes"], first["verified_inventory_bytes"])

    def test_always_rules_survive_nonmatching_phase(self):
        self.assertEqual([r["id"] for r in self.select(phase="CLOSE")["documents"]], ["safety"])

    def test_uncertain_selection_uses_full_historical_fallback(self):
        value = self.select(phase="UNKNOWN")
        self.assertEqual(value["selection"], "FULL_FALLBACK")
        self.assertEqual(value["document_count"], 3)

    def test_transitive_dependency_is_loaded(self):
        self.rows[0]["requires"] = ["work"]
        self.assertEqual(self.select()["document_count"], 2)

    def test_cycle_blocks_even_in_unselected_document(self):
        self.rows[2]["requires"] = ["archive"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.select()

    def test_missing_reference_blocks(self):
        self.rows[0]["requires"] = ["absent"]
        with self.assertRaisesRegex(ValueError, "missing document reference"):
            self.select()

    def test_changed_unselected_document_blocks(self):
        (self.root / "archive.md").write_text("changed")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.select()

    def test_duplicate_id_blocks(self):
        self.rows.append(deepcopy(self.rows[0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.select()

    def test_missing_always_rules_blocks(self):
        self.rows[0]["role"] = "PROCEDURE"
        with self.assertRaisesRegex(ValueError, "cross-cutting"):
            self.select()

    def test_candidate_manifest_cannot_replace_selected_policy(self):
        trusted = p.digest(self.manifest)
        self.manifest["repository_policy"] = {"weak": True}
        with self.assertRaisesRegex(ValueError, "changed document manifest"):
            p.select_documents(
                self.root, self.manifest, trusted, workstream="PROTOCOL", phase="START"
            )

    def test_unknown_condition_is_not_silently_ignored(self):
        self.rows[1]["phases"] = ["NOT_A_PHASE"]
        with self.assertRaisesRegex(ValueError, "reading condition"):
            self.select()

    def test_missing_file_blocks(self):
        (self.root / "work.md").unlink()
        with self.assertRaisesRegex(ValueError, "missing document"):
            self.select()

    def test_merge_denial_and_head_race_are_not_bypassed(self):
        for response, head in (
            ({"merged": False, "message": "protected"}, "a" * 40),
            ({"merged": True, "sha": "c" * 40}, "b" * 40),
        ):
            with self.subTest(response=response, head=head), self.assertRaises(ValueError):
                p.verify_merge_response(response, "a" * 40, head)

    def test_merge_success_still_requires_post_merge_proof(self):
        result = p.verify_merge_response({"merged": True, "sha": "b" * 40}, "a" * 40, "a" * 40)
        self.assertEqual(result["post_merge_verification"], "REQUIRED")

    def observation(self):
        return {
            "status": "OBSERVED",
            "observed_at": datetime.now(UTC).isoformat(),
            "complete": False,
            "response": {
                "sha": "a" * 40,
                "status": "completed",
                "conclusion": "failure",
                "user": {"noise": "x"},
            },
            "findings": ["failed attempt"],
            "uncertainties": ["incomplete inventory"],
        }

    def summary(self, observation):
        return p.evidence_summary(
            observation, {"id": "saved/observation", "sha256": p.digest(observation)}
        )

    def test_summary_preserves_failures_and_uncertainty(self):
        value = self.summary(self.observation())
        self.assertEqual(value["state"]["conclusion"], "failure")
        self.assertEqual(value["findings"], ["failed attempt"])
        self.assertFalse(value["complete"])
        self.assertFalse(value["push_qualified"])
        self.assertNotIn("user", json.dumps(value))

    def test_summary_cannot_reseal_different_observation(self):
        original = self.observation()
        expected = p.digest(original)
        original["response"]["conclusion"] = "success"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            p.evidence_summary(original, {"id": "saved/original", "sha256": expected})

    def test_raw_github_pr_summary_keeps_repository_base_and_head(self):
        observation = self.observation()
        observation["url"] = "https://api.github.com/repos/example/public/pulls/12"
        observation["response"] = {
            "number": 12,
            "state": "open",
            "base": {"sha": "a" * 40},
            "head": {"sha": "b" * 40, "repo": {"noise": "omitted"}},
        }
        value = self.summary(observation)
        self.assertEqual(
            value["identity"],
            {
                "number": 12,
                "repository": "example/public",
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
            },
        )
        self.assertEqual(value["qualification"], "NOT_EVALUATED")

    def test_stale_summary_retains_original_timestamp(self):
        value = self.observation()
        value["observed_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        result = self.summary(value)
        self.assertEqual(result["freshness"], "STALE")
        self.assertEqual(result["observed_at"], value["observed_at"])

    def test_error_payload_cannot_be_observed_success(self):
        value = self.observation()
        value["response"] = {"status": 403, "error": "denied"}
        self.assertEqual(self.summary(value)["status"], "UNKNOWN")

    def test_summary_requires_no_remote_administration_data(self):
        value = self.summary(self.observation())
        self.assertEqual(value["qualification"], "NOT_EVALUATED")

    def test_ci_unknown_scope_runs_all_suites(self):
        suites = {"code": ["core/a.py"], "protocol": ["tools/agent_protocol.py"]}
        for paths, complete in ((["unknown.py"], True), (["core/a.py"], False), ([], True)):
            value = p.ci_plan(paths, suites, complete=complete)
            self.assertTrue(value["full_fallback"])
            self.assertEqual(value["suites"], ["code", "protocol"])

    def test_ci_dependencies_select_and_never_elide_merge_tests(self):
        value = p.ci_plan(
            ["a.py"], {"a": ["a.py"], "b": ["b.py"]}, complete=True, merge_equivalent=True
        )
        self.assertEqual(value["suites"], ["a"])
        self.assertEqual(value["merge_tests"], "REQUIRED")
        self.assertFalse(value["push_qualified"])

    def test_ci_non_boolean_completeness_blocks(self):
        with self.assertRaises(ValueError):
            p.ci_plan(["a.py"], {"a": ["a.py"]}, complete="yes")

    def test_storage_sample_is_not_account_billing(self):
        result = p.storage_summary(
            [
                {"id": 1, "size_in_bytes": 100, "expired": False},
                {"id": 2, "size_in_bytes": 200, "expired": True},
            ],
            complete=False,
        )
        self.assertEqual(result["current_bytes"], 100)
        self.assertEqual(result["inventory"], "BOUNDED_SAMPLE")
        self.assertEqual(result["account_billing"], "NOT_OBSERVED")
        self.assertFalse(result["deletion_authorized"])

    def test_storage_duplicate_identity_blocks(self):
        row = {"id": 1, "size_in_bytes": 100, "expired": False}
        with self.assertRaises(ValueError):
            p.storage_summary([row, row], complete=True)

    def test_session_handoff_does_not_mutate_state(self):
        state = {
            "repository": "example/repository",
            "pr": 3,
            "head_sha": "a" * 40,
            "state": "RESUME_REQUIRED",
        }
        before = deepcopy(state)
        value = p.handoff(
            state,
            blocker="NONE",
            references=["archive:verified"],
            next_action="Restore evidence, collect fresh anchors and run preflight",
        )
        self.assertEqual(state, before)
        self.assertEqual(value["state_sha256"], p.digest(state))
        self.assertEqual(value["text"].count("Next action:"), 1)


if __name__ == "__main__":
    unittest.main()
