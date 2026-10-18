"""Synthetic manual authority, authentic attribution and current-preimage journeys."""

from __future__ import annotations

import errno
import hashlib
import json
import shutil
import socket
import subprocess
import sys

import pytest

from provelume.instance_validation import inspect_instance
from provelume.knowledge_object_contract import KnowledgeObjectError
from provelume.knowledge_object_evidence import ObjectEvidenceResolver
from provelume.object_migration import tree_inventory
from provelume.representations import RepresentationBundleManager
from provelume.service import ProvelumeInstance


@pytest.fixture
def seeded(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("Synthetic original.\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest(source)
    return instance, source


def _version(instance):
    return instance.store.list_canonical("versions")[0]["id"]


def _entity(services, title="Manual"):
    return services.create("entity", title, {"description": "Inert <script> text"}, consent=True)


def _ref(view):
    return {
        "id": view["record"]["id"],
        "revision": view["record"]["revision"],
        "sha256": view["sha256"],
    }


def _page(instance):
    bundle = RepresentationBundleManager(instance.store).materialize(
        _version(instance),
        recipe_id="synthetic.object-evidence",
        recipe_version="1",
        recipe_settings={},
        output_payloads={"pages.txt": ("text/plain", b"First page.\n\fSecond page.\n")},
        implementation={
            "component": "synthetic",
            "component_version": "1",
            "adapter": "local",
            "adapter_version": "1",
            "settings": {},
        },
        anchor_targets=(
            {"kind": "page", "page": 1},
            {"kind": "page", "page": 2},
            {"kind": "time", "start_ms": 0, "end_ms": 1000},
        ),
    )
    selector = {
        "kind": "text",
        "representation_id": bundle["representation_id"],
        "output_id": bundle["outputs"][0]["id"],
        "anchor_id": bundle["anchors"][1]["id"],
        "quote_sha256": hashlib.sha256(b"Second page.\n").hexdigest(),
    }
    return bundle, selector


@pytest.mark.parametrize(
    "consent",
    [False, None, 0, 1, "true", {}],
    ids=["false", "none", "zero", "one", "string", "object"],
)
def test_manual_writes_deny_before_instance_io_or_recovery(seeded, monkeypatch, consent):
    instance, _ = seeded
    before = tree_inventory(instance.root)
    services = instance.object_services()
    monkeypatch.setattr(instance.store, "read_config", lambda: pytest.fail("denial read Instance"))
    with pytest.raises(KnowledgeObjectError, match="denied"):
        services.create("entity", "Denied", {"description": ""}, consent=consent)
    with pytest.raises(KnowledgeObjectError, match="denied"):
        services.update("untrusted", {"title": "Denied"}, expected_sha256="x", consent=consent)
    with pytest.raises(KnowledgeObjectError, match="denied"):
        services.create_relation("relates_to", {}, {}, consent=consent)
    assert tree_inventory(instance.root) == before


@pytest.mark.parametrize(
    "kind,body",
    [
        ("entity", {"description": "Person asserted by the operator"}),
        ("claim", {"statement": "An attributed assertion, not certified truth"}),
        ("decision", {"rationale": "Explicit local reasoning"}),
        ("task", {"description": "Manual task", "due_at": None}),
        ("outcome", {"description": "Manual outcome"}),
        (
            "calendar_event",
            {
                "description": "Fold-aware event",
                "time_zone": "Europe/Rome",
                "starts_at": "2026-10-25T02:30:00+02:00",
                "ends_at": "2026-10-25T02:45:00+01:00",
            },
        ),
        ("commitment", {"description": "Manual commitment", "due_at": "2026-11-01T10:00:00Z"}),
    ],
    ids=["entity", "claim", "decision", "task", "outcome", "calendar", "commitment"],
)
def test_manual_types_have_immutable_history_and_no_inference(seeded, monkeypatch, kind, body):
    instance, _ = seeded
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("DNS"))
    services = instance.object_services()
    ev = services.evidence_for_version(_version(instance))
    original = instance.store.original_bytes(ev["original_id"])
    first = services.create(kind, "Explicit", body, aliases=["Alias"], evidence=[ev], consent=True)
    second = services.update(
        first["record"]["id"], {"title": "Edited"}, expected_sha256=first["sha256"], consent=True
    )
    assert second["record"]["revision"] == 2
    assert second["record"]["previous_sha256"] == first["sha256"]
    assert second["record"]["origin"] == {"kind": "manual", "proposal_id": None}
    assert second["truth"] == "NOT_VERIFIED" and second["evidence"][0]["status"] == "AVAILABLE"
    assert services.history(first["record"]["id"]) == [first["record"], second["record"]]
    before = tree_inventory(instance.root)
    assert services.get(first["record"]["id"])["record"] == second["record"]
    assert services.list()["items"][0]["history"] == "NOT_CHECKED"
    assert tree_inventory(instance.root) == before
    assert instance.store.original_bytes(ev["original_id"]) == original
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


@pytest.mark.parametrize("kind", ["project", "collection"])
def test_hierarchy_identity_and_name_keep_the_existing_single_writer(seeded, kind):
    instance, _ = seeded
    node = instance.create_hierarchy_node(kind, "Existing")
    canonical_before = instance.store.read_canonical("hierarchy", node["id"])
    services = instance.object_services()
    first = services.get(node["id"])
    with pytest.raises(KnowledgeObjectError, match="hierarchy_authority"):
        services.create(kind, "Replacement", {"description": ""}, consent=True)
    with pytest.raises(KnowledgeObjectError, match="hierarchy_authority"):
        services.update(
            node["id"], {"title": "Hidden rename"}, expected_sha256=first["sha256"], consent=True
        )
    edited = services.update(
        node["id"],
        {"aliases": ["Stable alias"], "body": {"description": "Manual metadata"}},
        expected_sha256=first["sha256"],
        consent=True,
    )
    assert instance.store.read_canonical("hierarchy", node["id"]) == canonical_before
    instance.rename_hierarchy_node(node["id"], "Renamed through hierarchy")
    current = services.get(node["id"])
    assert current["record"]["id"] == node["id"]
    assert current["record"]["title"] == "Renamed through hierarchy"
    assert current["record"]["aliases"] == edited["record"]["aliases"]
    assert len(services.history(node["id"])) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "obj_" + "a" * 32},
        {"instance_id": "inst_" + "a" * 32},
        {"kind": "claim"},
        {"revision": 900},
        {"origin": {"kind": "reviewed_proposal", "proposal_id": "objprop_" + "a" * 64}},
    ],
    ids=["id", "instance", "kind", "revision", "proposal-origin"],
)
def test_untrusted_changes_cannot_grant_authority_or_replace_identity(seeded, changes):
    instance, _ = seeded
    services = instance.object_services()
    first = _entity(services)
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError):
        services.update(
            first["record"]["id"], changes, expected_sha256=first["sha256"], consent=True
        )
    assert tree_inventory(instance.root) == before


