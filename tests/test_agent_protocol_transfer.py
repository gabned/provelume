"""Synthetic extraction failures never inspect a consumer or external repository."""

import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
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
