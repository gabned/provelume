"""Cross-layer synthetic preservation journeys, with no model-quality claim."""

import json
import shutil
import socket

import pytest
from fastapi.testclient import TestClient
from test_ai_synthesis import synthesis as _synthesis
from test_knowledge_object_review import _grant, _plan, _proposal
from test_knowledge_object_storage import _legacy
from test_review_placement_routing import _bytes, _confirm

from provelume.instance_backup import verify_backup
from provelume.instance_lifecycle import InstanceLifecycleManager
from provelume.instance_schema import build_instance_manifest
from provelume.instance_validation import inspect_instance
from provelume.knowledge_object_contract import OBJECT_CANONICAL_KINDS, KnowledgeObjectError
from provelume.knowledge_object_review import history_record
from provelume.portable_transfer import PortableTransferError
from provelume.review_effects import ReviewConflict
from provelume.service import ProvelumeInstance
from provelume.shell_settings import LauncherSettings, ShellSettingsManager
from provelume.web import create_app

synthesis = _synthesis


def _deny_network(*args, **kwargs):
    pytest.fail("The local object/recovery journey attempted network access")


def _deny_egress(monkeypatch):
    connect = socket.socket.connect

    def local_only(sock, address):
        # Windows event-loop wakeups may use an actual loopback socket pair.
        # Permit that local transport, while denying every external connection.
        if (sock.family in {socket.AF_INET, socket.AF_INET6}
                and isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}):
            return connect(sock, address)
        if hasattr(socket, "AF_UNIX") and sock.family == socket.AF_UNIX:
            return connect(sock, address)
        return _deny_network()

    monkeypatch.setattr(socket.socket, "connect", local_only)
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", _deny_network)


def _ref(view):
    return {"id": view["record"]["id"], "revision": view["record"]["revision"],
            "sha256": view["sha256"]}