def test_stale_edit_cannot_append_evidence_or_revisions(seeded):
    instance, _ = seeded
    services = instance.object_services()
    first = _entity(services)
    services.update(
        first["record"]["id"], {"title": "Newer"}, expected_sha256=first["sha256"], consent=True
    )
    ev = services.evidence_for_version(_version(instance))
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError, match="conflict"):
        services.update(
            first["record"]["id"],
            {"title": "Stale", "evidence_ids": [ev["id"]]},
            expected_sha256=first["sha256"],
            evidence=[ev],
            consent=True,
        )
    assert tree_inventory(instance.root) == before
    assert not instance.store.list_canonical("object-evidence")


def test_real_local_processes_can_commit_only_one_matching_preimage(seeded):
    instance, _ = seeded
    first = _entity(instance.object_services())
    script = """
import sys
from provelume.service import ProvelumeInstance
from provelume.knowledge_object_contract import KnowledgeObjectError
from provelume.instance_lifecycle import InstanceLifecycleBusy
try:
    manager = ProvelumeInstance(sys.argv[1]).object_services()
    manager.update(sys.argv[2], {'title': sys.argv[4]}, expected_sha256=sys.argv[3], consent=True)
    print('APPLIED')
except (KnowledgeObjectError, InstanceLifecycleBusy):
    print('REFUSED')
"""
    children = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(instance.root),
                first["record"]["id"],
                first["sha256"],
                title,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for title in ["First contender", "Second contender"]
    ]
    outcomes = []
    for child in children:
        stdout, stderr = child.communicate(timeout=60)
        assert child.returncode == 0, stderr.decode()
        outcomes.append(stdout.decode().strip())
    assert sorted(outcomes) == ["APPLIED", "REFUSED"]
    assert len(instance.object_services().history(first["record"]["id"])) == 2


