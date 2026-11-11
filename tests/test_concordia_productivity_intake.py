"""Attributed imports, partial completion and real journal recovery."""

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_concordia_connectors_s10 import core as _core
from test_concordia_connectors_s10 import grant, item

from provelume.atomic_commit import AtomicInstanceCommit
from provelume.knowledge_object_contract import KnowledgeObjectError, record_digest
from provelume.productivity_contract import ProductivityError, ReadPage
from provelume.productivity_intake import ProductivityIntake
from provelume.service import ProvelumeInstance
from provelume.web import create_app

core = _core


def preview(manager, source, values):
    class Adapter:
        def read_page(self, **_request):
            return ReadPage(
                tuple(values),
                checkpoint="complete",
                originals=tuple(json.dumps(value).encode() for value in values),
            )

    return manager.preview(
        source,
        "task_read",
        Adapter(),
        expected_authority=manager.authority(source, "task_read")["sha256"],
    )


def test_exact_originals_versions_restart_idempotence_and_reversion(core):
    instance, manager, _identities, sources = core
    source = sources[0]["id"]
    grant(manager, source)
    intake = ProductivityIntake(instance.store)
    first = item()
    imported = intake.accept(preview(manager, source, [first]))
    document = imported["results"][0]["document_id"]
    assert imported["count"] == 1 and imported["provider_write"] is False
    assert instance.document_original(document)["data"] == json.dumps(first).encode()
    assert intake.records(source)[0]["item"] == first
    replay = intake.accept(preview(manager, source, [first]))
    assert replay["results"][0]["status"] == "unchanged"
    second = {**first, "title": "Changed remotely", "revision": '"etag-2"'}
    intake.accept(preview(manager, source, [second]))
    intake.accept(preview(manager, source, [first]))
    assert [row["sequence"] for row in instance.store.versions_for_document(document)] == [1, 2, 3]
    reopened = ProvelumeInstance(instance.root)
    assert ProductivityIntake(reopened.store).records(source)[0]["item"] == first
    assert reopened.validate_instance()["status"] == "valid"
    objects = reopened.store.list_canonical("objects")
    assert len(objects) == 1 and objects[0]["origin"]["kind"] == "connector"
    assert objects[0]["kind"] == "task" and objects[0]["body"]["due_at"] is None
    assert objects[0]["body"]["due_date"] == "2026-11-07"
    with pytest.raises(KnowledgeObjectError, match="denied"):
        reopened.object_services().update(
            objects[0]["id"],
            {"title": "Forbidden local overwrite"},
            expected_sha256=record_digest(objects[0]),
            consent=True,
        )


def test_partial_import_never_advances_checkpoint_and_recovery_deduplicates(core, monkeypatch):
    instance, manager, _identities, sources = core
    source = sources[0]["id"]
    grant(manager, source)
    intake = ProductivityIntake(instance.store)
    result = preview(manager, source, [item("one"), item("two")])
    original = intake._commit

    def fail_second(source_id, selected, *args):
        if selected["remote_id"] == "two":
            raise ProductivityError("controlled_interruption")
        return original(source_id, selected, *args)

    monkeypatch.setattr(intake, "_commit", fail_second)
    with pytest.raises(ProductivityError, match="controlled_interruption"):
        intake.accept(result)
    assert intake.checkpoint(source) is None
    assert len(instance.store.list_canonical("documents")) == 1
    monkeypatch.setattr(intake, "_commit", original)
    recovered = intake.accept(result)
    assert [row["status"] for row in recovered["results"]] == ["unchanged", "imported"]
    assert len(instance.store.list_canonical("versions")) == 2
    assert intake.checkpoint(source)["checkpoint"] == "complete"


def test_changed_authority_or_tampered_preview_cannot_publish(core):
    instance, manager, _identities, sources = core
    source = sources[0]["id"]
    grant(manager, source)
    result = preview(manager, source, [item()])
    tampered = deepcopy(result)
    tampered["items"][0]["state"] = "completed"
    with pytest.raises(ProductivityError, match="integrity"):
        ProductivityIntake(instance.store).accept(tampered)
    grant(manager, source, revision=1, mode="disabled")
    with pytest.raises(ProductivityError):
        ProductivityIntake(instance.store).accept(result)
    assert instance.store.list_canonical("documents") == []


def test_portable_rebuild_preserves_offline_connector_object_evidence(core, tmp_path):
    instance, manager, _identities, sources = core
    source = sources[0]["id"]
    grant(manager, source)
    value = {**item(), "description": "z" * 17000}
    ProductivityIntake(instance.store).accept(preview(manager, source, [value]))
    obj = instance.store.list_canonical("objects")[0]
    expected = instance.object_services().get(obj["id"])["provider_snapshot"]
    archive = tmp_path / "portable.zip"
    instance.export_portable(archive, derived_state="rebuild")
    target = ProvelumeInstance.initialise(tmp_path / "restored")
    target.import_portable(archive)
    assert target.validate_instance()["status"] == "valid"
    assert target.object_services().get(obj["id"])["provider_snapshot"] == expected
    assert ProductivityIntake(target.store).records(source)[0]["item"] == value


def test_prepared_transaction_reopens_through_registered_native_recovery(core, monkeypatch):
    instance, manager, _identities, sources = core
    source = sources[0]["id"]
    grant(manager, source)
    result = preview(manager, source, [item()])
    original = AtomicInstanceCommit._publish_entries

    def interrupt_after_replacements(self, *args):
        original(self, *args)
        raise SystemExit("Synthetic power loss before commit marker")

    monkeypatch.setattr(AtomicInstanceCommit, "_publish_entries", interrupt_after_replacements)
    with pytest.raises(SystemExit):
        ProductivityIntake(instance.store).accept(result)
    monkeypatch.setattr(AtomicInstanceCommit, "_publish_entries", original)
    reopened = ProvelumeInstance(instance.root)
    assert reopened.validate_instance()["status"] == "valid"
    assert reopened.store.list_canonical("documents") == []
    assert ProductivityIntake(reopened.store).checkpoint(source) is None


@pytest.mark.parametrize("language", ["en", "it", "de", "es", "fr", "pt", "ro"])
def test_long_description_date_only_readonly_object_ui_has_no_silent_truncation(
    core,
    tmp_path,
    language,
):
    instance, manager, _identities, sources = core
    source = sources[0]["id"]
    grant(manager, source)
    value = {**item(), "description": "LONG SOURCE <img src=x onerror=alert(1)> " + "z" * 16001}
    ProductivityIntake(instance.store).accept(preview(manager, source, [value]))
    obj = instance.store.list_canonical("objects")[0]
    assert obj["body"]["description"] == "" and obj["body"]["description_from_source"] is True
    view = instance.object_services().get(obj["id"])
    assert view["provider_snapshot"]["item"]["description"] == value["description"]
    client = TestClient(create_app(instance.root, shell_settings_file=tmp_path / "shell.json"))
    response = client.get(f"/objects/{obj['id']}?lang={language}")
    assert response.status_code == 200
    assert "z" * 16001 in response.text and "&lt;img" in response.text
    assert "<img src=x" not in response.text and "description_from_source" not in response.text
    assert 'id="connector-readonly"' in response.text and "2026-11-07" in response.text
    assert "objects.field.due_date" not in response.text
    assert f"/objects/{obj['id']}/edit?" not in response.text
    assert client.get(f"/objects/{obj['id']}/edit?lang={language}").status_code == 403