@pytest.mark.parametrize("schema", [1, 2], ids=["schema1", "schema2"])
@pytest.mark.parametrize("derived", ["include", "rebuild"])
@pytest.mark.parametrize("mode", ["preview", "current"], ids=["cura", "current"])
def test_migrated_manual_graph_version_evidence_restore_and_portable_ui(
    tmp_path, monkeypatch, schema, derived, mode,
):
    _deny_egress(monkeypatch)
    legacy, hierarchy_ids = _legacy(tmp_path, schema)
    config = legacy.store.read_config()
    original_bytes = _bytes(legacy.store.paths.originals)
    retained_state = (legacy.root / "state/synthetic-preferences.json").read_bytes()
    settings = ShellSettingsManager(
        tmp_path / "launcher.json",
        LauncherSettings(instance_path=str(legacy.root), language="it", theme="dark"),
    )
    settings.save(settings.defaults)
    if mode == "current":
        settings.set_interface_mode("current", expected_revision=0)
    preference_bytes = settings.path.read_bytes()

    migrated = InstanceLifecycleManager(legacy.store).prepare(migrate_objects=True)
    assert migrated["status"] == "migrated"
    assert verify_backup(migrated["backup"]["archive"])["instance_schema_version"] == schema
    instance = ProvelumeInstance(legacy.root)
    assert {**instance.store.read_config(), "schema_version": schema} == config
    assert migrated["migration"]["promoted_hierarchy_ids"] == sorted(hierarchy_ids)
    services = instance.object_services()
    version = instance.store.list_canonical("versions")[0]
    evidence = services.evidence_for_version(version["id"])
    first = services.create(
        "claim", "Attributed <svg onload=alert(1)>", {"statement": "Original assertion"},
        aliases=["Explicit alias"], evidence=[evidence], consent=True,
    )
    second = services.update(first["record"]["id"], {"state": "disputed"},
                             expected_sha256=first["sha256"], consent=True)
    task = services.create("task", "Manual follow-up", {"description": "Check the source",
                           "due_at": "2026-11-01T10:00:00Z"}, evidence=[evidence], consent=True)
    relation = services.create_relation("relates_to", _ref(second), _ref(task), consent=True)
    committed = _bytes(instance.store.paths.knowledge)
    with pytest.raises(KnowledgeObjectError, match="conflict"):
        services.update(first["record"]["id"], {"state": "retracted"},
                        expected_sha256=first["sha256"], consent=True)
    assert _bytes(instance.store.paths.knowledge) == committed

    (tmp_path / "source/sample.md").write_text("New current Version.\n", encoding="utf-8")
    instance.ingest(tmp_path / "source")
    assert instance.get_document(version["document_id"])["current_version"]["id"] != version["id"]
    assert services.get(first["record"]["id"])["evidence"][0]["status"] == "AVAILABLE"
    assert services.get(first["record"]["id"])["record"]["evidence_ids"] == [evidence["id"]]
    assert all(_bytes(instance.store.paths.originals)[p] == raw
               for p, raw in original_bytes.items())
    canonical = _bytes(instance.store.paths.knowledge)
    backup = instance.backup(destination=tmp_path / "backups")
    services.update(second["record"]["id"], {"title": "Later local change"},
                    expected_sha256=second["sha256"], consent=True)
    restored = instance.restore(backup["archive"])
    assert verify_backup(restored["rollback_backup"]["archive"])["instance_id"] == (
        config["instance"]["id"]
    )
    assert _bytes(instance.store.paths.knowledge) == canonical
    archive = tmp_path / "portable.zip"
    if derived == "include":
        before = _bytes(instance.root)
        with pytest.raises(PortableTransferError, match="include export requires a ready"):
            instance.export_portable(archive, derived_state=derived)
        assert _bytes(instance.root) == before
        instance.rebuild_index()
        instance.rebuild_library()
    instance.export_portable(archive, derived_state=derived)
    target = ProvelumeInstance.initialise(tmp_path / "target")
    target.import_portable(archive)
    assert target.store.read_config()["instance"]["id"] == config["instance"]["id"]
    assert _bytes(target.store.paths.knowledge) == canonical
    assert _bytes(target.store.paths.originals) == _bytes(instance.store.paths.originals)
    assert (target.root / "state/synthetic-preferences.json").read_bytes() == retained_state
    restored_relation = target.object_services().get(relation["record"]["id"], relation=True)
    assert restored_relation["record"] == relation["record"]
    assert all(endpoint["current"] for endpoint in restored_relation["endpoints"])
    assert target.object_services().history(first["record"]["id"]) == [
        first["record"], second["record"],
    ]
    assert inspect_instance(target.root, deep=True)["status"] == "valid"

    client = TestClient(create_app(instance.root, shell_settings_file=settings.path))
    page = client.get("/objects/" + first["record"]["id"] + "?lang=it")
    assert page.status_code == 200 and "&lt;svg" in page.text
    assert "<svg onload=alert(1)>" not in page.text
    shell = client.get("/api/v1/shell").json()["shell"]
    assert shell["interface_mode"] == mode and shell["theme"] == "dark"
    assert settings.path.read_bytes() == preference_bytes
    assert {**instance.store.read_config(), "schema_version": schema} == config


