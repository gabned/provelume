"""Portable synthetic conformance; no network, private data or platform mutations."""

import hashlib
import importlib.util
import json
import subprocess
import sys
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

    def test_summary_rejects_raw_nested_payloads_and_oversized_annotations(self):
        for field in ("findings", "uncertainties"):
            for value in ({"raw": "x" * 1048576}, "x" * 1048576):
                observation = self.observation()
                observation[field] = [value]
                with self.subTest(field=field), self.assertRaises(ValueError):
                    self.summary(observation)

    def test_storage_completeness_requires_a_boolean(self):
        for value in ("false", "true", None, 0, 1, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "boolean"):
                p.storage_summary([], complete=value)

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


class DeliveryConformance(unittest.TestCase):
    """Synthetic host-selected evidence, never real editorial or production approval."""

    def setUp(self):
        self.now = datetime.now(UTC)
        self.start = (self.now - timedelta(minutes=1)).isoformat()
        self.end = (self.now + timedelta(minutes=10)).isoformat()
        self.item = dict(
            id="welcome",
            kind="TRANSLATION",
            language="it",
            source="Hello {name}",
            text="Ciao {name}",
            dependencies={"terminology": "a" * 64},
            fallback=False,
        )
        self.batch = dict(
            repository="example/project",
            catalog="ui",
            release="1.0",
            revision="r1",
            items=[self.item],
        )
        self.checks = dict(
            batch_sha256=p.digest(self.batch),
            checker="consumer-v1@sha",
            provenance="synthetic://checker",
            coverage=p.exact_items([self.item]),
            results={
                k: "PASS"
                for k in [
                    "coverage",
                    "placeholders",
                    "markup",
                    "escaping",
                    "pluralization",
                    "terminology",
                    "context",
                ]
            },
            exceptions=["Synthetic non-native linguistic assessment"],
        )
        self.policy = dict(
            repository="example/project", delegated_editorial=True, delegants=["maintainer"]
        )
        self.grant = dict(
            id="grant1",
            purpose="DELEGATED_EDITORIAL_APPROVAL",
            repository="example/project",
            catalog="ui",
            release="1.0",
            revision="r1",
            batch_sha256=p.digest(self.batch),
            items=p.exact_items([self.item]),
            checks_sha256=p.digest(self.checks),
            policy_sha256=p.digest(self.policy),
            delegant="maintainer",
            executor="agent",
            provenance="synthetic://grant",
            not_before=self.start,
            expires_at=self.end,
            revoked=False,
            conditions={"valid_complete_batch": True, "no_publication": True},
            accepted_exceptions=self.checks["exceptions"],
        )
        self.identity = dict(
            repository="example/project",
            release="1.0",
            candidate_sha="a" * 40,
            artifact_sha256="b" * 64,
            effects_sha256="c" * 64,
            inputs_sha256="d" * 64,
            audience="STAFF",
            shared_impacts_sha256="e" * 64,
        )
        self.conditions = {"catalog": "ready", "configuration": "ready"}
        self.deploy_grant = dict(
            id="deploy1",
            purpose="PRODUCTION",
            identity=self.identity,
            allowed_conditions_sha256=[p.digest(self.conditions)],
            not_before=self.start,
            expires_at=self.end,
            revoked=False,
            partial_retry=False,
            procedure="existing/runbook",
            provenance="synthetic://production-consent",
        )

    def test_semantic_documents_keep_mixed_runtime_effect_and_unknowns(self):
        registry = {
            "docs/roadmap.md": "PLANNING",
            "AGENTS.md": "POLICY",
            "app/content.md": "RUNTIME",
            "docs/guide.md": "DOCUMENTATION",
        }
        first = p.classify_document_effects(["docs/roadmap.md"], registry, p.digest(registry))
        self.assertEqual(first["effect"], "NO_PRODUCTION")
        self.assertEqual(first["scope"], "NOT_INFERRED")
        mixed = p.classify_document_effects(
            ["app/content.md", "docs/new.md"], registry, p.digest(registry)
        )
        self.assertEqual(mixed["effect"], "UNKNOWN")
        self.assertEqual(mixed["known_effect"], "PRODUCTION")
        with self.assertRaises(ValueError):
            p.classify_document_effects(["AGENTS.md"], registry, "f" * 64)

    def test_retention_requires_authoritative_copy_and_preserves_audit(self):
        policy = dict(
            minimum_days={"TRANSIENT": 7, "AUDIT": 90},
            cache_authoritative=False,
            deletion_authorized=False,
        )
        row = dict(id="artifact1", purpose="AUDIT", retention_days=90, durable_copy=True)
        self.assertEqual(p.retention_plan([row], policy, p.digest(policy))["deletions"], [])
        for delta in [{"retention_days": 7}, {"durable_copy": False}, {"purpose": "UNKNOWN"}]:
            with self.assertRaises(ValueError):
                p.retention_plan([{**row, **delta}], policy, p.digest(policy))

    def approve(self, grant=None, trusted=True):
        grant = self.grant if grant is None else grant
        return p.delegated_approval(
            self.batch,
            self.checks,
            grant,
            self.policy,
            trusted_grants=[p.digest(grant)] if trusted else [],
            trusted_checks=[p.digest(self.checks)],
            policy_digest=p.digest(self.policy),
            executor="agent",
            now=self.now,
        )

    def test_delegation_is_automatic_not_human_and_not_publication(self):
        result = self.approve()
        self.assertEqual(result["state"], "APPROVED_AUTOMATIC_DELEGATED")
        self.assertFalse(result["human_review"])
        self.assertFalse(result["publication_authorized"])

    def test_missing_revoked_expired_out_of_scope_and_unknown_role_fail(self):
        with self.assertRaises(ValueError):
            self.approve(trusted=False)
        for field, value in [
            ("revoked", True),
            ("expires_at", self.start),
            ("release", "2.0"),
            ("catalog", "other"),
            ("revision", "r2"),
            ("delegant", "stranger"),
            ("executor", "other"),
            ("purpose", "HUMAN_REVIEW"),
            ("accepted_exceptions", []),
        ]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.approve({**self.grant, field: value})

    def test_missing_changed_fallback_invalid_and_unchecked_text_fail(self):
        for field, value in [
            ("text", ""),
            ("text", "Changed"),
            ("fallback", True),
            ("language", "fr"),
            ("dependencies", {"terminology": "f" * 64}),
        ]:
            previous = deepcopy(self.batch)
            self.batch["items"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.approve()
            self.batch = previous
        for key in self.checks["results"]:
            old = self.checks["results"][key]
            self.checks["results"][key] = "FAIL"
            with self.subTest(check=key), self.assertRaises(ValueError):
                self.approve()
            self.checks["results"][key] = old
        self.checks["coverage"] = []
        with self.assertRaises(ValueError):
            self.approve()

    def test_policy_must_be_adopted_first(self):
        self.policy["delegated_editorial"] = False
        with self.assertRaisesRegex(ValueError, "prior policy"):
            self.approve()

    def test_public_cli_requires_independently_supplied_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = dict(
                batch=self.batch,
                checks=self.checks,
                grant=self.grant,
                policy=self.policy,
                executor="agent",
            )
            trusted = dict(
                trusted_grants=[p.digest(self.grant)],
                trusted_checks=[p.digest(self.checks)],
                policy_digest=p.digest(self.policy),
            )
            (root / "input.json").write_text(json.dumps(data))
            command = [
                sys.executable,
                str(ROOT / "tools/agent_protocol_v1_4_7.py"),
                "delegated-approval",
                "--input",
                str(root / "input.json"),
                "--trusted",
                str(root / "trusted.json"),
            ]
            for grants, expected in [(trusted["trusted_grants"], 0), ([], 2)]:
                (root / "trusted.json").write_text(
                    json.dumps({**trusted, "trusted_grants": grants})
                )
                result = subprocess.run(command, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_unchanged_approvals_retained_only_changed_dependency_invalidated(self):
        other = {**self.item, "id": "welcome2"}
        old = [self.item, other]
        approvals = [
            {"item": i, "approval_reference": "prior://approval"} for i in p.exact_items(old)
        ]
        new = [self.item, {**other, "dependencies": {"terminology": "f" * 64}}]
        result = p.preserved_approvals(old, new, approvals)
        self.assertEqual(len(result["retained"]), 1)
        self.assertEqual(len(result["invalidated"]), 1)
        self.assertEqual(result["new_approvals"], [])

    def reuse(self, identity=None, conditions=None, grant=None, prior="NONE"):
        grant = self.deploy_grant if grant is None else grant
        return p.authorization_reuse(
            identity or self.identity,
            conditions or self.conditions,
            grant,
            trusted_grants=[p.digest(grant)],
            now=self.now,
            prior_effects=prior,
        )

    def test_same_sha_operational_change_requires_condition_coverage(self):
        self.assertEqual(self.reuse()["authorization"], "COVERED")
        with self.assertRaisesRegex(ValueError, "operational change"):
            self.reuse(conditions={"catalog": "changed", "configuration": "ready"})
        changed = {"catalog": "ready", "configuration": "repaired"}
        grant = {**self.deploy_grant, "allowed_conditions_sha256": [p.digest(changed)]}
        self.assertEqual(self.reuse(conditions=changed, grant=grant)["authorization"], "COVERED")

    def test_changed_candidate_artifact_effects_inputs_audience_need_new_binding(self):
        for key in self.identity:
            value = "f" * (40 if key == "candidate_sha" else 64) if "sha" in key else "changed"
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.reuse(identity={**self.identity, key: value})

    def test_editorial_consent_never_deploys_and_failure_does_not_revoke(self):
        with self.assertRaises(ValueError):
            self.reuse(grant={**self.deploy_grant, "purpose": "DELEGATED_EDITORIAL_APPROVAL"})
        self.assertEqual(self.reuse(prior="NONE")["authorization"], "COVERED")
        for state in ["PARTIAL", "UNKNOWN", "COMPLETED"]:
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.reuse(prior=state)
        self.assertEqual(
            self.reuse(prior="PARTIAL", grant={**self.deploy_grant, "partial_retry": True})[
                "authorization"
            ],
            "COVERED",
        )

    def test_readiness_aggregates_blockers_and_keeps_ci_separate(self):
        def observation(phase, status):
            return dict(
                phase=phase,
                identity_sha256=p.digest(self.identity),
                status=status,
                cause="synthetic cause",
                elements=["synthetic item"],
                effects="unknown",
                next_action="read-only diagnostic",
                evidence="synthetic://evidence",
                event_at=self.start,
                observed_at=self.start,
                recorded_at=self.start,
            )

        rows = [
            observation("CODE", "PASS"),
            observation("DATA", "BLOCKED"),
            observation("CONFIGURATION", "BLOCKED"),
        ]
        result = p.readiness(self.identity, rows, trusted_observations=[p.digest(r) for r in rows])
        self.assertEqual(result["phases"]["CODE"], "PASS")
        self.assertEqual(len(result["blockers"]), 9)
        self.assertFalse(result["ready_for_final_consent"])
        self.assertFalse(result["production_executed"])

    def recovery(self, state="PARTIAL", **kwargs):
        row = dict(
            identity=self.identity,
            state=state,
            completed=["migration1"],
            remaining=["publish"],
            reconciled=True,
            bookkeeping="PASS",
            procedure="existing/recovery",
            event_at=self.start,
            observed_at=self.start,
            recorded_at=self.now.isoformat(),
            **{},
        )
        row.update(kwargs)
        return p.recovery_plan(row, trusted_observations=[p.digest(row)])

    def test_partial_recovery_is_idempotent_and_never_repeats_completed_effects(self):
        first = self.recovery()
        self.assertEqual(first, self.recovery())
        self.assertEqual(first["never_repeat"], ["migration1"])
        self.assertEqual(first["eligible_for_qualification"], ["publish"])
        self.assertFalse(first["mutation_authorized"])
        self.assertFalse(first["retroactive_approval"])

    def test_unknown_monitoring_and_bookkeeping_failures_differ(self):
        self.assertEqual(self.recovery("UNKNOWN")["next_action"], "RECONCILE_READ_ONLY")
        self.assertEqual(
            self.recovery("MONITORING_FAILED", remaining=[])["next_action"], "VERIFY_COMPLETED"
        )
        self.assertEqual(self.recovery(bookkeeping="FAILED")["eligible_for_qualification"], [])
        with self.assertRaises(ValueError):
            self.recovery("BEFORE_EFFECTS")

    def test_absent_staging_staff_and_user_pc(self):
        env = dict(
            staging="ABSENT",
            staging_result="NOT_APPLICABLE",
            target="PRODUCTION",
            audience="STAFF",
            server_authorization="VERIFIED",
            shared_impacts="database",
            ui_capabilities={"pre_deploy": [], "post_deploy": ["mobile pending"]},
            emergency_procedure="existing/emergency",
        )
        self.assertTrue(p.environment_plan(env)["staff_is_production"])
        self.assertFalse(p.environment_plan(env)["rollback_assumed"])
        self.assertEqual(
            p.environment_plan({**env, "target": "USER_PC"})["next"],
            "PREPARE_BUILD_AND_INSTRUCTIONS",
        )
        for delta in [
            {"staging": "CONFIGURED", "staging_result": "FAIL"},
            {"server_authorization": "HIDDEN_LINK"},
        ]:
            with self.assertRaises(ValueError):
                p.environment_plan({**env, **delta})

    def test_intervention_requires_concrete_preparation_and_link(self):
        request = dict(
            kind="MATERIAL",
            reason="user PC test",
            rule_source="accepted policy",
            action="Install prepared build",
            url="https://example.com/releases/1.0",
            navigation=[],
            inputs={"sha": "a" * 40},
            expected_result="connection test",
            prepared_result="build and instructions",
            agent_can_execute=False,
        )
        self.assertEqual(p.human_intervention(request)["after_done"], "OBSERVE_RESULT_BOUNDED")
        for delta in [
            {"agent_can_execute": True},
            {"url": ""},
            {"prepared_result": ""},
            {"url": "https://user:secret@example.com"},
            {"kind": "VAGUE_BLOCKER"},
        ]:
            with self.assertRaises(ValueError):
                p.human_intervention({**request, **delta})

    def test_thread_inventory_rejects_missing_pages_comments_or_counts(self):
        pr = {"review_comments": 1}
        thread = {"id": "thread1", "is_resolved": True, "comments": [{"database_id": 1}]}
        result = p.review_inventory(pr, [thread], [[{"id": 1}]], [[]])
        self.assertTrue(result["complete"])
        for threads, pages in [
            ([], [[{"id": 1}]]),
            ([thread], [[]]),
            ([thread], []),
            ([thread, thread], [[{"id": 1}]]),
        ]:
            with self.assertRaises(ValueError):
                p.review_inventory(pr, threads, pages, [[]])

    def test_closure_requires_criteria_and_deduplicates_verified_steps(self):
        steps = ["POST_DEPLOY", "CERTIFY", "CHECKPOINT", "ROADMAP", "ISSUES", "HANDOFF"]
        scope = dict(
            repository=self.identity["repository"],
            release="1.0",
            identity=self.identity,
            issues=["#1"],
            steps=steps,
        )
        evidence = dict(
            scope_sha256=p.digest(scope),
            identity_sha256=p.digest(self.identity),
            criteria={"behavior": "PASS"},
            issues={"#1": "CRITERIA_MET"},
            steps={k: "PENDING" for k in steps},
        )

        def plan(completed=()):
            return p.closure_plan(
                scope,
                evidence,
                trusted_scope=[p.digest(scope)],
                trusted_evidence=[p.digest(evidence)],
                completed_keys=completed,
            )

        first = plan()
        self.assertEqual(first, plan())
        self.assertEqual(first["next_action"][0]["step"], "POST_DEPLOY")
        evidence["steps"] = {k: "VERIFIED" for k in steps}
        self.assertTrue(plan([a["idempotency_key"] for a in first["remaining"]])["complete"])
        evidence["criteria"]["behavior"] = "PENDING"
        with self.assertRaises(ValueError):
            plan()


if __name__ == "__main__":
    unittest.main()