def test_exact_page_and_original_evidence_remain_on_the_old_version(seeded):
    instance, source = seeded
    services = instance.object_services()
    bundle, selector = _page(instance)
    before = tree_inventory(instance.root)
    ev = services.evidence_for_version(_version(instance), selector=selector)
    assert tree_inventory(instance.root) == before
    claim = services.create(
        "claim", "Attributed page", {"statement": "Operator assertion"}, evidence=[ev], consent=True
    )
    (source / "note.txt").write_text("Changed document Version.\n", encoding="utf-8")
    instance.ingest(source)
    current = services.get(claim["record"]["id"])
    assert current["evidence"][0]["status"] == "AVAILABLE"
    assert (
        instance.store.read_canonical("object-evidence", ev["id"])["version_id"] == ev["version_id"]
    )
    assert len(instance.store.list_canonical("versions")) == 2
    output = instance.root / bundle["outputs"][0]["storage_ref"]
    output.write_bytes(b"forged replacement")
    assert services.get(claim["record"]["id"])["evidence"][0]["status"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    "damage",
    [
        "quote",
        "output-id",
        "anchor-id",
        "page",
        "unsupported-time",
        "bundle-anchor-id",
        "duplicate-json",
        "removed",
    ],
    ids=["quote", "output", "anchor", "page", "time", "forged-anchor", "duplicate-json", "removed"],
)
def test_selector_forgery_cannot_append_canonical_claims(seeded, damage):
    instance, _ = seeded
    services = instance.object_services()
    bundle, selector = _page(instance)
    if damage == "quote":
        selector["quote_sha256"] = hashlib.sha256(b"First page.\n").hexdigest()
    elif damage == "output-id":
        selector["output_id"] = "rout_" + "0" * 64
    elif damage == "anchor-id":
        selector["anchor_id"] = "ranc_" + "0" * 64
    elif damage == "page":
        selector["anchor_id"] = bundle["anchors"][0]["id"]
    elif damage == "unsupported-time":
        selector["anchor_id"] = bundle["anchors"][2]["id"]
    else:
        path = (
            instance.root
            / "state/derived/representations"
            / bundle["representation_id"]
            / "bundle.json"
        )
        if damage == "bundle-anchor-id":
            bundle["anchors"][1]["id"] = "ranc_" + "0" * 64
            selector["anchor_id"] = bundle["anchors"][1]["id"]
            path.write_text(json.dumps(bundle), encoding="utf-8")
        elif damage == "duplicate-json":
            path.write_text(
                '{"schema_version":1,' + path.read_text(encoding="utf-8")[1:], encoding="utf-8"
            )
        elif damage == "removed":
            bundle["lifecycle"].update(
                state="removed", removed_at=bundle["lifecycle"]["created_at"]
            )
            path.write_text(json.dumps(bundle), encoding="utf-8")
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError):
        services.evidence_for_version(_version(instance), selector=selector)
    assert tree_inventory(instance.root) == before
    assert not instance.store.list_canonical("objects")


def test_purged_source_stays_unavailable_and_explicit_withdrawal_retains_attribution(seeded):
    instance, _ = seeded
    services = instance.object_services()
    ev = services.evidence_for_version(_version(instance))
    claim = services.create(
        "claim", "Withdrawable", {"statement": "Attributed assertion"}, evidence=[ev], consent=True
    )
    instance.trash_document(ev["document_id"])
    preview = instance.purge_document_preview(ev["document_id"])
    instance.purge_document(
        ev["document_id"], preview["confirmation_token"], acknowledge_boundaries=True
    )
    before = tree_inventory(instance.root)
    assert services.get(claim["record"]["id"])["evidence"][0]["status"] == "UNAVAILABLE"
    assert tree_inventory(instance.root) == before
    with pytest.raises(KnowledgeObjectError, match="evidence_unavailable"):
        services.update(
            claim["record"]["id"],
            {"title": "New asserted claim"},
            expected_sha256=claim["sha256"],
            consent=True,
        )
    withdrawn = services.update(
        claim["record"]["id"], {"state": "retracted"}, expected_sha256=claim["sha256"], consent=True
    )
    assert withdrawn["record"]["evidence_ids"] == [ev["id"]]
    assert withdrawn["evidence"][0]["status"] == "UNAVAILABLE"
    assert instance.store.read_canonical("object-evidence", ev["id"]) == ev
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_relation_staleness_is_visible_and_retraction_never_retargets(seeded):
    instance, _ = seeded
    services = instance.object_services()
    first, second = _entity(services), _entity(services, "Other")
    relation = services.create_relation("depends_on", _ref(first), _ref(second), consent=True)
    services.update(
        first["record"]["id"], {"title": "Newer"}, expected_sha256=first["sha256"], consent=True
    )
    observed = services.get(relation["record"]["id"], relation=True)
    assert [x["current"] for x in observed["endpoints"]] == [False, True]
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError, match="conflict"):
        services.create_relation("relates_to", _ref(first), _ref(second), consent=True)
    assert tree_inventory(instance.root) == before
    withdrawn = services.update(
        relation["record"]["id"],
        {"state": "retracted"},
        relation=True,
        expected_sha256=relation["sha256"],
        consent=True,
    )
    assert withdrawn["record"]["source"] == relation["record"]["source"]
    assert withdrawn["record"]["target"] == relation["record"]["target"]
    assert len(services.history(relation["record"]["id"], relation=True)) == 2


