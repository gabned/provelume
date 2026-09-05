from __future__ import annotations

import json
import os
import re
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import BoundedSemaphore, Event

import pytest
from fastapi.testclient import TestClient

import provelume.folder_source_exclusions as manager_module
import provelume.source_exclusions as rules_module
from provelume.cli import main
from provelume.folder_source_exclusion_i18n import ERROR_TEXT, EXCLUSION_TRANSLATIONS
from provelume.folder_source_exclusions import ExclusionPreviewError, propose_change
from provelume.ingest import IngestionRetryError
from provelume.paths import UnsafePathError
from provelume.scheduler import schedule_payload
from provelume.service import ProvelumeInstance
from provelume.source_exclusions import (
    ExclusionError,
    ExclusionLimitError,
    canonical_json,
    decision,
    default_policy,
    fingerprint,
    normalize_policy,
    rule,
    scan,
)
from provelume.web import create_app


@pytest.fixture
def setup(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    folder = tmp_path / "source"
    folder.mkdir()
    for name in (
        "note.md",
        "nested/note.txt",
        ".git/private.md",
        ".github/workflow.txt",
        ".gitignore",
        ".gitattributes",
        ".gitmodules",
        "unsupported.bin",
    ):
        path = folder / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("synthetic " + name, encoding="utf-8")
    source = instance.register_folder_source(
        folder, name="Rules", quiescence_seconds=0, stable_observations=1
    )
    return instance, folder, source["id"]


def changed(instance, source_id, *additional, enabled=None):
    policy = deepcopy(instance.folder_source_exclusions(source_id)["policy"])
    policy["revision"] += 1
    policy["rules"].extend(additional)
    if enabled is not None:
        policy["enabled"] = enabled
    return normalize_policy(policy)


def apply(instance, source_id, policy):
    preview = instance.preview_folder_source_exclusions(source_id, policy)
    return instance.apply_folder_source_exclusions(
        source_id, policy, preview_fingerprint=preview["preview_fingerprint"]
    )


def test_visible_defaults_preview_counts_without_reading_document_bytes(setup, monkeypatch):
    instance, folder, source_id = setup
    before = instance.store.read_config()
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert not path.is_relative_to(folder), "Preview must never read Source file bytes"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    preview = instance.preview_folder_source_exclusions(source_id)
    assert instance.store.read_config() == before
    assert preview["complete"] and not preview["canonical_deletion"]
    assert preview["counts"]["included_files"] == 2
    assert preview["counts"]["excluded_files"] == 3
    assert preview["counts"]["excluded_directories"] == 2
    assert preview["counts"]["unsupported_files"] == 1
    assert {r["pattern"] for r in preview["policy"]["rules"]} == {
        ".git/**",
        ".github/**",
        ".gitignore",
        ".gitattributes",
        ".gitmodules",
    }
    assert str(folder) not in json.dumps(preview)
    assert not instance.store.list_canonical("acquisitions")
    assert not any(row["locator"] == ".git/private.md" for row in preview["rows"])


@pytest.mark.parametrize(
    "kind,pattern,locator,expected",
    [
        ("subfolder", "nested", "nested/note.txt", False),
        ("subfolder", "nested", "nested.txt", True),
        ("file", "nested/note.txt", "nested/note.txt", False),
        ("file", "nested/note.txt", "other/note.txt", True),
        ("file", "[draft]!.txt", "[draft]!.txt", False),
        ("extension", "TXT", "nested/NOTE.TXT", False),
        ("type", "image", "photo.JPG", False),
        ("type", "audio", "sound.MP3", False),
        ("type", "audio", "sound.OPUS", False),
        ("glob", "**/*.txt", "nested/deep/note.txt", False),
        ("glob", "**/*.txt", "note.txt", False),
        ("glob", "nested/*.txt", "nested/deep/note.txt", True),
        ("glob", "nested/?.txt", "nested/a.txt", False),
    ],
)
def test_bounded_portable_rule_kinds(kind, pattern, locator, expected):
    policy = default_policy()
    policy["rules"].append(rule(kind, pattern))
    assert decision(normalize_policy(policy), locator)["included"] is expected


@pytest.mark.parametrize(
    "kind,pattern",
    [
        ("file", "../secret"),
        ("glob", "/absolute/**"),
        ("subfolder", "C:\\root"),
        ("glob", "folder//file"),
        ("glob", "a/./b"),
        ("glob", "**/**/**/x"),
        ("glob", "***.txt"),
        ("glob", "[a-z].txt"),
        ("glob", "?" * 13),
        ("glob", "/".join(["part"] * 17)),
        ("file", "x" * 257),
        ("extension", "pdf/**"),
        ("type", "unknown"),
        ("file", "foo\x00bar"),
        ("file", "*.txt"),
        ("glob", "smb://server/share"),
    ],
)
def test_unsafe_and_overcomplex_patterns_fail_closed(kind, pattern):
    with pytest.raises(ExclusionError):
        rule(kind, pattern)


def test_exact_override_keeps_unrelated_excluded_subtrees_pruned(setup, monkeypatch):
    instance, folder, source_id = setup
    objects = folder / ".git" / "objects"
    objects.mkdir()
    for index in range(30):
        (objects / f"{index}.txt").write_text("excluded", encoding="utf-8")
    monkeypatch.setattr(rules_module, "MAX_SCAN_ENTRIES", 20)
    policy = changed(instance, source_id, rule("file", ".git/private.md", action="include"))
    preview = instance.preview_folder_source_exclusions(source_id, policy)
    assert preview["counts"]["included_files"] == 3
    assert preview["counts"]["excluded_directories"] == 2
    assert any(row["locator"] == ".git/private.md" for row in preview["rows"])
    assert not any(row["locator"].startswith(".git/objects/") for row in preview["rows"])


def test_audio_type_exclusion_keeps_opus_out_of_preview_and_refresh(setup):
    instance, folder, source_id = setup
    (folder / "sound.opus").write_bytes(b"synthetic OPUS exclusion fixture")
    policy = changed(instance, source_id, rule("type", "audio"))
    preview = instance.preview_folder_source_exclusions(source_id, policy)
    selected = next(row for row in preview["rows"] if row["locator"] == "sound.opus")
    assert selected["included"] is False and selected["reason"] == "excluded"
    assert preview["counts"]["included_files"] == 2
    apply(instance, source_id, policy)
    assert instance.refresh_folder_source(source_id)["job"]["status"] == "succeeded"
    assert {item["locator"] for item in instance.store.list_canonical("acquisitions")} == {
        "note.md",
        "nested/note.txt",
    }


def test_directory_junction_detection_prevents_subtree_traversal(setup, monkeypatch):
    instance, folder, source_id = setup
    junction = folder / "junction"
    junction.mkdir()
    (junction / "must-not-read.txt").write_text("not followed", encoding="utf-8")
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == junction or original(path))
    preview = instance.preview_folder_source_exclusions(source_id)
    assert preview["counts"]["included_files"] == 2
    assert preview["counts"]["unfollowed_links"] == 1
    assert any(row["reason"] == "directory_link_not_followed" for row in preview["rows"])
    assert not any(row["locator"].startswith("junction/") for row in preview["rows"])


