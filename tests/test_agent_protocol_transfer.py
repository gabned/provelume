"""Synthetic extraction failures never inspect a consumer or external repository."""

import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "transfer", Path(__file__).resolve().parents[1] / "tools/agent_protocol_transfer.py"
)
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)


def fixture():
    files = []
    observed = []
    for name in ["COMMERCIAL-LICENSE.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "tools/check.py"]:
        data = ("synthetic " + name).encode()
        row = {
            "source_path": name,
            "destination_path": name,
            "source_revision": "SOURCE",
            "mode": "100755" if name.endswith(".py") else "100644",
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_base64": None,
            "treatment": "KEEP",
        }
        files.append(row)
        observed.append(
            {"path": name, "mode": row["mode"], "content_base64": base64.b64encode(data).decode()}
        )
    manifest = {
        "schema": "agent-protocol-transfer/v1",
        "source_repository": "gabned/provelume",
        "source_commit": "a" * 40,
        "destination_repository": "gabned/agent-protocol",
        "destination_id": 123,
        "files": files,
        "future_paths": ["src/agent_protocol/cli.py"],
        "dependencies": ["Python standard library"],
        "initialization": "FULL_ROOT",
    }
    observation = {
        "repository": "gabned/agent-protocol",
        "repository_id": 123,
        "commit": "b" * 40,
        "parents": [],
        "files": observed,
        "seed": None,
    }
    return manifest, observation


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="protocol-maintenance-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.predecessor, self.destination = self.root / "predecessor", self.root / "destination"
        for root in (self.predecessor, self.destination):
            root.mkdir()
            self.git(root, "init", "-q")
            self.git(root, "config", "user.name", "Synthetic")
            self.git(root, "config", "user.email", "synthetic@example.invalid")
            self.git(root, "config", "core.autocrlf", "false")
        self.path = "compat/legacy/tools/runner.py"
        target = self.destination / self.path
        target.parent.mkdir(parents=True)
        target.write_bytes(b"before\n")
        (self.destination / "guard.py").write_text("unchanged gate\n")
        self.base = self.commit(self.destination)
        self.before = self.git(self.destination, "rev-parse", self.base + ":" + self.path)
        target.write_bytes(b"after\n")
        self.head = self.commit(self.destination)
        self.record = {
            "schema": "agent-protocol-maintenance/v1", "predecessor": "gabned/provelume",
            "repository": "gabned/agent-protocol", "repository_id": 1393711644, "pr": 4,
            "base": self.base, "head": self.head,
            "tree": self.git(self.destination, "rev-parse", self.head + "^{tree}"),
            "files": [{"path": self.path, "mode": "100644", "before_blob": self.before,
                       "after_blob": self.git(self.destination, "rev-parse",
                                              self.head + ":" + self.path),
                       "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}],
        }
        self.save_record()

    @staticmethod
    def git(root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args],
                                       stderr=subprocess.PIPE).decode().strip()

    def commit(self, root):
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "synthetic fixture")
        return self.git(root, "rev-parse", "HEAD")

    def save_record(self):
        path = self.predecessor / transfer.MAINTENANCE_DOCUMENT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            (transfer.MAINTENANCE_MARKER + json.dumps(self.record) + "\n```\n").encode("utf-8")
        )
        self.accepted = self.commit(self.predecessor)

    def verify(self, **overrides):
        args = {"accepted_predecessor": self.accepted, "repository": "gabned/agent-protocol",
                "repository_id": 1393711644, "pr": 4, "expected_base": self.base,
                "expected_head": self.head}
        args.update(overrides)
        return transfer.verify_maintenance(self.predecessor, self.destination, **args)

    def test_accepted_record_is_read_from_git_and_does_not_grant_merge_authority(self):
        (self.predecessor / transfer.MAINTENANCE_DOCUMENT).write_text("unaccepted working copy")
        result = self.verify()
        self.assertEqual(result["result"], "BYTES_VERIFIED")
        self.assertEqual(result["head"], self.head)
        self.assertFalse(result["merge_authorized"])
        self.assertFalse(result["publication_authorized"])

    def test_independent_destination_coordinates_cannot_be_reassigned(self):
        for field, value in (("repository", "different/repo"), ("repository_id", 123),
                             ("pr", 5), ("expected_base", "a" * 40),
                             ("expected_head", "b" * 40)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(**{field: value})

    def test_record_bytes_modes_and_complete_delta_are_required(self):
        original = copy.deepcopy(self.record)
        mutations = [
            lambda r: r.update(waiver=True),
            lambda r: r.update(tree="a" * 40),
            lambda r: r["files"][0].update(before_blob="a" * 40),
            lambda r: r["files"][0].update(after_blob="b" * 40),
            lambda r: r["files"][0].update(sha256="c" * 64),
            lambda r: r["files"][0].update(mode="100755"),
            lambda r: r["files"][0].update(path="tools/guard.py"),
            lambda r: r["files"].append(copy.deepcopy(r["files"][0])),
            lambda r: r.update(files=[]),
        ]
        for mutate in mutations:
            self.record = copy.deepcopy(original)
            mutate(self.record)
            self.save_record()
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.verify()

    def test_hidden_gate_change_cannot_hide_behind_listed_legacy_files(self):
        (self.destination / "guard.py").write_text("unexpected gate change\n")
        self.git(self.destination, "add", ".")
        self.git(self.destination, "commit", "--amend", "--no-edit", "-q")
        self.head = self.git(self.destination, "rev-parse", "HEAD")
        self.record.update(head=self.head,
                           tree=self.git(self.destination, "rev-parse", self.head + "^{tree}"))
        self.save_record()
        with self.assertRaisesRegex(ValueError, "incomplete or out of scope"):
            self.verify()

    def test_multiple_commits_and_replacement_history_are_refused(self):
        (self.destination / self.path).write_text("another change\n")
        newer = self.commit(self.destination)
        self.record.update(head=newer)
        self.save_record()
        with self.assertRaisesRegex(ValueError, "one direct successor"):
            self.verify(expected_head=newer)
        self.git(self.destination, "replace", newer, self.head)
        with self.assertRaisesRegex(ValueError, "Replaced history"):
            self.verify(expected_head=newer)

    def test_record_must_be_single_and_complete(self):
        for text in ("none", transfer.MAINTENANCE_MARKER + "{}",
                     transfer.MAINTENANCE_MARKER * 2,
                     transfer.MAINTENANCE_MARKER + '{"pr": 4, "pr": 5}\n```'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                transfer.read_maintenance_record(text)

    def test_shallow_history_is_not_complete_evidence(self):
        clone = self.root / "shallow"
        self.git(self.root, "clone", "--depth=1", self.destination.as_uri(), str(clone))
        self.destination = clone
        with self.assertRaisesRegex(ValueError, "Complete history"):
            self.verify()

    def test_public_cli_uses_accepted_record_and_refuses_caller_manifest(self):
        command = [sys.executable, str(Path(transfer.__file__)), "verify-maintenance",
                   "--source-root", str(self.predecessor), "--destination", str(self.destination),
                   "--accepted-predecessor", self.accepted, "--repository", "gabned/agent-protocol",
                   "--repository-id", "1393711644", "--pr", "4", "--expected-base", self.base,
                   "--expected-head", self.head]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "BYTES_VERIFIED")
        refused = subprocess.run([*command, "--manifest", "candidate.json"],
                                 capture_output=True, text=True, check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("accepted Git bytes only", refused.stdout)

        for option, absent in (("--accepted-predecessor", "a" * 40),
                               ("--destination", str(self.root / "absent"))):
            with self.subTest(unavailable=option):
                missing_command = command.copy()
                missing_command[command.index(option) + 1] = absent
                missing = subprocess.run(missing_command, capture_output=True,
                                         text=True, check=False)
                self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)
                self.assertEqual(json.loads(missing.stdout), {
                    "result": "BLOCKED", "reason": "Required Git evidence unavailable",
                })
                self.assertEqual(missing.stderr, "")


class TransferTests(unittest.TestCase):
    def test_missing_independent_history_blocks_destination_verification(self):
        manifest, observation = self.correction_fixture()
        with self.assertRaisesRegex(ValueError, "Independent authenticated"):
            self.verify(manifest, observation, accepted_history=None, trusted_history=None)

    def test_current_manifest_cannot_reassign_a_historical_qualification(self):
        manifest, observation = self.correction_fixture()
        for field in ["qualified_by", "manifest_sha256"]:
            changed = copy.deepcopy(manifest)
            changed["bootstrap_history"][0][field] = "9" * len(
                changed["bootstrap_history"][0][field]
            )
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "independently"):
                self.verify(changed, observation)

    def test_replaced_host_history_fails_its_independently_retained_digest(self):
        manifest, observation = self.correction_fixture()
        accepted = [
            {
                "source_repository": "gabned/provelume",
                "qualification_commit": "1" * 40,
                "manifest_sha256": "2" * 64,
                "destination_repository": "gabned/agent-protocol",
                "destination_id": 123,
                "destination_commit": "e" * 40,
                "destination_parent": "d" * 40,
                "destination_tree": "f" * 40,
            }
        ]
        trusted = transfer.digest(accepted)
        accepted[0]["qualification_commit"] = "9" * 40
        with self.assertRaisesRegex(ValueError, "Independent authenticated"):
            self.verify(manifest, observation, accepted_history=accepted, trusted_history=trusted)

    def correction_fixture(self):
        manifest, observation = fixture()
        manifest.update(
            schema="agent-protocol-transfer/v2",
            initialization="LICENSE_ONLY_ROOT",
            bootstrap_history=[
                {
                    "commit": "e" * 40,
                    "parent": "d" * 40,
                    "tree": "f" * 40,
                    "qualified_by": "1" * 40,
                    "manifest_sha256": "2" * 64,
                }
            ],
        )
        license_row = next(r for r in observation["files"] if r["path"] == "LICENSE")
        observation.update(
            seed={"commit": "d" * 40, "parents": [], "files": [license_row]},
            parents=["e" * 40],
            history=[{"commit": "e" * 40, "parents": ["d" * 40], "tree": "f" * 40}],
        )
        return manifest, observation

    def test_qualified_correction_appends_without_rewriting_initial_candidate(self):
        result = self.verify(*self.correction_fixture())
        self.assertEqual(result["schema"], "agent-protocol-transfer-receipt/v2")
        self.assertFalse(result["publication_authorized"])
        legacy = self.verify(*fixture())
        self.assertEqual(legacy["schema"], "agent-protocol-transfer-receipt/v1")

    def test_correction_requires_every_exact_predecessor_qualified_history_object(self):
        mutations = [
            lambda o: o["history"].clear(),
            lambda o: o["history"][0].update(tree="9" * 40),
            lambda o: o["history"][0].update(parents=["8" * 40]),
            lambda o: o.update(parents=["d" * 40]),
            lambda o: o.update(commit="d" * 40),
            lambda o: o.update(commit="e" * 40),
            lambda o: o["history"].append(copy.deepcopy(o["history"][0])),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                manifest, observation = self.correction_fixture()
                mutate(observation)
                with self.assertRaises(ValueError):
                    self.verify(manifest, observation)

    def test_self_selected_or_cyclic_bootstrap_history_cannot_grant_authority(self):
        manifest, observation = self.correction_fixture()
        trusted = transfer.digest(manifest)
        manifest["bootstrap_history"][0]["qualified_by"] = "9" * 40
        with self.assertRaisesRegex(ValueError, "Untrusted"):
            self.verify(manifest, observation, trusted)
        manifest["bootstrap_history"].append(
            {**manifest["bootstrap_history"][0], "commit": "d" * 40, "parent": "e" * 40}
        )
        with self.assertRaisesRegex(ValueError, "Cyclic"):
            self.verify(manifest, observation)

    def test_host_selected_predecessor_must_be_the_exact_byte_source(self):
        manifest, observation = fixture()
        with self.assertRaisesRegex(ValueError, "Source commit differs"):
            transfer.verify_destination(
                manifest,
                observation,
                trusted_manifest=transfer.digest(manifest),
                accepted_predecessor="c" * 40,
            )

    def test_authored_materialization_preserves_existing_bytes_and_is_idempotent(self):
        manifest, _ = fixture()
        # Applicable notices remain source rows; use the real accepted corpus for this host check.
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / ".github/agent-protocol/transfer-v1.5.0.json").read_text())
        trust = {
            "trusted_manifest": transfer.digest(manifest),
            "accepted_predecessor": manifest["source_commit"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            dest = Path(temporary) / "extraction"
            first = transfer.materialize(manifest, root, dest, **trust)
            second = transfer.materialize(manifest, root, dest, **trust)
            self.assertEqual(first, second)
            self.assertEqual(first["authority"], "NOT_GRANTED")
            (dest / "README.md").write_text("unsaved")
            with self.assertRaisesRegex(ValueError, "Existing bytes"):
                transfer.materialize(manifest, root, dest, **trust)
            self.assertEqual((dest / "README.md").read_text(), "unsaved")

    def test_repository_manifest_has_complete_committed_source_bytes(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / ".github/agent-protocol/transfer-v1.5.0.json").read_text())
        rows = []
        for row in sorted(
            (r for r in manifest["files"] if r["source_revision"] == "SOURCE"),
            key=lambda r: r["source_path"],
        ):
            name = row["source_path"]
            self.assertTrue(
                name
                in {
                    "AGENTS.md",
                    "LICENSE",
                    "COMMERCIAL-LICENSE.md",
                    "THIRD_PARTY_NOTICES.md",
                    "tools/__init__.py",
                    ".github/workflows/ci.yml",
                }
                or name.startswith(
                    (
                        "tools/agent_protocol",
                        "tests/test_agent_protocol",
                        "docs/agent-development-v",
                        ".github/agent-protocol/",
                    )
                )
            )
            argv = ["git", "-c", "safe.directory=" + root.as_posix(), "-C", str(root)]
            data = subprocess.check_output([*argv, "show", manifest["source_commit"] + ":" + name])
            meta = subprocess.check_output(
                [*argv, "ls-tree", manifest["source_commit"], "--", name]
            )
            mode = meta.decode().split()[0]
            rows.append(
                {"path": name, "mode": mode, "content_base64": base64.b64encode(data).decode()}
            )
        source = {
            "repository": manifest["source_repository"],
            "commit": manifest["source_commit"],
            "files": rows,
        }
        trust = {
            "trusted_manifest": transfer.digest(manifest),
            "accepted_predecessor": manifest["source_commit"],
        }
        self.assertEqual(
            transfer.verify_source(manifest, source, **trust)["result"], "SOURCE_BYTES_VERIFIED"
        )

    def verify(self, manifest, observation, trusted=None, **history):
        if manifest["schema"] == "agent-protocol-transfer/v2" and not history:
            # Independently selected synthetic predecessor receipt, not derived
            # from the candidate's bootstrap_history claims.
            accepted = [
                {
                    "source_repository": "gabned/provelume",
                    "qualification_commit": "1" * 40,
                    "manifest_sha256": "2" * 64,
                    "destination_repository": "gabned/agent-protocol",
                    "destination_id": 123,
                    "destination_commit": "e" * 40,
                    "destination_parent": "d" * 40,
                    "destination_tree": "f" * 40,
                }
            ]
            history = {"accepted_history": accepted, "trusted_history": transfer.digest(accepted)}
        return transfer.verify_destination(
            manifest,
            observation,
            trusted_manifest=trusted or transfer.digest(manifest),
            accepted_predecessor=manifest["source_commit"],
            **history,
        )

    def test_exact_transfer_is_byte_evidence_without_publication_authority(self):
        result = self.verify(*fixture())
        self.assertEqual(result["result"], "BYTES_VERIFIED")
        self.assertFalse(result["publication_authorized"])
        self.assertEqual(result["functional_qualification"], "REQUIRED")

    def test_wrong_repository_identity_history_bytes_mode_and_inventory_fail(self):
        mutations = [
            lambda o: o.update(repository="example/other"),
            lambda o: o.update(repository_id=321),
            lambda o: o.update(parents=["a" * 40]),
            lambda o: o["files"].pop(),
            lambda o: o["files"].append(copy.deepcopy(o["files"][0])),
            lambda o: o["files"][0].update(mode="100755"),
            lambda o: o["files"][0].update(content_base64="dGFtcGVy"),
            lambda o: o["files"].reverse(),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                manifest, observations = fixture()
                mutate(observations)
                with self.assertRaises(ValueError):
                    self.verify(manifest, observations)

    def test_candidate_cannot_replace_host_selected_manifest(self):
        manifest, observation = fixture()
        trusted = transfer.digest(manifest)
        manifest["future_paths"].append("tools/candidate.py")
        with self.assertRaisesRegex(ValueError, "Untrusted"):
            self.verify(manifest, observation, trusted)

    def test_path_collisions_traversal_and_wildcards_fail(self):
        for path in [
            "../other",
            "/absolute",
            "C:/outside",
            "tools\\bad.py",
            "tools//bad.py",
            "NUL.txt",
            "name.",
            "tools/*",
        ]:
            manifest, observation = fixture()
            manifest["future_paths"] = [path]
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.verify(manifest, observation)
        manifest, observation = fixture()
        manifest["files"].append({**manifest["files"][1], "destination_path": "license"})
        with self.assertRaises(ValueError):
            self.verify(manifest, observation)

    def test_applicable_license_cannot_be_rewritten_as_authored(self):
        manifest, observation = fixture()
        row = manifest["files"][1]
        row.update(
            source_path=None,
            source_revision="AUTHORED",
            content_base64=observation["files"][1]["content_base64"],
        )
        with self.assertRaisesRegex(ValueError, "notice"):
            self.verify(manifest, observation)

    def test_license_seed_cannot_import_application_history_or_add_other_bytes(self):
        manifest, observation = fixture()
        manifest["initialization"] = "LICENSE_ONLY_ROOT"
        license_row = next(r for r in observation["files"] if r["path"] == "LICENSE")
        observation["seed"] = {"commit": "d" * 40, "parents": [], "files": [license_row]}
        observation["parents"] = ["d" * 40]
        self.assertEqual(self.verify(manifest, observation)["result"], "BYTES_VERIFIED")
        observation["seed"]["parents"] = ["e" * 40]
        with self.assertRaises(ValueError):
            self.verify(manifest, observation)

    def test_source_revision_bytes_and_modes_are_bound(self):
        manifest, observation = fixture()
        source = {
            "repository": "gabned/provelume",
            "commit": "a" * 40,
            "files": copy.deepcopy(observation["files"]),
        }
        trust = {
            "trusted_manifest": transfer.digest(manifest),
            "accepted_predecessor": manifest["source_commit"],
        }
        self.assertEqual(
            transfer.verify_source(manifest, source, **trust)["result"], "SOURCE_BYTES_VERIFIED"
        )
        source["files"][0]["content_base64"] = "dGFtcGVy"
        with self.assertRaises(ValueError):
            transfer.verify_source(manifest, source, **trust)


if __name__ == "__main__":
    unittest.main()