@pytest.mark.parametrize("damage", ["cycle", "missing", "typed"], ids=["cycle", "missing", "typed"])
def test_manual_relation_graph_is_checked_before_mutation(seeded, damage):
    instance, _ = seeded
    services = instance.object_services()
    first, second = _entity(services), _entity(services, "Other")
    services.create_relation("depends_on", _ref(first), _ref(second), consent=True)
    source, target = _ref(second), _ref(first)
    kind = "depends_on"
    if damage == "missing":
        target = {**target, "id": "obj_" + "0" * 32}
    elif damage == "typed":
        kind = "scheduled_for"
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError):
        services.create_relation(kind, source, target, consent=True)
    assert tree_inventory(instance.root) == before


@pytest.mark.parametrize(
    "zone,start,end",
    [
        ("No_Such_Zone", "2026-10-18T10:00:00Z", "2026-10-18T11:00:00Z"),
        ("Europe/Rome", "2026-03-29T02:30:00+01:00", "2026-03-29T04:00:00+02:00"),
        ("Europe/Rome", "2026-07-01T10:00:00+01:00", "2026-07-01T11:00:00+01:00"),
    ],
    ids=["unknown-zone", "nonexistent-wall-time", "wrong-season-offset"],
)
def test_calendar_zone_and_selected_instants_must_agree(seeded, zone, start, end):
    instance, _ = seeded
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError, match="time_zone"):
        instance.object_services().create(
            "calendar_event",
            "Rejected",
            {
                "description": "Synthetic",
                "starts_at": start,
                "ends_at": end,
                "time_zone": zone,
            },
            consent=True,
        )
    assert tree_inventory(instance.root) == before


def test_bounded_history_and_source_reads_fail_without_repair(seeded, monkeypatch):
    instance, _ = seeded
    services = instance.object_services()
    first = _entity(services)
    ev = services.evidence_for_version(_version(instance))
    resolver = ObjectEvidenceResolver(instance.store)
    resolver.remaining = 1
    assert resolver.status(ev)["status"] == "UNAVAILABLE"
    path = instance.store.paths.canonical_dir("object-revisions") / (
        "objrev_" + first["sha256"] + ".json"
    )
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    wrapper["record"]["title"] = "Corrupted history"
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError, match="integrity"):
        services.get(first["record"]["id"])
    assert tree_inventory(instance.root) == before


def test_boolean_schema_cannot_impersonate_an_immutable_integer_revision_schema(seeded):
    instance, _ = seeded
    services = instance.object_services()
    first = _entity(services)
    path = instance.store.paths.canonical_dir("object-revisions") / (
        "objrev_" + first["sha256"] + ".json"
    )
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    wrapper["schema_version"] = True
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError, match="integrity"):
        services.get(first["record"]["id"])
    assert tree_inventory(instance.root) == before


@pytest.mark.parametrize(
    "damage",
    ["cycle", "depth", "nan", "surrogate", "oversize"],
    ids=["cycle", "depth", "nan", "surrogate", "oversize"],
)
def test_untrusted_nested_inputs_are_bounded_before_copying_or_journalling(seeded, damage):
    instance, _ = seeded
    body = {"description": "initial"}
    if damage == "cycle":
        body["description"] = body
    elif damage == "depth":
        value = body
        for _ in range(40):
            value["nested"] = {}
            value = value["nested"]
    elif damage == "nan":
        body["description"] = float("nan")
    elif damage == "surrogate":
        body["description"] = "\ud800"
    else:
        body["description"] = "x" * (256 * 1024 + 1)
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError):
        instance.object_services().create("entity", "Rejected", body, consent=True)
    assert tree_inventory(instance.root) == before


