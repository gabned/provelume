"""Real Core identities/policies; synthetic adapters do not qualify providers."""

import json
from copy import deepcopy

import pytest

from provelume import cli
from provelume.productivity_contract import (
    ProductivityError,
    ReadCredential,
    ReadPage,
    fingerprint,
    temporal,
    validate_item,
)
from provelume.service import ProvelumeInstance


def item(remote_id="one"):
    return {"remote_id": remote_id, "revision": '"etag-1"', "revision_kind": "etag",
            "kind": "task", "title": "Synthetic follow-up", "description": "Original text",
            "state": "open", "due": {"kind": "date", "value": "2026-11-07", "time_zone": None},
            "starts": None, "ends": None,
            "provenance": {"container_ids": ["project-one"], "parent_id": None,
                           "assignees": ["synthetic-user"], "links": ["https://example.org/tasks/1"],
                           "comments": ["Synthetic retained comment"], "uid": None,
                           "recurrence_id": None, "recurrence": []}}


@pytest.fixture
def core(tmp_path):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = instance.productivity_connectors()
    definition = instance.connectors.register_definition({
        "adapter_key": "concordia-synthetic", "adapter_version": "1.0.0",
        "display_name": "Synthetic conformance", "provider": "synthetic",
        "conformance_profile": "provelume.connector.v1", "adapter_protocol_version": 1,
        "capabilities": ["manual_read", "source_selection", "task_read", "calendar_read"],
        "authorization_modes": ["none"], "source_kinds": ["tasks", "calendar"],
        "data_categories": ["source.content"], "multi_instance": True, "network_access": "none"})
    identities = [instance.connectors.create_instance(
        definition["id"], name=name, provider_identity="synthetic", account_identity=name)
        for name in ("first", "second")]
    sources = [instance.connectors.add_source(identity["id"], name="Selected project",
               source_kind="tasks", external_id="same-remote-project") for identity in identities]
    return instance, manager, identities, sources


class Adapter:
    def __init__(self, action=None):
        self.calls = []
        self.action = action

    def read_page(self, **request):
        self.calls.append(request)
        if self.action:
            self.action()
        return (ReadPage((item("one"),), next_cursor="next") if request["cursor"] is None
                else ReadPage((item("two"),), checkpoint="sync-complete"))


def grant(manager, source_id, *, mode="manual", revision=0):
    return manager.consent(source_id, capabilities=["task_read"], mode=mode,
                           expected_revision=revision, confirmed=True)


def test_two_identities_sources_consents_and_cursor_sessions_are_independent(core):
    instance, manager, identities, sources = core
    first, second = [row["id"] for row in sources]
    assert first != second and identities[0]["id"] != identities[1]["id"]
    adapter = Adapter()
    with pytest.raises(ProductivityError, match="consent_required"):
        manager.authority(first, "task_read")
    grant(manager, first)
    before = instance.store.knowledge_fingerprint()
    authority = manager.authority(first, "task_read")
    result = manager.preview(first, "task_read", adapter, expected_authority=authority["sha256"])
    assert [record["remote_id"] for record in result["items"]] == ["one", "two"]
    assert [call["cursor"] for call in adapter.calls] == [None, "next"]
    assert result["checkpoint"] == "sync-complete" and not result["cursor_advanced"]
    assert instance.store.knowledge_fingerprint() == before
    with pytest.raises(ProductivityError, match="consent_required"):
        manager.authority(second, "task_read")
    assert manager.policy(second) is None
    assert instance.validate_instance()["status"] == "valid"


@pytest.mark.parametrize("change", ["pause", "revoke", "source", "identity", "selection"])
def test_authority_change_during_response_refuses_complete_preview(core, change):
    instance, manager, identities, sources = core
    source, identity = sources[0]["id"], identities[0]["id"]
    grant(manager, source)
    authority = manager.authority(source, "task_read")

    def mutate():
        if change in {"pause", "revoke"}:
            manager.consent(source, capabilities=[] if change == "revoke" else ["task_read"],
                            mode="disabled", expected_revision=1, confirmed=True)
        elif change == "source":
            instance.connectors.disable_source(identity, source)
        elif change == "identity":
            instance.connectors.disable_instance(identity)
        else:
            instance.connectors.update_source(identity, source, external_id="another-project")

    with pytest.raises(ProductivityError):
        manager.preview(source, "task_read", Adapter(mutate),
                        expected_authority=authority["sha256"])
    assert instance.store.list_canonical("objects") == []


def test_stale_confirmation_scheduling_and_cancel_cannot_grant_or_read(core):
    _instance, manager, _identities, sources = core
    source = sources[0]["id"]
    with pytest.raises(ProductivityError, match="consent_required"):
        manager.consent(source, capabilities=["task_read"], mode="manual",
                        expected_revision=0, confirmed=False)
    grant(manager, source)
    with pytest.raises(ProductivityError, match="stale"):
        grant(manager, source)
    with pytest.raises(ProductivityError, match="consent_required"):
        manager.authority(source, "task_read", scheduled=True)
    adapter = Adapter()
    with pytest.raises(ProductivityError, match="cancelled"):
        manager.preview(source, "task_read", adapter, expected_authority=manager.authority(
            source, "task_read")["sha256"], cancelled=lambda: True)
    assert adapter.calls == []


def test_cursor_cycle_is_a_failure_without_cursor_commit(core):
    _instance, manager, _identities, sources = core
    source = sources[0]["id"]
    grant(manager, source)

    class Loop:
        def read_page(self, **request):
            return ReadPage((), next_cursor="repeated")

    with pytest.raises(ProductivityError, match="cursor_loop"):
        manager.preview(source, "task_read", Loop(), expected_authority=manager.authority(
            source, "task_read")["sha256"])
    assert manager.policy(source)["revision"] == 1