@pytest.mark.skipif(os.name != "nt", reason="Permanent Windows NTFS junction qualification")
def test_real_windows_junction_is_not_followed(setup):
    instance, folder, source_id = setup
    junction, target = folder / "junction", folder / "nested"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
    )
    try:
        assert junction.is_junction()
        preview = instance.preview_folder_source_exclusions(source_id)
        assert preview["counts"]["included_files"] == 2
        assert preview["counts"]["unfollowed_links"] == 1
        assert any(row["reason"] == "directory_link_not_followed" for row in preview["rows"])
        assert instance.refresh_folder_source(source_id)["job"]["status"] == "succeeded"
        assert len(instance.store.list_canonical("acquisitions")) == 2
    finally:
        junction.rmdir()


def test_normalization_serialization_and_rule_bounds_are_deterministic():
    first = default_policy()
    first["rules"].append(rule("file", "  re\u0301sume\u0301\\note.txt  "))
    second = deepcopy(first)
    second["rules"].reverse()
    assert canonical_json(normalize_policy(first)) == canonical_json(normalize_policy(second))
    assert fingerprint(normalize_policy(first)) == fingerprint(normalize_policy(second))
    assert any(r["pattern"] == "résumé/note.txt" for r in first["rules"])
    for field, value in (("schema_version", 2), ("revision", True), ("enabled", "yes")):
        invalid = {**first, field: value}
        with pytest.raises(ExclusionError):
            normalize_policy(invalid)
    with pytest.raises(ExclusionError, match="Duplicate"):
        normalize_policy({**first, "rules": first["rules"] * 2})
    with pytest.raises(ExclusionError):
        normalize_policy({**first, "rules": [rule("file", f"{i}.txt") for i in range(33)]})


