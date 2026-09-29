"""Synthetic extraction failures never inspect a consumer or external repository."""

import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
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
        trust = {"trusted_manifest": transfer.digest(manifest), "accepted_predecessor": "c" * 40}
        self.assertEqual(
            transfer.verify_source(manifest, source, **trust)["result"], "SOURCE_BYTES_VERIFIED"
        )

    def verify(self, manifest, observation, trusted=None):
        return transfer.verify_destination(
            manifest,
            observation,
            trusted_manifest=trusted or transfer.digest(manifest),
            accepted_predecessor="c" * 40,
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
        trust = {"trusted_manifest": transfer.digest(manifest), "accepted_predecessor": "c" * 40}
        self.assertEqual(
            transfer.verify_source(manifest, source, **trust)["result"], "SOURCE_BYTES_VERIFIED"
        )
        source["files"][0]["content_base64"] = "dGFtcGVy"
        with self.assertRaises(ValueError):
            transfer.verify_source(manifest, source, **trust)


if __name__ == "__main__":
    unittest.main()
