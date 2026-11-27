"""Synthetic GitHub responses and native file Git; real SaaS is explicitly NOT_RUN."""

from unittest.mock import patch

import pytest

from provelume.mirror_contract import MirrorError, fingerprint
from provelume.mirror_git_runtime import GitSession
from provelume.mirror_github_contract import (
    API_VERSION,
    PROBE,
    PROBE_OID,
    configuration,
    repository_observation,
)
from provelume.mirror_github_helper import credential_response
from provelume.mirror_github_http import GitHubHttp, admitted_request
from provelume.mirror_github_qualification import SyntheticApi, target
from provelume.mirror_github_qualification import synthetic_fixture as fixture


def prepare(engine, destination):
    return engine.prepare(
        destination["id"], expected_revision=destination["revision"], confirmed=True
    )


def publish(engine, plan, **extra):
    return engine.publish(
        plan["id"],
        expected_plan_sha256=plan["plan_sha256"],
        expected_git_plan_sha256=plan["git_plan_sha256"],
        confirmed=True,
        **extra,
    )


def test_synthetic_api_native_git_publication_noop_and_external_receipt(tmp_path):
    _instance, mirrors, engine, destination, api = fixture(tmp_path)
    before = mirrors.snapshots.source_fingerprint()
    plan = prepare(engine, destination)
    transfer = plan["git_plan"]["transfer"]
    assert any(row["path"].endswith("/namespace.json") for row in transfer["files"])
    assert any(row["path"].endswith("/active.json") for row in transfer["files"])
    assert any(row["path"].endswith("/manifest.json") for row in transfer["files"])
    assert transfer["permission_probe"]["git_blob_sha"] == PROBE_OID
    result = publish(engine, plan)
    assert result["receipt"]["transport_proof"]["profile"] == "github.com/2022-11-28"
    assert result["receipt"]["transport_proof"]["provider_observation"]["repository_id"] == 17
    count = len(api.calls)
    assert publish(engine, plan)["historical"]
    assert len(api.calls) == count
    repeated = publish(engine, prepare(engine, destination))
    assert repeated["receipt"]["transport_proof"]["commit_written"] is False
    assert mirrors.snapshots.source_fingerprint() == before
    assert b"synthetic-valid" not in b"".join(
        p.read_bytes() for p in mirrors.store.paths.root.rglob("*") if p.is_file()
    )


@pytest.mark.parametrize(
    "key,value,code",
    [
        ("id", 18, "github_repository_changed"),
        ("full_name", "synthetic/transferred", "github_repository_changed"),
        ("clone_url", "https://evil.invalid/a.git", "github_repository_changed"),
        ("visibility", "unknown", "visibility_unknown"),
        ("private", False, "visibility_unknown"),
        ("archived", True, "github_read_only"),
        ("permissions", {"push": False}, "github_read_only"),
    ],
)
def test_provider_drift_is_refused_before_claim(tmp_path, key, value, code):
    _instance, mirrors, engine, destination, api = fixture(tmp_path)
    plan = prepare(engine, destination)
    api.repo[key] = value
    with pytest.raises(MirrorError, match=code):
        publish(engine, plan)
    assert mirrors.operation_ledger(destination["id"])["serial"] == 0


def test_repository_role_cannot_substitute_for_token_contents_write(tmp_path):
    _instance, mirrors, engine, destination, api = fixture(tmp_path)
    plan = prepare(engine, destination)
    api.writable = False
    with pytest.raises(MirrorError, match="authorization_required"):
        publish(engine, plan)
    assert mirrors.operation_ledger(destination["id"])["serial"] == 0


def test_explicit_connection_probe_consent_and_wrong_account_renewal(tmp_path):
    _instance, _mirrors, engine, _destination, api = fixture(tmp_path)
    with pytest.raises(MirrorError, match="consent_required"):
        engine.connect(
            name="x",
            target=target(),
            token="synthetic-valid",
            mode="user",
            confirmed=True,
            probe_confirmed=False,
        )
    identity = engine.mirrors.state()["identities"][0]
    api.identity["id"] = 24
    with pytest.raises(MirrorError, match="github_identity_changed"):
        engine.connect(
            name="x",
            target=target(),
            token="synthetic-valid",
            mode="user",
            confirmed=True,
            probe_confirmed=True,
            identity_id=identity["id"],
        )