def test_explicit_override_and_individual_disable_are_visible(setup):
    instance, _folder, source_id = setup
    policy = changed(instance, source_id, rule("file", ".git/private.md", action="include"))
    preview = instance.preview_folder_source_exclusions(source_id, policy)
    selected = next(row for row in preview["rows"] if row["locator"] == ".git/private.md")
    assert selected["included"] and selected["reason"] == "explicit_override"
    assert preview["counts"]["included_files"] == 3
    apply(instance, source_id, policy)
    current = instance.folder_source_exclusions(source_id)["policy"]
    target = next(item for item in current["rules"] if item["action"] == "include")
    proposed = propose_change(
        current,
        dict(
            revision=str(current["revision"]),
            operation="upsert",
            rule_id=target["id"],
            kind=target["kind"],
            pattern=target["pattern"],
            rule_action="include",
            rule_enabled="false",
        ),
    )
    apply(instance, source_id, proposed)
    assert not decision(proposed, ".git/private.md")["included"]


def test_preview_is_bound_to_source_rules_version_and_filesystem_snapshot(setup, tmp_path):
    instance, folder, source_id = setup
    policy = changed(instance, source_id, rule("extension", ".md"))
    preview = instance.preview_folder_source_exclusions(source_id, policy)
    before = instance.folder_source_exclusions(source_id)
    (folder / "new.txt").write_text("new file", encoding="utf-8")
    with pytest.raises(ExclusionPreviewError) as exc:
        instance.apply_folder_source_exclusions(
            source_id, policy, preview_fingerprint=preview["preview_fingerprint"]
        )
    assert exc.value.code == "stale_preview"
    assert instance.folder_source_exclusions(source_id) == before
    fresh = instance.preview_folder_source_exclusions(source_id, policy)
    altered = deepcopy(policy)
    altered["enabled"] = False
    with pytest.raises(ExclusionPreviewError, match="stale_preview"):
        instance.apply_folder_source_exclusions(
            source_id, altered, preview_fingerprint=fresh["preview_fingerprint"]
        )
    other_folder = tmp_path / "other"
    other_folder.mkdir()
    other = instance.register_folder_source(other_folder, name="Other")["id"]
    with pytest.raises(ExclusionPreviewError, match="stale_preview"):
        instance.apply_folder_source_exclusions(
            other, policy, preview_fingerprint=fresh["preview_fingerprint"]
        )
    apply(instance, source_id, policy)
    with pytest.raises(ExclusionPreviewError, match="version_conflict"):
        instance.apply_folder_source_exclusions(
            source_id, policy, preview_fingerprint=fresh["preview_fingerprint"]
        )
    assert instance.folder_source_exclusions(other)["policy"] == default_policy()


def test_scan_watch_reconciliation_and_reindex_preserve_previously_acquired_records(setup):
    instance, _folder, source_id = setup
    apply(instance, source_id, changed(instance, source_id, enabled=False))
    assert (
        instance.refresh_folder_source(source_id, request_key="before")["job"]["status"]
        == "succeeded"
    )
    before = {
        kind: instance.store.list_canonical(kind)
        for kind in ("sources", "acquisitions", "originals", "documents", "versions")
    }
    assert len(before["documents"]) == 4
    old_fingerprint = instance.observe_folder_source(source_id)["pending_fingerprint"]
    current = instance.folder_source_exclusions(source_id)["policy"]
    proposed = propose_change(
        current, dict(operation="defaults", revision=str(current["revision"]))
    )
    proposed["rules"].append(rule("extension", "md"))
    apply(instance, source_id, proposed)
    assert instance.observe_folder_source(source_id)["pending_fingerprint"] != old_fingerprint
    assert (
        instance.refresh_folder_source(source_id, request_key="after")["job"]["status"]
        == "succeeded"
    )
    plan, _network = instance.source_reconciliation.build_plan(source_id)
    assert len(plan["items"]) == 1 and plan["items"][0]["classification"] == "current"
    instance.rebuild_index()
    instance.rebuild_library()
    # A refreshed admitted file can add an unchanged acquisition. Original,
    # Document and Version identities/content remain exactly retained.
    for kind in ("sources", "originals", "documents", "versions"):
        assert instance.store.list_canonical(kind) == before[kind]
    after_acquisitions = instance.store.list_canonical("acquisitions")
    assert all(item in after_acquisitions for item in before["acquisitions"])
    assert instance.validate_instance()["status"] == "valid"