def test_mapping_preserves_date_due_and_dst_offsets_without_invented_times():
    value = item()
    assert validate_item(value)["due"]["value"] == "2026-11-07"
    event = {**value, "kind": "calendar_event", "state": "confirmed", "due": None,
             "starts": {"kind": "instant", "value": "2026-10-25T02:30:00+02:00",
                        "time_zone": "Europe/Rome"},
             "ends": {"kind": "instant", "value": "2026-10-25T02:45:00+01:00",
                      "time_zone": "Europe/Rome"}}
    assert validate_item(event) == event
    assert temporal(event["ends"]) > temporal(event["starts"])
    with pytest.raises(ProductivityError):
        temporal({"kind": "instant", "value": "2026-11-07T10:00:00", "time_zone": "Europe/Rome"})


@pytest.mark.parametrize("corruption", ["unknown", "javascript", "missing_revision", "bad_date",
                                        "title_limit", "unsafe_time", "secret_field"])
def test_unsupported_mapping_fails_before_consumer(corruption):
    value = item()
    if corruption in {"unknown", "secret_field"}:
        value[corruption] = "not accepted"
    elif corruption == "javascript":
        value["provenance"]["links"] = ["javascript:alert(1)"]
    elif corruption == "missing_revision":
        value["revision"] = ""
    elif corruption == "bad_date":
        value["due"]["value"] = "2026-02-30"
    elif corruption == "title_limit":
        value["title"] = "x" * 241
    else:
        value["due"] = {"kind": "instant", "value": "2026-07-01T12:00:00+00:00",
                        "time_zone": "Europe/Rome"}
    with pytest.raises(ProductivityError):
        ReadPage((value,)).validate()


def test_credentials_are_redacted_and_bound_to_capability_and_identity():
    credential = ReadCredential("connector_instance_" + "1" * 32, "task_read", "a" * 64,
                                {"access_token": "synthetic-secret-sentinel"})
    assert "synthetic-secret" not in repr(credential)
    assert credential.validate(credential.identity_id, "task_read") is credential
    with pytest.raises(ProductivityError, match="authorization_required"):
        credential.validate("connector_instance_" + "2" * 32, "task_read")
    with pytest.raises(ProductivityError, match="authorization_required"):
        credential.validate(credential.identity_id, "calendar_read")


def test_source_policy_integrity_chain_is_checked_not_repaired(core):
    instance, manager, _identities, sources = core
    source = sources[0]["id"]
    first = grant(manager, source)
    grant(manager, source, revision=1, mode="disabled")
    path = instance.root / f"state/productivity-connectors/{source}/policies/000001.json"
    previous = path.read_bytes()
    bad = deepcopy(first)
    bad["mode"] = "scheduled"
    instance.store._atomic_json(path, bad)
    with pytest.raises(ProductivityError, match="integrity"):
        manager.policy(source)
    assert path.read_bytes() != previous
    assert fingerprint(first) != fingerprint(bad)


def test_source_kind_cannot_borrow_another_capability(core):
    _instance, manager, _identities, sources = core
    with pytest.raises(ProductivityError, match="unsupported"):
        manager.consent(sources[0]["id"], capabilities=["calendar_read"], mode="manual",
                        expected_revision=0, confirmed=True)


def test_external_credential_revision_change_and_missing_network_fail_closed(core):
    instance, manager, _identities, _sources = core
    definition = instance.store.list_canonical("connector-definitions")[0]
    manifest = {key: value for key, value in definition.items()
                if key not in {"schema_version", "id", "created_at"}}
    manifest.update(adapter_key="concordia-remote", network_access="explicit_only", capabilities=
                    sorted([*manifest["capabilities"], "external_secret_authorization"]))
    registered = instance.connectors.register_definition(manifest)
    identity = instance.connectors.create_instance(registered["id"], name="Remote synthetic",
        provider_identity="synthetic", endpoint="https://example.org", network_mode="explicit",
        allowed_origins=["https://example.org"])
    source = instance.connectors.add_source(
        identity["id"], name="Remote synthetic tasks", source_kind="tasks",
        external_id="remote-project")["id"]
    grant(manager, source)
    with pytest.raises(ProductivityError, match="network_disabled"):
        manager.authority(source, "task_read")
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)

    class Resolver:
        revision = "a" * 64

        def resolve(self, identity_id, capability):
            return ReadCredential(identity_id, capability, self.revision,
                                  {"access_token": "synthetic-secret-sentinel"})

    resolver = Resolver()
    adapter = Adapter(lambda: setattr(resolver, "revision", "b" * 64))
    with pytest.raises(ProductivityError, match="stale"):
        manager.preview(source, "task_read", adapter, credentials=resolver,
                        expected_authority=manager.authority(source, "task_read")["sha256"])
    assert len(adapter.calls) == 1
    assert all(b"synthetic-secret-sentinel" not in path.read_bytes()
               for path in instance.root.rglob("*") if path.is_file())


def test_cli_observation_and_revision_bound_consent_use_real_policy(core, capsys):
    instance, manager, _identities, sources = core
    source = sources[0]["id"]
    assert cli.main(["productivity-policy", str(instance.root), source]) == 0
    assert json.loads(capsys.readouterr().out)["policy"] is None
    arguments = ["productivity-consent", str(instance.root), source, "--mode", "manual",
                 "--capability", "task_read", "--expected-revision", "0"]
    assert cli.main(arguments) == 2
    assert json.loads(capsys.readouterr().out)["network_attempted"] is False
    assert manager.policy(source) is None
    assert cli.main([*arguments, "--confirm"]) == 0
    assert json.loads(capsys.readouterr().out)["policy"]["revision"] == 1
    assert cli.main([*arguments, "--confirm"]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "productivity_policy_unavailable"
