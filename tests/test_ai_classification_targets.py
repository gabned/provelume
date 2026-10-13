from __future__ import annotations

import json
import socket
from dataclasses import FrozenInstanceError

import pytest

from provelume import ai_classification_targets as targets
from provelume.ai_contract import AiContractError, digest
from provelume.review_effects import ReviewError, ReviewStale, ReviewUnavailable
from provelume.service import ProvelumeInstance


@pytest.fixture
def current(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("Public synthetic target-resolution fixture.")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    document = instance.list_documents()[0]["id"]
    area = instance.create_hierarchy_node("area", "Work")
    project = instance.create_hierarchy_node("project", "Atlas", parent_id=area["id"])
    collection = instance.create_hierarchy_node("collection", "References")
    allowlist = tuple((node["kind"], node["id"]) for node in (area, project, collection))
    return instance, document, allowlist


def resolve(current):
    instance, document, allowlist = current
    return targets.resolve_classification_targets(instance.store, document, allowlist)


def bytes_before(instance):
    return {p.relative_to(instance.root): p.read_bytes()
            for p in instance.root.rglob("*") if p.is_file()}


def test_resolution_is_read_only_offline_and_uses_current_stable_identity(current, monkeypatch):
    instance, document, allowlist = current
    before = bytes_before(instance)
    monkeypatch.setattr(
        socket, "socket", lambda *a, **k: pytest.fail("target resolution used network")
    )
    snapshot = resolve(current)
    assert instance.ai_classification_targets(document, allowlist) == snapshot
    assert snapshot.document_id == document
    assert tuple((t.kind, t.id) for t in snapshot.targets) == allowlist
    assert tuple(t.label for t in snapshot.targets) == ("Work", "Atlas", "References")
    for language in ("en", "it"):
        template = snapshot.template(language)
        assert template.targets == snapshot.targets
        assert template.allow_partial is False
    assert snapshot.revalidate(instance.store) == snapshot
    with pytest.raises(FrozenInstanceError):
        snapshot.revision = "0" * 64
    assert bytes_before(instance) == before


@pytest.mark.parametrize("change", ["rename", "move", "placement", "new_target", "source"])
def test_current_canonical_changes_invalidate_retained_target_snapshot(current, change):
    instance, document, allowlist = current
    snapshot = resolve(current)
    if change == "rename":
        instance.rename_hierarchy_node(allowlist[1][1], "Atlas revised")
    elif change == "move":
        instance.move_hierarchy_node(allowlist[1][1], None)
    elif change == "placement":
        instance.classify_document(document, allowlist[0][1])
    elif change == "new_target":
        instance.create_hierarchy_node("area", "New choice")
    else:
        path = instance.store.paths.canonical_dir("sources") / (snapshot.source_id + ".json")
        row = json.loads(path.read_bytes())
        row["name"] = "Renamed source"
        path.write_text(json.dumps(row))
    with pytest.raises(ReviewStale):
        snapshot.revalidate(instance.store)
    assert resolve(current).revision != snapshot.revision


def test_kind_and_unknown_destination_fail_closed_without_label_matching(current):
    instance, document, allowlist = current
    for selected in ((("area", "area_" + "0" * 32),),
                     (("project", allowlist[0][1]),),
                     (("area", "Work"),),
                     (("document_type", "invoice"),)):
        with pytest.raises(ReviewUnavailable):
            targets.resolve_classification_targets(instance.store, document, selected)


def test_document_type_uses_existing_mime_category_without_rewriting_format(current):
    instance, document, allowlist = current
    row = instance.store.read_canonical("documents", document)
    before = bytes_before(instance)
    mime = row["media_type"]
    snapshot = targets.resolve_classification_targets(
        instance.store, document, (*allowlist, ("document_type", "media_" + digest(mime)))
    )
    assert snapshot.targets[-1].label == mime
    assert snapshot.targets[-1].kind == "document_type"
    assert bytes_before(instance) == before
    path = instance.store.paths.canonical_dir("documents") / (document + ".json")
    row["media_type"] = "application/pdf"
    path.write_text(json.dumps(row))
    with pytest.raises(ReviewUnavailable):
        snapshot.revalidate(instance.store)


@pytest.mark.parametrize("allowlist", [[], (), (("area", "x"),) * 65,
                                       (("area", "x"), ("area", "x")),
                                       (("area", "x"), ("project", "x")),
                                       (("provider", "x"),), ((True, "x"),),
                                       (("area", 1),), (("area", "x", "label"),),
                                       (["area", "x"],)])
def test_unbounded_or_open_host_target_input_is_rejected(current, allowlist):
    instance, document, _ = current
    with pytest.raises(ReviewError):
        targets.resolve_classification_targets(instance.store, document, allowlist)


@pytest.mark.parametrize("corrupt", ["cycle", "foreign_version", "original_hash", "missing",
                                     "linked_inventory", "future_node", "oversized"])
def test_corrupt_or_incomplete_evidence_never_resolves(current, corrupt, tmp_path):
    instance, document, allowlist = current
    if corrupt in {"cycle", "future_node", "oversized"}:
        path = instance.store.paths.canonical_dir("hierarchy") / (allowlist[0][1] + ".json")
        row = json.loads(path.read_bytes())
        if corrupt == "cycle":
            row["parent_id"] = row["id"]
        elif corrupt == "future_node":
            row["schema_version"] = 999
        else:
            row["name"] = "x" * 121
        path.write_text(json.dumps(row))
    elif corrupt == "linked_inventory":
        path = instance.store.paths.canonical_dir("hierarchy")
        path.rename(tmp_path / "foreign")
        path.symlink_to(tmp_path / "foreign", target_is_directory=True)
    else:
        snapshot = resolve(current)
        kind, identity = (("versions", snapshot.version_id) if corrupt == "foreign_version"
                          else ("originals", snapshot.original_id))
        path = instance.store.paths.canonical_dir(kind) / (identity + ".json")
        if corrupt == "missing":
            path.unlink()
        else:
            row = json.loads(path.read_bytes())
            row["document_id" if corrupt == "foreign_version" else "sha256"] = "0" * 64
            path.write_text(json.dumps(row))
    with pytest.raises((ReviewError, AiContractError)):
        resolve(current)


def test_change_during_read_is_not_a_coherent_observation(current, monkeypatch):
    instance, _, allowlist = current
    observe = targets._observe
    calls = 0

    def changed(*args):
        nonlocal calls
        result = observe(*args)
        calls += 1
        if calls == 1:
            instance.rename_hierarchy_node(allowlist[0][1], "Concurrent rename")
        return result

    monkeypatch.setattr(targets, "_observe", changed)
    with pytest.raises(ReviewStale):
        resolve(current)


def test_pending_domain_transaction_requires_existing_lifecycle_recovery(current):
    from provelume.instance_lifecycle import InstanceLifecycleManager

    instance, _, _ = current
    root = InstanceLifecycleManager(instance.store).control_root / "transactions"
    root.mkdir(parents=True, exist_ok=True)
    (root / "review-interrupted").mkdir()
    with pytest.raises(ReviewUnavailable, match="recovery"):
        resolve(current)


@pytest.mark.parametrize("language", [None, True, "de", "en-v1", {"language": "en"}])
def test_target_contract_does_not_invent_task_language(current, language):
    with pytest.raises(ReviewError):
        resolve(current).template(language)