def test_policy_round_trips_backup_restore_and_portable_transfer(setup, tmp_path):
    instance, _folder, source_id = setup
    policy = changed(instance, source_id, rule("subfolder", "nested"))
    apply(instance, source_id, policy)
    expected = instance.folder_source_exclusions(source_id)
    backup = tmp_path / "rules-backup.zip"
    instance.backup(destination=backup, reason="exclusions")
    apply(instance, source_id, changed(instance, source_id, enabled=False))
    instance.restore(backup)
    restored = ProvelumeInstance(instance.root)
    assert restored.folder_source_exclusions(source_id) == expected
    portable = tmp_path / "rules-portable.zip"
    restored.export_portable(portable)
    target = ProvelumeInstance.initialise(tmp_path / "target")
    target.import_portable(portable)
    imported = ProvelumeInstance(target.root)
    assert imported.folder_source_exclusions(source_id) == expected
    assert imported.validate_instance()["status"] == "valid"


def test_scheduled_watch_obeys_current_exclusions_and_rule_edits_keep_identity(setup):
    instance, _folder, source_id = setup
    policy = changed(instance, source_id, rule("extension", "md"))
    apply(instance, source_id, policy)
    rule_id = next(item["id"] for item in policy["rules"] if item["kind"] == "extension")
    updated = propose_change(
        policy,
        dict(
            operation="upsert",
            revision=str(policy["revision"]),
            rule_id=rule_id,
            kind="extension",
            pattern="txt",
            rule_action="exclude",
            rule_enabled="true",
        ),
    )
    assert next(item for item in updated["rules"] if item["id"] == rule_id)["pattern"] == ".txt"
    apply(instance, source_id, updated)
    start = datetime.now(UTC)
    policy_id = instance.folder_sources.public_view(source_id)["policy_id"]
    instance.scheduler.journal.update_policy(
        policy_id,
        schedule=schedule_payload(mode="interval", timezone="UTC", interval_seconds=60),
        now=start,
    )
    result = instance.scheduler.cycle(now=start + timedelta(seconds=61))
    assert len(result["jobs"]) == 1 and result["jobs"][0]["status"] == "succeeded"
    assert {item["locator"] for item in instance.store.list_canonical("acquisitions")} == {
        "note.md"
    }
    removed = propose_change(
        updated,
        dict(
            operation="remove",
            revision=str(updated["revision"]),
            rule_id=rule_id,
        ),
    )
    apply(instance, source_id, removed)
    assert all(item["id"] != rule_id for item in removed["rules"])
    assert instance.folder_sources.public_view(source_id)["policy_id"] == policy_id


def test_new_retry_cannot_read_items_excluded_since_the_original_failure(setup):
    instance, folder, source_id = setup
    failed = instance.ingest_run(folder, max_file_bytes=1)
    assert failed["run"]["failed_items"] == 2
    apply(instance, source_id, changed(instance, source_id, rule("glob", "**")))
    before = instance.list_ingestion_runs()
    with pytest.raises(IngestionRetryError, match="excluded"):
        instance.retry_ingestion(failed["run"]["id"])
    assert instance.list_ingestion_runs() == before
    assert instance.store.list_canonical("acquisitions") == []


def test_traversal_is_bounded_and_unicode_locators_retain_their_filesystem_spelling(
    tmp_path, monkeypatch
):
    folder = tmp_path / "tree"
    folder.mkdir()
    decomposed = "re\u0301sume\u0301.txt"
    (folder / decomposed).write_text("preserve locator", encoding="utf-8")
    assert scan(folder, 10, default_policy())["files"][0][0] == decomposed
    for name in ("a.txt", "b.txt"):
        (folder / name).write_text(name, encoding="utf-8")
    monkeypatch.setattr(rules_module, "MAX_SCAN_ENTRIES", 2)
    with pytest.raises(ExclusionLimitError):
        scan(folder, 10, default_policy())


def test_symlink_escape_and_retargeted_instance_root_fail_closed(setup, tmp_path):
    instance, folder, source_id = setup
    outside = tmp_path / "outside.txt"
    outside.write_text("must not read", encoding="utf-8")
    link = folder / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This filesystem does not permit symlink creation")
    with pytest.raises(UnsafePathError):
        scan(folder, 100, default_policy())
    link.unlink()
    detached = tmp_path / "detached-source"
    folder.rename(detached)
    folder.symlink_to(instance.root, target_is_directory=True)
    assert instance.observe_folder_source(source_id)["last_error_code"] == "unsafe_path"
    with pytest.raises(ExclusionPreviewError, match="preview_unavailable"):
        instance.preview_folder_source_exclusions(source_id)
    assert instance.store.list_canonical("acquisitions") == []