@pytest.mark.parametrize("derived", ["include", "rebuild"])
def test_migrated_ai_receipt_review_off_version_change_and_accounting_round_trip(
    synthesis, tmp_path, monkeypatch, derived,
):
    _deny_egress(monkeypatch)
    setup, _, _ = synthesis
    instance = setup.instance
    project = instance.create_hierarchy_node("project", "Existing reviewed project")
    for kind in OBJECT_CANONICAL_KINDS:
        shutil.rmtree(instance.store.paths.canonical_dir(kind))
    config = instance.store.read_config()
    config["schema_version"] = 2
    instance.store.write_config(config)
    instance.store._atomic_json(instance.store.paths.manifest, build_instance_manifest(config))
    state_before = {p: sha for p, sha in _bytes(instance.store.paths.state).items()
                    if not p.startswith("locks/")}
    migrated = InstanceLifecycleManager(instance.store).prepare(migrate_objects=True)
    assert migrated["status"] == "migrated"
    state_after = {p: sha for p, sha in _bytes(instance.store.paths.state).items()
                   if not p.startswith("locks/")}
    assert all(state_after[p] == sha for p, sha in state_before.items())
    assert set(state_after) - set(state_before) == {
        "migrations/receipts/instance-schema-2-to-3.json",
    }
    assert {**instance.store.read_config(), "schema_version": 2} == config
    assert migrated["migration"]["promoted_hierarchy_ids"] == [project["id"]]

    _, job, proposal = _proposal(synthesis)
    _grant(instance, sources=[proposal["source"]["source_id"]])
    setup.save({"mode": "off"}, setup.configuration()["revision"])
    scheduler = _bytes(instance.store.paths.state / "scheduler")
    job_before = instance.ai_jobs.journal.get_job(job["id"])
    control_before = instance.ai_jobs._control()
    decision = _confirm(instance.review_decisions, _plan(instance, proposal), "integrated-review")
    with pytest.raises(ReviewConflict):
        _plan(instance, proposal)
    retained = history_record(instance.store, proposal["id"])
    services = instance.object_services()
    approved = services.get(decision["result"]["canonical"]["id"])
    relation = services.create_relation(
        "relates_to", _ref(services.get(project["id"])), _ref(approved), consent=True,
    )
    services.update(approved["record"]["id"], {"state": "disputed"},
                    expected_sha256=approved["sha256"], consent=True)
    instance.object_review.discard(proposal["id"], consent=True,
                                   expected_instance_id=setup.instance_id)
    setup.synthesis.discard(job["id"])
    (tmp_path / "source/note.txt").write_text("A new document Version.\n", encoding="utf-8")
    instance.ingest(tmp_path / "source")
    assert history_record(instance.store, proposal["id"]) == retained
    assert services.get(approved["record"]["id"])["evidence"][0]["status"] == "AVAILABLE"
    canonical = _bytes(instance.store.paths.knowledge)
    review = _bytes(instance.store.paths.state / "review")
    assert _bytes(instance.store.paths.state / "scheduler") == scheduler
    backup = instance.backup(destination=tmp_path / "backups")
    instance.restore(backup["archive"])
    archive = tmp_path / "ai-bearing-portable.zip"
    if derived == "include":
        before = _bytes(instance.root)
        with pytest.raises(PortableTransferError, match="include export requires a ready"):
            instance.export_portable(archive, derived_state=derived)
        assert _bytes(instance.root) == before
        instance.rebuild_index()
        instance.rebuild_library()
    instance.export_portable(archive, derived_state=derived)
    foreign = ProvelumeInstance.initialise(tmp_path / "foreign")
    foreign_before = _bytes(foreign.root)
    with pytest.raises(PortableTransferError, match="verified target backup was restored"):
        foreign.import_portable(archive)
    assert _bytes(foreign.root) == foreign_before
    instance.import_portable(archive)
    reopened = ProvelumeInstance(instance.root)
    assert _bytes(reopened.store.paths.knowledge) == canonical
    assert _bytes(reopened.store.paths.state / "review") == review
    after = _bytes(reopened.store.paths.state / "scheduler")
    mutable = {"ai-control.json", "jobs/" + job["id"] + ".json"}
    assert {p: sha for p, sha in scheduler.items() if p not in mutable} == {
        p: sha for p, sha in after.items() if p not in mutable
    }
    restored_job = json.loads((reopened.root / "state/scheduler/jobs" /
                               (job["id"] + ".json")).read_bytes())
    assert restored_job == {**job_before, "ai": {**job_before["ai"], "restored": True}}
    # Each supported whole-Instance replacement revokes the previous execution
    # generation while preserving policies, accounting and immutable receipts.
    assert reopened.ai_jobs._control() == {
        **control_before, "generation": control_before["generation"] + 2,
    }
    assert history_record(reopened.store, proposal["id"]) == retained
    restored_relation = reopened.object_services().get(relation["record"]["id"], relation=True)
    assert restored_relation["record"] == relation["record"]
    assert [endpoint["current"] for endpoint in restored_relation["endpoints"]] == [True, False]
    assert reopened.object_review._synthesis().setup.configuration()["mode"] == "off"
    assert inspect_instance(reopened.root, deep=True)["status"] == "valid"
