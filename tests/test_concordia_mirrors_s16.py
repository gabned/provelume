"""Shared mirror contracts using synthetic local data; no transport qualification."""

import json
import re
from copy import deepcopy

import pytest

from provelume.mirror_contract import MirrorError, diff, inventory
from provelume.mirrors import Mirrors
from provelume.service import ProvelumeInstance
from provelume.tududi_qualification import SyntheticVault


def seed(
    tmp_path,
    *,
    text="# Synthetic mirror\n\nReadable offline body.\n",
    mode="manual",
    profile="folder",
):
    source = tmp_path / "input"
    source.mkdir()
    (source / "readable.md").write_text(text)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest_run(source)
    engine = Mirrors(instance.store, vault=SyntheticVault())
    engine.set_access(enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True)
    identity = engine.create_identity(
        name="Synthetic folder identity",
        profile=profile,
        credential={"reference": ""},
        confirmed=True,
    )
    destination = engine.configure(
        identity_id=identity["id"],
        name="Synthetic destination",
        target={"path": str(tmp_path / "destination")},
        scope={"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
        include_rules={"originals": [], "attachments": [], "ai_receipts": []},
        mode=mode,
        confirmed=True,
    )
    observation = {
        "destination_sha256": destination["destination_sha256"],
        "visibility": "private",
        "writable": True,
        "inventory": [],
        "revision": "synthetic-empty-1",
    }
    return instance, engine, identity, destination, observation


def preview(engine, destination, observation):
    return engine.preview(destination["id"], observation, expected_revision=destination["revision"])


def arguments(plan, observation, **extra):
    return {
        "expected_plan_sha256": plan["plan_sha256"],
        "observation": observation,
        "confirmed": True,
        **extra,
    }


def test_snapshot_complete_deterministic_and_no_canonical_effect(tmp_path):
    instance, engine, _, destination, observation = seed(tmp_path)
    before = engine.snapshots.source_fingerprint()
    plan = preview(engine, destination, observation)
    again = preview(engine, destination, observation)
    assert plan == again
    manifest = engine.snapshots.verify(plan["generation"])
    assert manifest["complete"] and not manifest["canonical"]
    assert {row["category"] for row in manifest["inventory"]} == {"markdown", "metadata"}
    assert manifest["total_bytes"] == sum(row["size_bytes"] for row in manifest["inventory"])
    assert engine.snapshots.source_fingerprint() == before
    assert not (tmp_path / "destination").exists()
    assert plan["diff"]["delete"] == []
    assert engine.view()["publication"] == "TRANSPORT_NOT_QUALIFIED"
    assert instance.store.list_canonical("documents")


def test_disabled_and_passive_status_do_not_open_vault_or_dispatch(tmp_path):
    _, engine, _, destination, observation = seed(tmp_path, mode="disabled")
    reads = engine.vault.reads
    assert engine.view()["network_used"] is False
    assert engine.vault.reads == reads
    with pytest.raises(MirrorError, match="disabled"):
        preview(engine, destination, observation)
    assert engine.vault.reads == reads
    with pytest.raises(MirrorError, match="transport_not_qualified"):
        engine.dispatch("mirplan_" + "a" * 32, confirmed=True)
    assert engine.vault.reads == reads


@pytest.mark.parametrize("visibility", ["unknown", "public"])
def test_visibility_and_public_allowlist_are_closed(tmp_path, visibility):
    _, engine, _, destination, observation = seed(tmp_path)
    observation["visibility"] = visibility
    plan = preview(engine, destination, observation)
    with (
        engine.guard(),
        pytest.raises(
            MirrorError,
            match=("visibility_unknown" if visibility == "unknown" else "public_consent_required"),
        ),
    ):
        engine.validate_preview_locked(plan["id"], **arguments(plan, observation))


def test_public_exact_allowlist_and_confirmation_required(tmp_path):
    _, engine, identity, destination, observation = seed(tmp_path)
    observation["visibility"] = "public"
    first = preview(engine, destination, observation)
    destination = engine.configure(
        identity_id=identity["id"],
        name=destination["name"],
        target=engine._grant(identity)["destinations"][destination["id"]]["target"],
        scope=destination["scope"],
        include_rules=destination["include_rules"],
        mode="manual",
        public_allowlist=first["manifest"]["inventory"],
        destination_id=destination["id"],
        expected_revision=destination["revision"],
        confirmed=True,
    )
    plan = preview(engine, destination, observation)
    with engine.guard(), pytest.raises(MirrorError, match="public_consent_required"):
        engine.validate_preview_locked(plan["id"], **arguments(plan, observation))
    with engine.guard():
        validated, _ = engine.validate_preview_locked(
            plan["id"], **arguments(plan, observation, public_confirmed=True)
        )
    assert validated["id"] == plan["id"]
    # A correct shared preview still cannot qualify or invoke a real transport.
    with pytest.raises(MirrorError, match="transport_not_qualified"):
        engine.dispatch(plan["id"], **arguments(plan, observation, public_confirmed=True))


@pytest.mark.parametrize("mutation", ["destination", "policy", "source", "revoke"])
def test_changed_bound_inputs_invalidate_preview(tmp_path, mutation):
    instance, engine, identity, destination, observation = seed(tmp_path)
    plan = preview(engine, destination, observation)
    changed = deepcopy(observation)
    if mutation == "destination":
        changed["revision"] = "another-actor"
    elif mutation == "policy":
        engine.disable(destination["id"], expected_revision=destination["revision"], confirmed=True)
    elif mutation == "revoke":
        engine.revoke(identity["id"], expected_revision=identity["revision"], confirmed=True)
    else:
        extra = tmp_path / "extra"
        extra.mkdir()
        (extra / "new.md").write_text("# A later document\n")
        instance.ingest_run(extra)
    with engine.guard(), pytest.raises(MirrorError):
        engine.validate_preview_locked(plan["id"], **arguments(plan, changed))


def test_external_references_and_targets_absent_from_portable_policy(tmp_path):
    _, engine, identity, destination, observation = seed(tmp_path)
    plan = preview(engine, destination, observation)
    policy_bytes = (engine.store.paths.state / "mirrors/policies.json").read_text()
    assert str(tmp_path / "destination") not in policy_bytes
    assert "credential" not in policy_bytes and "reference" not in policy_bytes
    imported = Mirrors(engine.store, vault=SyntheticVault())
    assert imported.view()["identities"][0]["id"] == identity["id"]
    with pytest.raises(MirrorError, match="authorization_required"):
        imported.authority(destination["id"])
    assert imported.snapshots.verify(plan["generation"])["inventory"]


@pytest.mark.parametrize("mutation", ["change", "missing", "extra", "link"])
def test_sealed_generation_detects_tampering(tmp_path, mutation):
    _, engine, _, destination, observation = seed(tmp_path)
    plan = preview(engine, destination, observation)
    root = engine.snapshots.root() / plan["generation"]
    first = root / plan["manifest"]["inventory"][0]["path"]
    if mutation == "change":
        first.write_bytes(b"replacement")
    elif mutation == "missing":
        first.unlink()
    elif mutation == "extra":
        (root / "extra.txt").write_text("not inventoried")
    else:
        first.unlink()
        try:
            first.symlink_to(tmp_path / "input/readable.md")
        except OSError:
            pytest.skip("Host does not permit synthetic symlinks")
    with pytest.raises(ValueError):
        engine.snapshots.verify(plan["generation"])


@pytest.mark.parametrize(
    "body,code",
    [
        ("# Sample\naccess_token=synthetic_blocked_secret_value\n", "secret_pattern"),
        ("# Sample\nConfidential synthetic@example.invalid\n", "sensitive_pattern"),
    ],
)
def test_privacy_findings_block_without_echoing_values(tmp_path, body, code):
    _, engine, _, destination, observation = seed(tmp_path, text=body)
    plan = preview(engine, destination, observation)
    assert code in {row["code"] for row in plan["manifest"]["findings"]}
    assert "synthetic_blocked_secret_value" not in json.dumps(plan)
    with engine.guard(), pytest.raises(MirrorError, match=code):
        engine.validate_preview_locked(plan["id"], **arguments(plan, observation))


def test_exact_original_rule_and_no_implicit_attachments(tmp_path):
    instance, engine, identity, destination, observation = seed(tmp_path)
    original = instance.store.list_canonical("originals")[0]
    rules = {"originals": [original["id"]], "attachments": [], "ai_receipts": []}
    destination = engine.configure(
        identity_id=identity["id"],
        name=destination["name"],
        target=engine._grant(identity)["destinations"][destination["id"]]["target"],
        scope=destination["scope"],
        include_rules=rules,
        mode="manual",
        destination_id=destination["id"],
        expected_revision=1,
        confirmed=True,
    )
    plan = preview(engine, destination, observation)
    assert [row["category"] for row in plan["manifest"]["inventory"]].count("original") == 1
    data = (
        engine.snapshots.root() / plan["generation"] / ("originals/" + original["id"] + ".bin")
    ).read_bytes()
    assert data == instance.store.original_bytes(original["id"])


def test_claim_is_single_dispatch_and_final_receipt_requires_exact_inventory(tmp_path):
    _, engine, _, destination, observation = seed(tmp_path)
    plan = preview(engine, destination, observation)
    with engine.guard():
        engine._claim_locked(plan["id"], **arguments(plan, observation))
    restarted = Mirrors(engine.store, vault=engine.vault)
    with restarted.guard(), pytest.raises(MirrorError, match="stale"):
        restarted._claim_locked(plan["id"], **arguments(plan, observation))
    with restarted.guard():
        restarted._unknown_locked(plan["id"])
    with restarted.guard(), pytest.raises(MirrorError, match="destination_incomplete"):
        restarted._complete_locked(plan["id"], operation_id=plan["id"], observation=observation)
    completed = {
        **observation,
        "inventory": plan["manifest"]["inventory"],
        "revision": "activated-1",
    }
    with restarted.guard():
        receipt = restarted._complete_locked(
            plan["id"], operation_id=plan["id"], observation=completed
        )
    assert receipt["source_manifest_sha256"] == receipt["destination_manifest_sha256"]
    assert not receipt["backup_proof"] and not receipt["destination_deletion"]
    assert "readable" not in json.dumps(receipt)
    assert restarted.plan(plan["id"])["state"] == "completed"


def test_destination_only_content_is_retained_and_never_deleted():
    entry = {"path": "old.md", "size_bytes": 1, "sha256": "a" * 64, "category": "markdown"}
    result = diff([], [entry])
    assert result["retain_destination_only"] == ["old.md"]
    assert result["delete"] == []


@pytest.mark.parametrize("change", ["duplicate", "parent", "absolute", "case", "size", "hash"])
def test_inventory_rejects_hostile_or_incomplete_identity(change):
    entry = {"path": "safe.md", "size_bytes": 1, "sha256": "a" * 64, "category": "markdown"}
    entries = [entry]
    if change == "duplicate":
        entries.append(deepcopy(entry))
    elif change == "parent":
        entry["path"] = "../safe.md"
    elif change == "absolute":
        entry["path"] = "/safe.md"
    elif change == "case":
        entry["path"] = "CON.md"
    elif change == "size":
        entry["size_bytes"] = True
    else:
        entry["sha256"] = "not-a-digest"
    with pytest.raises(MirrorError):
        inventory(entries)


def test_discard_does_not_remove_staging_or_remote_and_releases_plan_only_explicitly(tmp_path):
    _, engine, _, destination, observation = seed(tmp_path)
    plan = preview(engine, destination, observation)
    with pytest.raises(MirrorError, match="outcome_unknown"):
        engine.forget_plan(plan["id"], confirmed=True)
    engine.discard(plan["id"], expected_plan_sha256=plan["plan_sha256"], confirmed=True)
    engine.forget_plan(plan["id"], confirmed=True)
    assert engine.plans() == []
    assert engine.snapshots.verify(plan["generation"])
    engine.drop_generation(plan["generation"], confirmed=True)
    assert not (tmp_path / "destination").exists()


def test_interrupted_staging_never_exposes_a_complete_generation(tmp_path, monkeypatch):
    _, engine, _, destination, observation = seed(tmp_path)
    original = engine.store._atomic_bytes
    calls = []

    def fail_midway(path, content):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("synthetic disk full")
        return original(path, content)

    monkeypatch.setattr("provelume.mirror_snapshot.InstanceStore._atomic_bytes", fail_midway)
    with pytest.raises(OSError, match="synthetic disk full"):
        preview(engine, destination, observation)
    assert list(engine.snapshots.root().iterdir()) == []
    assert engine.plans() == [] and not (tmp_path / "destination").exists()


def test_new_plan_cannot_escape_an_unknown_prior_dispatch(tmp_path):
    _, engine, _, destination, observation = seed(tmp_path)
    first = preview(engine, destination, observation)
    with engine.guard():
        engine._claim_locked(first["id"], **arguments(first, observation))
        engine._unknown_locked(first["id"])
    another = preview(engine, destination, observation)
    assert another["id"] != first["id"]
    with engine.guard(), pytest.raises(MirrorError, match="outcome_unknown"):
        engine._claim_locked(another["id"], **arguments(another, observation))


@pytest.mark.parametrize("language", ["en", "it", "de", "es", "fr", "pt", "ro"])
def test_real_local_http_preview_csrf_closed_forms_and_no_passive_vault_access(tmp_path, language):
    from fastapi.testclient import TestClient

    from provelume.web import create_app

    instance, engine, _, destination, _ = seed(tmp_path)
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    app.state.provelume._mirrors_manager = engine
    client = TestClient(app)
    reads = engine.vault.reads
    page = client.get("/mirrors?lang=" + language)
    assert page.status_code == 200 and "mirror.title" not in page.text
    assert engine.vault.reads == reads
    assert client.post("/mirrors", data={"action": "prepare"}).status_code == 403
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    form = {
        "csrf_token": csrf,
        "action": "prepare",
        "destination_id": destination["id"],
        "revision": "1",
        "confirm": "yes",
    }
    rejected = client.post("/mirrors", data={**form, "publish": "yes"}, follow_redirects=False)
    assert rejected.status_code == 303 and engine.plans() == []
    prepared = client.post("/mirrors?lang=" + language, data=form)
    assert prepared.status_code == 200 and 'id="mirror-preview"' in prepared.text
    assert "Readable offline body" not in prepared.text
    plan = engine.plans()[0]
    assert plan["observation"]["visibility"] == "unknown"
    assert plan["observation"]["writable"] is False
    assert 'id="mirror-unavailable"' in prepared.text
    assert not (tmp_path / "destination").exists()


def test_automatic_frozen_qualification_is_separate_from_transport_acceptance(tmp_path):
    from provelume.ocr_desktop import run_ocr_command

    target = tmp_path / "Fresh Synthetic Mirror Qualification"
    result = tmp_path / "mirror-operator-result.json"
    assert run_ocr_command(["mirror-qualify", str(target)], result) == 0
    report = json.loads(result.read_bytes())
    assert report["result"] == "PASS" and report["canonical_unchanged"]
    assert report["real_transports"] == "NOT_RUN" and not report["network_used"]
    assert not report["transport_process_used"]
    assert report["offline_portable_no_grant"] == "PASS"
    assert report["windows_11_pro_25h2_manual"] == "DEFERRED_BY_MAINTAINER / NOT_RUN"
    assert run_ocr_command(["mirror-qualify", str(target)], tmp_path / "reused.json") == 2


def test_scheduled_policy_prepares_local_only_and_respects_interval_and_disabled(tmp_path):
    from provelume.mirror_jobs import MirrorJobs

    instance, engine, identity, destination, _ = seed(tmp_path)
    destination = engine.configure(
        identity_id=identity["id"],
        name=destination["name"],
        target=engine._grant(identity)["destinations"][destination["id"]]["target"],
        scope=destination["scope"],
        include_rules=destination["include_rules"],
        mode="scheduled",
        interval_seconds=300,
        destination_id=destination["id"],
        expected_revision=1,
        confirmed=True,
    )
    bridge = MirrorJobs(instance.store, mirrors=engine)
    policy = bridge.policy()
    instance.scheduler._mirror_manager_factory = lambda _store: bridge
    assert policy["state"] == "enabled" and policy["retry"]["max_attempts"] == 1
    job = bridge.scheduler.run_now(policy["id"])["job"]
    executed = instance.scheduler.run_one(job_id=job["id"])
    assert executed["status"] == "succeeded"
    assert len(engine.plans()) == 1 and engine.plans()[0]["scheduled"]
    job = bridge.scheduler.run_now(policy["id"], request_key="synthetic-next")["job"]
    assert instance.scheduler.run_one(job_id=job["id"])["status"] == "succeeded"
    assert len(engine.plans()) == 1
    engine.disable(destination["id"], expected_revision=2, confirmed=True)
    assert bridge.policy()["state"] == "disabled"
    assert not (tmp_path / "destination").exists()


@pytest.mark.parametrize(
    "profile,enabled,code",
    [
        ("folder", False, "local_only"),
        ("github", True, "github_disabled"),
        ("rsync-ssh", True, "rsync_disabled"),
    ],
)
def test_access_modes_refuse_before_credential_or_destination_access(
    tmp_path, profile, enabled, code
):
    _, engine, _, destination, observation = seed(tmp_path, profile=profile)
    engine.set_access(
        enabled=enabled, github=False, rsync=False, expected_revision=1, confirmed=True
    )
    reads = engine.vault.reads
    with pytest.raises(MirrorError, match=code):
        preview(engine, destination, observation)
    assert engine.vault.reads == reads and engine.plans() == []
    assert not (tmp_path / "destination").exists()