def test_timed_out_preview_workers_cannot_apply_rules_late(setup, monkeypatch):
    instance, _folder, source_id = setup
    release = Event()
    monkeypatch.setattr(manager_module, "_PREVIEW_SLOTS", BoundedSemaphore(1))
    monkeypatch.setattr(manager_module, "PREVIEW_SECONDS", 0.02)
    original_scan = manager_module.scan

    def blocked(*args):
        assert release.wait(3)
        return original_scan(*args)

    monkeypatch.setattr(manager_module, "scan", blocked)
    before = instance.folder_source_exclusions(source_id)
    try:
        with pytest.raises(ExclusionPreviewError, match="preview_timeout"):
            instance.preview_folder_source_exclusions(source_id)
        with pytest.raises(ExclusionPreviewError, match="preview_busy"):
            instance.preview_folder_source_exclusions(source_id)
    finally:
        release.set()
    assert manager_module._PREVIEW_SLOTS.acquire(timeout=3)
    manager_module._PREVIEW_SLOTS.release()
    assert instance.folder_source_exclusions(source_id) == before


def test_browser_preview_apply_and_read_only_api_share_policy_and_csrf(setup):
    instance, folder, source_id = setup
    with TestClient(create_app(instance.root)) as client:
        url = f"/sources/{source_id}/exclusions?lang=it"
        page = client.get(url)
        assert page.status_code == 200 and "Esclusioni della Source" in page.text
        assert ".git/**" in page.text
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        fields = dict(
            csrf_token=token,
            action="preview",
            operation="upsert",
            revision="1",
            kind="extension",
            pattern="md",
            rule_action="exclude",
            rule_enabled="true",
        )
        preview = client.post(url, data=fields)
        assert preview.status_code == 200 and "Nessuna regola o record" in preview.text
        assert instance.folder_source_exclusions(source_id)["policy"]["revision"] == 1
        digest = re.search(r'name="preview_fingerprint" value="([^"]+)"', preview.text).group(1)
        response = client.post(
            url, data={**fields, "action": "apply", "preview_fingerprint": digest}
        )
        assert response.status_code == 200 and "Regole applicate" in response.text
        assert instance.folder_source_exclusions(source_id)["policy"]["revision"] == 2
        api = f"/api/v1/folder-sources/{source_id}/exclusions"
        assert client.get(api).json() == instance.folder_source_exclusions(source_id)
        inspected = client.post(
            api + "/preview?lang=it",
            data=dict(csrf_token=token, action="preview", operation="inspect", revision="2"),
        )
        assert inspected.status_code == 200 and inspected.json()["counts"]["included_files"] == 1
        assert str(folder) not in inspected.text
        assert client.post(api + "/preview", data={}).status_code == 415
        assert client.post(api + "/preview", data={"operation": "inspect"}).status_code == 403
        assert client.post(api, json={}).status_code == 405
    with TestClient(create_app(instance.root), client=("192.0.2.1", 1234)) as remote:
        assert 'name="csrf_token"' not in remote.get(url).text
        assert remote.post(url, data=fields).status_code == 403


def test_cli_preview_and_apply_and_en_it_parity(setup, tmp_path, capsys):
    instance, _folder, source_id = setup
    policy = changed(instance, source_id, rule("type", "text"))
    file = tmp_path / "policy.json"
    file.write_text(canonical_json(policy), encoding="utf-8")
    args = [str(instance.root), source_id, "--policy-file", str(file)]
    assert main(["folder-source-exclusions-preview", *args]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                "folder-source-exclusions-apply",
                *args,
                "--preview-fingerprint",
                preview["preview_fingerprint"],
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["policy"] == policy
    assert EXCLUSION_TRANSLATIONS["en"].keys() == EXCLUSION_TRANSLATIONS["it"].keys()
    assert all(len(pair) == 2 and pair[0] and pair[1] for pair in ERROR_TEXT.values())


@pytest.mark.skipif(os.name != "nt", reason="Permanent Windows UNC filesystem qualification")
def test_windows_unc_exclusions_and_preview_use_the_same_rules(setup):
    instance, folder, source_id = setup
    relative = str(folder.relative_to(folder.anchor))
    unc = Path(f"\\\\localhost\\{folder.drive.rstrip(':')}$\\{relative}")
    assert unc.is_dir()
    actual = scan(unc, 100, default_policy())
    local = instance.preview_folder_source_exclusions(source_id)
    assert actual["counts"] == local["counts"]
    assert {row["locator"] for row in actual["rows"]} == {row["locator"] for row in local["rows"]}
