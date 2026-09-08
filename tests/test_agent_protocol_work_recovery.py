"""Synthetic recovery/adoption regressions; no private operational evidence."""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "work_recovery", ROOT / "tools/agent_protocol_work_recovery.py"
)
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


def make_evidence(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "observation.json").write_text('{"observed_at":"2026-01-01T00:00:00Z"}\n')
    (root / "instruction.txt").write_bytes(b"  Actual user instruction.\r\n")
    (root / "binary").write_bytes(bytes(range(256)))
    archive = tmp_path / "recovery.zip"
    result = recovery.recovery_export(
        root, ["binary", "instruction.txt", "observation.json"], archive
    )
    return (root, archive, result["archive_sha256"])


def rewrite(archive, mutate):
    with zipfile.ZipFile(archive) as old:
        records = {n: old.read(n) for n in old.namelist()}
    manifest = json.loads(records["manifest.json"])
    mutate(manifest, records)
    records["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(archive, "w") as new:
        for name, data in records.items():
            new.writestr(name, data)
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def command(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


def make_adoption(tmp_path):
    canonical, target = (tmp_path / "canonical", tmp_path / "target")
    for root, repo in ((canonical, "gabned/provelume"), (target, "gabned/provelume.com")):
        root.mkdir()
        command(root, "init", "-q")
        command(root, "config", "core.autocrlf", "false")
        command(root, "config", "user.name", "Synthetic fixture")
        command(root, "config", "user.email", "fixture@example.invalid")
        command(root, "remote", "add", "origin", f"https://github.com/{repo}.git")
    for path in (*recovery.ops.VENDOR_FILES, *recovery.WORK_FILES):
        dest = canonical / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, dest)
        dest.chmod(493 if recovery.ops.VENDOR_FILES.get(path) == "100755" else 420)
    command(canonical, "add", ".")
    for path, mode in recovery.ops.VENDOR_FILES.items():
        command(
            canonical, "update-index", "--chmod=" + ("+x" if mode == "100755" else "-x"), "--", path
        )
    command(canonical, "commit", "-qm", "Synthetic canonical source")
    sha = command(canonical, "rev-parse", "HEAD")
    recovery.ops.sync_vendor(canonical, target, sha)
    (target / "tests").mkdir()
    (target / "tests/agent_protocol_v1_4_2_vendor_test.py").write_text(
        "EXPECTED_MANIFEST = {}\nWORK_ADAPTER_PIN = {}\nUNCHANGED = 'history'\n"
    )
    (target / "AGENTS.md").write_text("# Synthetic guidance\nHistorical pin stays here.\n")
    (target / "docs/agent-development-v1.4.2.md").write_text("# Historical guide\n")
    return (canonical, target, sha)


class RecoveryConformance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="recovery-conformance-")
        self.addCleanup(temporary.cleanup)
        self.tmp_path = Path(temporary.name)

    def patch(self, target, name, value):
        replacement = patch.object(target, name, value)
        self.addCleanup(replacement.stop)
        return replacement.start()

    def test_recovery_after_complete_workspace_loss_preserves_bytes_and_not_authority(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        root, archive, sha = evidence
        expected = {p.name: p.read_bytes() for p in root.iterdir()}
        shutil.rmtree(root)
        dest = tmp_path / "restored"
        result = recovery.recovery_restore(archive, sha, dest)
        assert {p.name: p.read_bytes() for p in dest.iterdir()} == expected
        assert result == {
            "restored_files": 3,
            "authority": "NOT_GRANTED",
            "fresh_observations_required": True,
            "push_qualified": False,
        }

    def test_archive_requires_independent_digest_and_never_overwrites(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        root, archive, sha = evidence
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            recovery.recovery_restore(archive, "f" * 64, tmp_path / "no-output")
        assert not (tmp_path / "no-output").exists()
        with self.assertRaises(FileExistsError):
            recovery.recovery_export(root, ["binary"], archive)
        with self.assertRaises(FileExistsError):
            recovery.recovery_restore(archive, sha, root)

    def test_archive_rejects_unsafe_manifest_paths_before_output_0(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        name = "../escape"
        _, archive, _ = evidence
        sha = rewrite(archive, lambda m, _: m["files"][0].update(path=name))
        with self.assertRaises(ValueError):
            recovery.recovery_restore(archive, sha, tmp_path / "output")
        assert not (tmp_path / "output").exists()

    def test_archive_rejects_unsafe_manifest_paths_before_output_1(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        name = "/absolute"
        _, archive, _ = evidence
        sha = rewrite(archive, lambda m, _: m["files"][0].update(path=name))
        with self.assertRaises(ValueError):
            recovery.recovery_restore(archive, sha, tmp_path / "output")
        assert not (tmp_path / "output").exists()

    def test_archive_rejects_unsafe_manifest_paths_before_output_2(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        name = "a\\b"
        _, archive, _ = evidence
        sha = rewrite(archive, lambda m, _: m["files"][0].update(path=name))
        with self.assertRaises(ValueError):
            recovery.recovery_restore(archive, sha, tmp_path / "output")
        assert not (tmp_path / "output").exists()

    def test_archive_rejects_unsafe_manifest_paths_before_output_3(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        name = ".git/config"
        _, archive, _ = evidence
        sha = rewrite(archive, lambda m, _: m["files"][0].update(path=name))
        with self.assertRaises(ValueError):
            recovery.recovery_restore(archive, sha, tmp_path / "output")
        assert not (tmp_path / "output").exists()

    def test_archive_rejects_unsafe_manifest_paths_before_output_4(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        name = "C:drive"
        _, archive, _ = evidence
        sha = rewrite(archive, lambda m, _: m["files"][0].update(path=name))
        with self.assertRaises(ValueError):
            recovery.recovery_restore(archive, sha, tmp_path / "output")
        assert not (tmp_path / "output").exists()

    def test_archive_rejects_unsafe_manifest_paths_before_output_5(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        name = "CON"
        _, archive, _ = evidence
        sha = rewrite(archive, lambda m, _: m["files"][0].update(path=name))
        with self.assertRaises(ValueError):
            recovery.recovery_restore(archive, sha, tmp_path / "output")
        assert not (tmp_path / "output").exists()

    def test_archive_rejects_unsafe_manifest_paths_before_output_6(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        name = "nul.txt"
        _, archive, _ = evidence
        sha = rewrite(archive, lambda m, _: m["files"][0].update(path=name))
        with self.assertRaises(ValueError):
            recovery.recovery_restore(archive, sha, tmp_path / "output")
        assert not (tmp_path / "output").exists()

    def test_archive_rejects_unsafe_manifest_paths_before_output_7(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        name = "a."
        _, archive, _ = evidence
        sha = rewrite(archive, lambda m, _: m["files"][0].update(path=name))
        with self.assertRaises(ValueError):
            recovery.recovery_restore(archive, sha, tmp_path / "output")
        assert not (tmp_path / "output").exists()

    def test_archive_rejects_unsafe_manifest_paths_before_output_8(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        name = "a "
        _, archive, _ = evidence
        sha = rewrite(archive, lambda m, _: m["files"][0].update(path=name))
        with self.assertRaises(ValueError):
            recovery.recovery_restore(archive, sha, tmp_path / "output")
        assert not (tmp_path / "output").exists()

    def test_archive_rejects_unsafe_manifest_paths_before_output_9(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        name = "a?b"
        _, archive, _ = evidence
        sha = rewrite(archive, lambda m, _: m["files"][0].update(path=name))
        with self.assertRaises(ValueError):
            recovery.recovery_restore(archive, sha, tmp_path / "output")
        assert not (tmp_path / "output").exists()

    def test_archive_rejects_case_aliased_parent_directories(self):
        with self.assertRaisesRegex(ValueError, "case-aliased directory"):
            recovery.entries(["A/one", "a/two"])

    @unittest.skipIf(os.name != "posix", "existing Work source route requires POSIX modes")
    def test_work_adoption_preserves_baseline_and_rejects_moved_default(self):
        tmp_path = self.tmp_path
        adoption = make_adoption(tmp_path)
        canonical, native, sha = adoption
        baseline, candidate = (tmp_path / "baseline", tmp_path / "candidate")
        shutil.copytree(native, baseline, ignore=shutil.ignore_patterns(".git"))
        shutil.copytree(baseline, candidate)
        entries = recovery.source.inventory(baseline)
        tree = recovery.source.tree_identity(entries, verify=True)
        repo, base = ("gabned/provelume.com", "a" * 40)
        snapshot = {
            "schema": recovery.source.SCHEMA,
            "repository": repo,
            "commit_sha": base,
            "tree_sha": tree,
            "tree": {"sha": tree, "truncated": False, "tree": list(entries.values())},
        }
        prefix = "https://api.github.com/repos/" + repo

        def observation(endpoint, response):
            return {
                "url": prefix + endpoint,
                "observed_at": datetime.now(UTC).isoformat(),
                "response": response,
            }

        ref = {"ref": "refs/heads/main", "object": {"type": "commit", "sha": base}}
        anchor = {
            "default_branch": "main",
            "repository": observation("", {"full_name": repo, "default_branch": "main"}),
            "before": observation("/git/ref/heads/main", ref),
            "commit": observation("/git/commits/" + base, {"sha": base, "tree": {"sha": tree}}),
            "after": observation("/git/ref/heads/main", ref),
        }
        work = (snapshot, baseline, anchor)
        result = recovery.sync_adopter(canonical, candidate, sha, repo, work=work)
        assert result["changed_paths"] and (not (candidate / ".git").exists())
        recovery.source.verify_source(snapshot, baseline, repo, base)
        assert (
            recovery.sync_adopter(canonical, candidate, sha, repo, work=work)["changed_paths"] == []
        )
        before = {p: p.read_bytes() for p in candidate.rglob("*") if p.is_file()}
        anchor["after"]["response"] = {
            "ref": "refs/heads/main",
            "object": {"type": "commit", "sha": "b" * 40},
        }
        with self.assertRaisesRegex(ValueError, "default branch moved"):
            recovery.sync_adopter(canonical, candidate, sha, repo, work=work)
        assert before == {p: p.read_bytes() for p in candidate.rglob("*") if p.is_file()}

    def test_archive_rejects_tampering_even_with_matching_outer_hash_0(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)

        def mutate(m, r):
            return m.update(push_qualified=True)

        _, archive, _ = evidence
        sha = rewrite(archive, mutate)
        with self.assertRaises(ValueError):
            recovery.recovery_verify(archive, sha)

    def test_archive_rejects_tampering_even_with_matching_outer_hash_1(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)

        def mutate(m, r):
            return m.update(authority="APPROVED")

        _, archive, _ = evidence
        sha = rewrite(archive, mutate)
        with self.assertRaises(ValueError):
            recovery.recovery_verify(archive, sha)

    def test_archive_rejects_tampering_even_with_matching_outer_hash_2(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)

        def mutate(m, r):
            return m.update(fresh_observations_required=False)

        _, archive, _ = evidence
        sha = rewrite(archive, mutate)
        with self.assertRaises(ValueError):
            recovery.recovery_verify(archive, sha)

    def test_archive_rejects_tampering_even_with_matching_outer_hash_3(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)

        def mutate(m, r):
            return m["files"][0].update(mode="120000")

        _, archive, _ = evidence
        sha = rewrite(archive, mutate)
        with self.assertRaises(ValueError):
            recovery.recovery_verify(archive, sha)

    def test_archive_rejects_tampering_even_with_matching_outer_hash_4(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)

        def mutate(m, r):
            return r.update({"objects/0": b"corrupt"})

        _, archive, _ = evidence
        sha = rewrite(archive, mutate)
        with self.assertRaises(ValueError):
            recovery.recovery_verify(archive, sha)

    def test_archive_rejects_tampering_even_with_matching_outer_hash_5(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)

        def mutate(m, r):
            return r.update({"unlisted": b"hidden"})

        _, archive, _ = evidence
        sha = rewrite(archive, mutate)
        with self.assertRaises(ValueError):
            recovery.recovery_verify(archive, sha)

    def test_archive_rejects_tampering_even_with_matching_outer_hash_6(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)

        def mutate(m, r):
            return m["files"][1].update(path="binary")

        _, archive, _ = evidence
        sha = rewrite(archive, mutate)
        with self.assertRaises(ValueError):
            recovery.recovery_verify(archive, sha)

    def test_expanded_limit_rejects_zip_before_extracting(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        _, archive, sha = evidence
        self.patch(recovery.source, "MAX_BLOB", 10)
        with self.assertRaisesRegex(ValueError, "expanded size"):
            recovery.recovery_verify(archive, sha)

    def test_duplicate_zip_member_rejected(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        _, archive, _ = evidence
        with zipfile.ZipFile(archive, "a") as stream, self.assertWarns(UserWarning):
            stream.writestr("objects/0", b"duplicate")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            recovery.recovery_verify(archive, hashlib.sha256(archive.read_bytes()).hexdigest())

    @unittest.skipIf(os.name != "posix", "POSIX symlink permissions")
    def test_source_symlinks_and_destination_parent_links_rejected(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        root, archive, sha = evidence
        (root / "link").symlink_to(root / "binary")
        with self.assertRaisesRegex(ValueError, "symlink"):
            recovery.recovery_export(root, ["link"], tmp_path / "bad.zip")
        (tmp_path / "parent-link").symlink_to(root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            recovery.recovery_restore(archive, sha, tmp_path / "parent-link/new")

    def test_restore_failure_removes_only_new_destination(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        _, archive, sha = evidence
        original = recovery.regular

        def fail(root, path):
            if path == "instruction.txt":
                raise OSError("disk failure")
            return original(root, path)

        self.patch(recovery, "regular", fail)
        with self.assertRaisesRegex(OSError, "disk failure"):
            recovery.recovery_restore(archive, sha, tmp_path / "partial")
        assert not (tmp_path / "partial").exists()

    def test_adoption_updates_every_current_identity_and_is_idempotent(self):
        tmp_path = self.tmp_path
        adoption = make_adoption(tmp_path)
        canonical, target, sha = adoption
        original = (target / "AGENTS.md").read_text()
        preview = recovery.sync_adopter(canonical, target, sha, "gabned/provelume.com", check=True)
        assert (target / "AGENTS.md").read_text() == original
        result = recovery.sync_adopter(canonical, target, sha, "gabned/provelume.com")
        assert result["changed_paths"] == preview["changed_paths"]
        assert (target / "AGENTS.md").read_text().startswith(original)
        guard = (target / "tests/agent_protocol_v1_4_2_vendor_test.py").read_text()
        assert "UNCHANGED = 'history'" in guard
        assert sha in guard and "agent_protocol_work_recovery.py" in guard
        again = recovery.sync_adopter(canonical, target, sha, "gabned/provelume.com")
        assert again["changed_paths"] == []
        assert not again["push_qualified"]

    def test_adoption_rollback_preserves_all_original_bytes(self):
        tmp_path = self.tmp_path
        adoption = make_adoption(tmp_path)
        canonical, target, sha = adoption
        _, plan = recovery.adoption_plan(canonical, target, sha, "gabned/provelume.com")
        before = {p: (target / p).read_bytes() for p in plan}
        replace = recovery.os.replace
        calls = 0

        def fail(src, dst):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected replacement failure")
            replace(src, dst)

        self.patch(recovery.os, "replace", fail)
        with self.assertRaisesRegex(OSError, "injected"):
            recovery.sync_adopter(canonical, target, sha, "gabned/provelume.com")
        assert before == {p: (target / p).read_bytes() for p in plan}

    def test_adoption_rechecks_vendor_bytes_after_manifest_read(self):
        tmp_path = self.tmp_path
        adoption = make_adoption(tmp_path)
        canonical, target, sha = adoption
        manifest = recovery.ops.manifest
        before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}

        def changed(*args):
            result = manifest(*args)
            vendor = canonical / next(iter(recovery.ops.VENDOR_FILES))
            vendor.write_bytes(vendor.read_bytes() + b"\n# changed after manifest\n")
            return result

        self.patch(recovery.ops, "manifest", changed)
        with self.assertRaisesRegex(ValueError, "canonical source changed"):
            recovery.sync_adopter(canonical, target, sha, "gabned/provelume.com")
        assert before == {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}

    @unittest.skipIf(os.name != "posix", "POSIX read-only destination replacement")
    def test_adoption_rollback_atomically_restores_read_only_destination(self):
        tmp_path = self.tmp_path
        adoption = make_adoption(tmp_path)
        canonical, target, sha = adoption
        preview = recovery.sync_adopter(canonical, target, sha, "gabned/provelume.com", check=True)
        first = target / preview["changed_paths"][0]
        first.chmod(256)
        original = first.read_bytes()
        replace, calls = (recovery.os.replace, [])

        def fail_second(src, dst):
            calls.append(Path(dst))
            if len(calls) == 2:
                raise OSError("injected second replacement")
            replace(src, dst)

        def no_inplace_write(path, data):
            raise AssertionError("rollback must not write the destination in place")

        self.patch(recovery.os, "replace", fail_second)
        write_bytes = Path.write_bytes
        self.patch(
            Path,
            "write_bytes",
            lambda p, b: no_inplace_write(p, b) if p == first else write_bytes(p, b),
        )
        with self.assertRaisesRegex(OSError, "injected second"):
            recovery.sync_adopter(canonical, target, sha, "gabned/provelume.com")
        assert calls == [first, target / preview["changed_paths"][1], first]
        assert first.read_bytes() == original and stat.S_IMODE(first.stat().st_mode) == 256

    def test_adoption_wrong_target_or_dirty_canonical_cannot_write(self):
        tmp_path = self.tmp_path
        adoption = make_adoption(tmp_path)
        canonical, target, sha = adoption
        with self.assertRaisesRegex(ValueError, "target repository"):
            recovery.sync_adopter(canonical, target, sha, "brickms/brickms")
        (canonical / "untracked").write_text("modified source")
        with self.assertRaisesRegex(ValueError, "dirty"):
            recovery.sync_adopter(canonical, target, sha, "gabned/provelume.com")

    def test_brick_adoption_updates_the_execution_adapter_pin_together(self):
        tmp_path = self.tmp_path
        adoption = make_adoption(tmp_path)
        canonical, target, sha = adoption
        command(target, "remote", "set-url", "origin", "https://github.com/brickms/brickms.git")
        adapter = target / "scripts/agent/protocol-v1-2.py"
        adapter.parent.mkdir(parents=True)
        adapter.write_text("WORK_ADAPTER_PIN = {}\n")
        adapter.chmod(493)
        guard = target / "tests/agent_protocol_v1_4_2_vendor_test.py"
        guard.write_text(
            'EXPECTED_MANIFEST = {}\ndef check(local):\n'
            '    assert len(local.WORK_ADAPTER_PIN["files"]) == 6\n'
        )
        runbook = target / "docs/runbooks/agent-development-v1.4.2.md"
        runbook.parent.mkdir()
        runbook.write_text("# Historical guide\n")
        result = recovery.sync_adopter(canonical, target, sha, "brickms/brickms")
        assert "scripts/agent/protocol-v1-2.py" in result["changed_paths"]
        assert sha in adapter.read_text() and sha in guard.read_text()
        assert 'assert len(local.WORK_ADAPTER_PIN["files"]) == 10' in guard.read_text()
        assert "agent_protocol_work_recovery.py" in adapter.read_text()
        assert (
            recovery.sync_adopter(canonical, target, sha, "brickms/brickms")["changed_paths"] == []
        )
        if os.name != "nt":
            assert adapter.stat().st_mode & stat.S_IXUSR

    def test_adoption_does_not_overwrite_edited_generated_guidance(self):
        tmp_path = self.tmp_path
        adoption = make_adoption(tmp_path)
        canonical, target, sha = adoption
        recovery.sync_adopter(canonical, target, sha, "gabned/provelume.com")
        guidance = target / "AGENTS.md"
        guidance.write_text(guidance.read_text() + "\nHuman addition.\n")
        before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ValueError, "explicit reconciliation"):
            recovery.sync_adopter(canonical, target, sha, "gabned/provelume.com")
        assert before == {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}

    def test_recovery_archive_never_carries_symlink_zip_members(self):
        tmp_path = self.tmp_path
        evidence = make_evidence(tmp_path)
        _, archive, _ = evidence
        buffer = io.BytesIO()
        with zipfile.ZipFile(archive) as old, zipfile.ZipFile(buffer, "w") as new:
            for name in old.namelist():
                info = zipfile.ZipInfo(name)
                info.external_attr = 41471 << 16
                new.writestr(info, old.read(name))
        archive.write_bytes(buffer.getvalue())
        with self.assertRaisesRegex(ValueError, "linked"):
            recovery.recovery_verify(archive, hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