def test_public_transfer_requires_logical_and_physical_allowlists(tmp_path):
    _instance, mirrors, engine, destination, api = fixture(tmp_path, public=True)
    first = prepare(engine, destination)
    with pytest.raises(MirrorError, match="public_consent_required"):
        publish(engine, first)
    identity = mirrors.identity(destination["identity_id"])
    configuration_value = mirrors._grant(identity)["destinations"][destination["id"]]["target"]
    destination = mirrors.configure(
        identity_id=identity["id"],
        name=destination["name"],
        target=configuration_value,
        scope=destination["scope"],
        include_rules=destination["include_rules"],
        mode="manual",
        destination_id=destination["id"],
        expected_revision=1,
        confirmed=True,
        public_allowlist=first["manifest"]["inventory"],
    )
    plan = prepare(engine, destination)
    with pytest.raises(MirrorError, match="public_consent_required"):
        publish(engine, plan, expected_transfer_sha256=fingerprint(plan["manifest"]["inventory"]))
    result = publish(engine, plan, expected_transfer_sha256=plan["git_plan"]["transfer_sha256"])
    assert result["receipt"]["transport_proof"]["provider_observation"]["visibility"] == "public"
    assert mirrors.operation_ledger(destination["id"])["serial"] == 1


def test_credential_renewal_invalidates_write_but_readonly_restore_recovery_works(tmp_path):
    instance, mirrors, engine, destination, api = fixture(tmp_path)
    plan = prepare(engine, destination)
    backup = instance.backup(destination=tmp_path / "before-send")
    run = GitSession.run
    sends = []

    def interrupted(session, arguments, **options):
        result = run(session, arguments, **options)
        if arguments[0] == "push":
            sends.append(True)
            raise MirrorError("deadline")
        return result

    with patch.object(GitSession, "run", interrupted), pytest.raises(MirrorError, match="deadline"):
        publish(engine, plan)
    assert instance.restore(backup["archive"])["status"] == "restored"
    engine.connect(
        name="renewed",
        target=target(),
        token="synthetic-renewed",
        mode="user",
        confirmed=True,
        probe_confirmed=True,
        identity_id=destination["identity_id"],
    )
    probes = sum(probe for _route, probe in api.calls)
    result = engine.reconcile(plan["id"], confirmed=True)
    assert result["receipt"]["transport_proof"]["evidence_mode"] == "reconciled_current_state"
    assert sum(probe for _route, probe in api.calls) == probes  # Strictly read-only recovery.
    assert len(sends) == 1
    assert publish(engine, plan)["historical"]


def test_connection_renewal_before_send_stales_preview(tmp_path):
    _instance, mirrors, engine, destination, _api = fixture(tmp_path)
    plan = prepare(engine, destination)
    engine.connect(
        name="renewed",
        target=target(),
        token="synthetic-renewed",
        mode="user",
        confirmed=True,
        probe_confirmed=True,
        identity_id=destination["identity_id"],
    )
    with pytest.raises(MirrorError, match="destination_changed"):
        publish(engine, plan)
    assert mirrors.operation_ledger(destination["id"])["serial"] == 0


@pytest.mark.parametrize("mode", ["off", "github-off"])
def test_disabled_gates_precede_vault_process_network_and_status_is_passive(tmp_path, mode):
    _instance, mirrors, engine, destination, api = fixture(tmp_path)
    mirrors.set_access(
        enabled=mode != "off", github=False, rsync=False, expected_revision=1, confirmed=True
    )
    calls = len(api.calls)
    with (
        patch.object(mirrors.vault, "read", side_effect=AssertionError("vault read")),
        patch.object(GitSession, "run", side_effect=AssertionError("Git process")),
    ):
        assert engine.status()["network_used"] is False
        with pytest.raises(MirrorError, match="local_only|github_disabled"):
            prepare(engine, destination)
    assert len(api.calls) == calls


@pytest.mark.parametrize(
    "route",
    [
        "https://evil.invalid/user",
        "/user?token=secret",
        "/repos/a/b/../c",
        "/repos/a/b/git/refs",
        "/installation/repositories?per_page=100&page=6",
    ],
)
def test_http_closed_routes_refuse_before_worker_or_network(route):
    with (
        patch("subprocess.run", side_effect=AssertionError("worker started")),
        pytest.raises(MirrorError, match="github_endpoint"),
    ):
        GitHubHttp().request(route, token="synthetic")


def test_http_request_has_exact_fixed_probe_bytes_version_and_no_redirect_route():
    request = admitted_request(
        {"route": "/repos/a/b/git/blobs", "token": "synthetic", "probe": True}
    )
    import base64

    from provelume.mirror_contract import parse

    assert base64.b64decode(parse(request.data)["content"]) == PROBE
    assert request.get_header("X-github-api-version") == API_VERSION
    assert request.get_method() == "POST"
    with pytest.raises(MirrorError, match="github_endpoint"):
        admitted_request({"route": "/repos/a/b/git/refs", "token": "synthetic", "probe": True})


@pytest.mark.parametrize(
    "query",
    [
        b"protocol=http\nhost=github.com\npath=synthetic/qualification.git\n",
        b"protocol=https\nhost=evil.invalid\npath=synthetic/qualification.git\n",
        b"protocol=https\nhost=github.com\npath=synthetic/wrong.git\n",
        b"protocol=https\nhost=github.com\npath=synthetic/qualification.git\npassword=x\n",
    ],
)
def test_owned_credential_helper_never_answers_wrong_origin_path_or_protocol(query):
    with pytest.raises(MirrorError, match="github_credential_query"):
        credential_response(query, target=target(), credential={"token": "synthetic"})