@pytest.mark.parametrize("value", [{}, [], False], ids=["object", "array", "boolean"])
def test_invalid_state_types_raise_content_free_errors_without_side_effects(seeded, value):
    instance, _ = seeded
    services = instance.object_services()
    first = _entity(services)
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError):
        services.update(
            first["record"]["id"], {"state": value}, expected_sha256=first["sha256"], consent=True
        )
    assert tree_inventory(instance.root) == before


@pytest.mark.parametrize("budget", ["revisions", "bytes"])
def test_refused_history_growth_keeps_the_last_head_readable(seeded, monkeypatch, budget):
    from provelume import knowledge_object_services as module

    instance, _ = seeded
    services = instance.object_services()
    first = _entity(services)
    if budget == "revisions":
        monkeypatch.setattr(module, "MAX_HISTORY_REVISIONS", 1)
    else:
        wrapper = instance.store.read_canonical("object-revisions", "objrev_" + first["sha256"])
        monkeypatch.setattr(
            module, "MAX_HISTORY_BYTES", len(module.canonical_json_bytes(wrapper)) + 1
        )
    before = tree_inventory(instance.root)
    with pytest.raises(KnowledgeObjectError, match="limit"):
        services.update(
            first["record"]["id"],
            {"title": "Would exceed retained history budget"},
            expected_sha256=first["sha256"],
            consent=True,
        )
    assert tree_inventory(instance.root) == before
    assert services.get(first["record"]["id"])["record"] == first["record"]


def test_parent_replacement_link_cannot_redirect_an_existing_service_store(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    instance = ProvelumeInstance.initialise(parent / "instance")
    services = instance.object_services()
    first = _entity(services)
    moved = tmp_path / "moved"
    outside = tmp_path / "outside"
    outside.mkdir()
    parent.rename(moved)
    shutil.copytree(moved / "instance", outside / "instance")
    try:
        parent.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        moved.rename(parent)
        if (
            exc.errno not in {errno.EACCES, errno.EPERM, errno.ENOTSUP}
            and getattr(exc, "winerror", None) != 1314
        ):
            raise
        pytest.skip("host does not permit creation of directory symlinks")
    try:
        outside_record = outside / "instance/knowledge/objects" / (first["record"]["id"] + ".json")
        original = outside_record.read_bytes()
        with pytest.raises(KnowledgeObjectError, match="integrity"):
            services.get(first["record"]["id"])
        with pytest.raises(KnowledgeObjectError, match="integrity"):
            services.create("entity", "Outside write denied", {"description": ""}, consent=True)
        assert outside_record.read_bytes() == original
    finally:
        parent.unlink()
        moved.rename(parent)


def test_manual_services_preserve_every_nonobject_instance_byte(seeded):
    instance, _ = seeded
    services = instance.object_services()
    before = {x["path"]: x for x in tree_inventory(instance.root)}
    ev = services.evidence_for_version(_version(instance))
    claim = services.create(
        "claim",
        "Local assertion",
        {"statement": "Operator attribution"},
        evidence=[ev],
        consent=True,
    )
    entity = _entity(services)
    services.create_relation("about", _ref(claim), _ref(entity), consent=True)
    after = {x["path"]: x for x in tree_inventory(instance.root)}
    changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    assert changed
    assert all(
        path.startswith(
            (
                "knowledge/objects/",
                "knowledge/object-evidence/",
                "knowledge/object-revisions/",
                "knowledge/object-relations/",
                "knowledge/object-relation-revisions/",
            )
        )
        for path in changed
    )


@pytest.mark.parametrize("mode", ["include", "rebuild"])
def test_service_objects_and_retained_evidence_survive_portable_round_trip(seeded, tmp_path, mode):
    instance, _ = seeded
    services = instance.object_services()
    ev = services.evidence_for_version(_version(instance))
    claim = services.create(
        "claim", "Portable", {"statement": "Retained original"}, evidence=[ev], consent=True
    )
    if mode == "include":
        instance.rebuild_index()
        instance.rebuild_library()
    instance.export_portable(tmp_path / "portable.zip", derived_state=mode)
    target = ProvelumeInstance.initialise(tmp_path / "target")
    target.import_portable(tmp_path / "portable.zip")
    result = target.object_services().get(claim["record"]["id"])
    assert result["record"] == claim["record"] and result["evidence"][0]["status"] == "AVAILABLE"
    assert target.store.original_bytes(ev["original_id"]) == instance.store.original_bytes(
        ev["original_id"]
    )