def test_owned_credential_helper_exact_secret_pipe_payload():
    response = credential_response(
        b"protocol=https\nhost=github.com\n"
        b"path=synthetic/qualification.git\ncapability[]=authtype\nwwwauth[]=Basic\n\n",
        target=target(),
        credential={"token": "synthetic"},
    )
    assert response == b"username=x-access-token\npassword=synthetic\n\n"


def test_installation_access_is_independent_and_pagination_must_be_complete(tmp_path):
    _instance, _mirrors, engine, destination, api = fixture(tmp_path, mode="installation")
    plan = prepare(engine, destination)
    identity = plan["git_plan"]["provider_binding"]["identity"]
    assert identity["mode"] == "installation" and identity["principal"] is None
    api.total = 2  # An incomplete listing cannot prove repository grant.
    with pytest.raises(MirrorError, match="github_access_unproven"):
        publish(engine, plan)


def test_unknown_profile_and_contradictory_visibility_are_not_qualified():
    selected = target()
    selected["api_version"] = "2099-01-01"
    with pytest.raises(MirrorError, match="github_profile_not_qualified"):
        configuration(selected)
    repo = SyntheticApi().repo
    del repo["visibility"]
    with pytest.raises(MirrorError, match="visibility_unknown"):
        repository_observation(repo, target())


def test_source_frozen_operator_uses_same_native_synthetic_profile(tmp_path):
    import json

    from provelume.ocr_desktop import run_ocr_command

    output = tmp_path / "result.json"
    assert (
        run_ocr_command(["github-mirror-qualify", str(tmp_path / "Synthetic Trial")], output) == 0
    )
    report = json.loads(output.read_bytes())
    assert report["result"] == "PASS" and report["real_github"] == "NOT_RUN"
    assert report["http_worker_refusal"] == "PASS" and not report["network_used"]
    assert report["manuals"] == "DEFERRED_BY_MAINTAINER / NOT_RUN"


def test_tampered_physical_transfer_is_recomputed_before_claim(tmp_path):
    _instance, mirrors, engine, destination, _api = fixture(tmp_path)
    plan = prepare(engine, destination)
    git_plan = plan["git_plan"]
    git_plan["transfer"]["files"] = git_plan["transfer"]["files"][:1]
    git_plan["transfer_sha256"] = fingerprint(git_plan["transfer"])
    mirrors._save("git/plans/" + plan["id"] + ".json", git_plan)
    plan["git_plan_sha256"] = fingerprint(git_plan)
    with pytest.raises(MirrorError, match="github_transfer_changed"):
        publish(engine, plan)
    assert mirrors.operation_ledger(destination["id"])["serial"] == 0


def test_foreign_namespace_refuses_before_claim_and_preserves_remote(tmp_path):
    from provelume.mirror_git import git_work, remote_ref

    _instance, mirrors, engine, destination, _api = fixture(tmp_path)
    first = publish(engine, prepare(engine, destination))
    before = first["receipt"]["transport_proof"]["commit_sha"]
    identity = mirrors.identity(destination["identity_id"])
    grant = mirrors._grant(identity)
    selected = grant["destinations"][destination["id"]]["target"]
    selected["namespace"] = "b" * 32
    destination = mirrors.configure(
        identity_id=identity["id"],
        name=destination["name"],
        target=selected,
        scope=destination["scope"],
        include_rules=destination["include_rules"],
        mode="manual",
        destination_id=destination["id"],
        expected_revision=1,
        confirmed=True,
    )
    with pytest.raises(MirrorError, match="github_namespace"):
        prepare(engine, destination)
    with git_work() as session:
        assert remote_ref(session, engine.synthetic_remote.as_uri(), "concordia") == before
    assert mirrors.operation_ledger(destination["id"])["serial"] == 1


def test_private_to_public_change_after_send_remains_unknown_without_replay(tmp_path):
    _instance, mirrors, engine, destination, api = fixture(tmp_path)
    plan = prepare(engine, destination)
    run, sends = GitSession.run, []

    def changed(session, arguments, **options):
        result = run(session, arguments, **options)
        if arguments[0] == "push":
            sends.append(True)
            api.repo.update(visibility="public", private=False)
        return result

    with (
        patch.object(GitSession, "run", changed),
        pytest.raises(MirrorError, match="github_visibility_changed"),
    ):
        publish(engine, plan)
    assert mirrors.plan(plan["id"])["state"] == "unknown"
    with pytest.raises(MirrorError, match="outcome_unknown"):
        publish(engine, plan)
    assert len(sends) == 1
