"""Independent exact-version Gitea contract and native Git, no real-user fixture."""

from unittest.mock import patch

import pytest

from provelume.mirror_contract import MirrorError
from provelume.mirror_git_runtime import GitSession
from provelume.mirror_gitea_contract import PROFILE, configuration
from provelume.mirror_gitea_helper import credential_response
from provelume.mirror_gitea_http import GiteaHttp, admitted_request
from provelume.mirror_gitea_qualification import synthetic_fixture, target


def prepare(engine, row):
    return engine.prepare(row["id"], expected_revision=row["revision"], confirmed=True)


def publish(engine, plan, **extra):
    return engine.publish(
        plan["id"],
        expected_plan_sha256=plan["plan_sha256"],
        expected_git_plan_sha256=plan["git_plan_sha256"],
        confirmed=True,
        **extra,
    )


def test_exact_gitea_profile_native_git_and_noop_are_independent(tmp_path):
    _instance, mirrors, engine, row, api = synthetic_fixture(tmp_path)
    before = mirrors.snapshots.source_fingerprint()
    plan = prepare(engine, row)
    assert plan["git_plan"]["provider_binding"]["repository"]["server_version"] == "28.3.0"
    assert plan["git_plan"]["transfer"]["permission_probe"]["remote_mutation"] is False
    first = publish(engine, plan)["receipt"]
    assert first["transport_proof"]["profile"] == PROFILE
    count = len(api.calls)
    assert publish(engine, plan)["historical"] and len(api.calls) == count
    assert not publish(engine, prepare(engine, row))["receipt"]["transport_proof"]["commit_written"]
    assert mirrors.snapshots.source_fingerprint() == before


@pytest.mark.parametrize("scopes", [["read:user", "read:repository"], ["write:repository"], []])
def test_actual_token_scope_required_even_when_repository_role_can_push(tmp_path, scopes):
    _instance, mirrors, engine, row, api = synthetic_fixture(tmp_path)
    plan = prepare(engine, row)
    api.token["scopes"] = scopes
    with pytest.raises(MirrorError, match="gitea_write_unproven|gitea_token_profile"):
        publish(engine, plan)
    assert mirrors.operation_ledger(row["id"])["serial"] == 0


@pytest.mark.parametrize(
    "key,value,code",
    [
        ("id", 12, "gitea_repository_changed"),
        ("full_name", "synthetic/replaced", "gitea_repository_changed"),
        ("clone_url", "https://evil.invalid/never-send.git", "gitea_repository_changed"),
        ("internal", True, "visibility_unknown"),
        ("private", None, "visibility_unknown"),
        ("private", False, "gitea_visibility_changed"),
        ("permissions", {"push": False}, "gitea_read_only"),
    ],
)
def test_repository_drift_blocks_before_claim(tmp_path, key, value, code):
    _instance, mirrors, engine, row, api = synthetic_fixture(tmp_path)
    plan = prepare(engine, row)
    api.repo[key] = value
    with pytest.raises(MirrorError, match=code):
        publish(engine, plan)
    assert mirrors.operation_ledger(row["id"])["serial"] == 0


def test_server_patch_or_account_change_is_not_silently_qualified(tmp_path):
    _instance, _mirrors, engine, row, api = synthetic_fixture(tmp_path)
    plan = prepare(engine, row)
    api.version["version"] = "28.3.1"
    with pytest.raises(MirrorError, match="gitea_profile_not_qualified"):
        publish(engine, plan)
    api.version["version"] = "28.3.0"
    api.user["id"] = 2
    with pytest.raises(MirrorError, match="gitea_identity_changed"):
        publish(engine, plan)


def test_interrupted_send_real_root_restore_and_readonly_recovery(tmp_path):
    instance, mirrors, engine, row, _api = synthetic_fixture(tmp_path)
    plan = prepare(engine, row)
    backup = instance.backup(destination=tmp_path / "Before send")
    run, sends = GitSession.run, []

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
        mode="current-token",
        confirmed=True,
        identity_id=row["identity_id"],
    )
    result = engine.reconcile(plan["id"], confirmed=True)
    assert result["receipt"]["transport_proof"]["evidence_mode"] == "reconciled_current_state"
    assert len(sends) == 1 and publish(engine, plan)["historical"]


def test_closed_worker_does_not_send_token_to_another_origin_or_method():
    request = admitted_request(
        {
            "route": "/token",
            "token": "synthetic",
            "probe": False,
            "endpoint": "https://127.0.0.1:30443",
            "ca_pem": "",
        }
    )
    assert (
        request.get_method() == "GET" and request.get_header("Authorization") == "token synthetic"
    )
    assert request.full_url == "https://127.0.0.1:30443/api/v1/token"
    for route in ["https://evil.invalid/", "/token?sudo=admin", "/repos/a/b/git/refs"]:
        with (
            patch("subprocess.run", side_effect=AssertionError("worker started")),
            pytest.raises(MirrorError, match="gitea_endpoint"),
        ):
            GiteaHttp().request(route, token="synthetic", endpoint=target()["endpoint"], ca_pem="")


@pytest.mark.parametrize(
    "bad",
    [
        "http://127.0.0.1",
        "https://user:password@example.invalid",
        "https://example.invalid/path",
        "https://example.invalid?other=host",
    ],
)
def test_endpoint_and_trust_must_be_explicit_and_qualified(bad):
    selected = target()
    selected["endpoint"] = bad
    with pytest.raises(MirrorError, match="gitea_endpoint"):
        configuration(selected)


def test_invalid_ca_or_wrong_git_credential_query_is_rejected_before_send():
    selected = target()
    selected["ca_pem"] = "-----BEGIN PRIVATE KEY-----\nSYNTHETIC\n-----END PRIVATE KEY-----"
    with pytest.raises(MirrorError, match="gitea_certificate"):
        configuration(selected)
    for host in ["github.com", "127.0.0.1:30444"]:
        with pytest.raises(MirrorError, match="gitea_credential_query"):
            credential_response(
                f"protocol=https\nhost={host}\npath=synthetic/qualification.git\n\n".encode(),
                target=target(),
                credential={
                    "token": "synthetic",
                    "identity": {"principal": {"login": "synthetic"}},
                },
            )
    assert (
        credential_response(
            b"protocol=https\nhost=127.0.0.1:30443\npath=synthetic/qualification.git\n\n",
            target=target(),
            credential={"token": "synthetic", "identity": {"principal": {"login": "synthetic"}}},
        )
        == b"username=synthetic\npassword=synthetic\n\n"
    )


def test_external_configuration_token_is_blocked_but_pagination_metadata_is_not():
    from provelume.mirror_contract import findings

    assert "secret_pattern" in findings(b'{"token":"0123456789abcdef0123456789abcdef01234567"}')
    assert "secret_pattern" not in findings(b'{"nextPageToken":"synthetic-opaque-pagination"}')


def test_public_gitea_publication_needs_exact_logical_and_physical_approval(tmp_path):
    _instance, mirrors, engine, row, _api = synthetic_fixture(tmp_path, public=True)
    first = prepare(engine, row)
    with pytest.raises(MirrorError, match="public_consent_required"):
        publish(engine, first)
    identity = mirrors.identity(row["identity_id"])
    selected = mirrors._grant(identity)["destinations"][row["id"]]["target"]
    row = mirrors.configure(
        identity_id=identity["id"],
        name=row["name"],
        target=selected,
        scope=row["scope"],
        include_rules=row["include_rules"],
        mode="manual",
        destination_id=row["id"],
        expected_revision=1,
        confirmed=True,
        public_allowlist=first["manifest"]["inventory"],
    )
    plan = prepare(engine, row)
    result = publish(engine, plan, expected_transfer_sha256=plan["git_plan"]["transfer_sha256"])
    assert result["receipt"]["transport_proof"]["provider_observation"]["visibility"] == "public"


def test_source_frozen_operator_and_default_off_passive_cli_status(tmp_path, monkeypatch, capsys):
    import json

    from provelume.cli import main
    from provelume.ocr_desktop import run_ocr_command

    output = tmp_path / "result.json"
    assert run_ocr_command(["gitea-mirror-qualify", str(tmp_path / "Fresh Gitea")], output) == 0
    report = json.loads(output.read_bytes())
    assert report["result"] == "PASS" and report["real_gitea"] == "NOT_RUN"
    assert report["http_worker_refusal"] == "PASS" and not report["network_used"]

    def forbidden(*_args, **_kwargs):
        pytest.fail("Passive status started a native process")

    monkeypatch.setattr(GitSession, "run", forbidden)
    assert main(["mirror-gitea-status", str(tmp_path / "Fresh Gitea" / "Instance")]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["profile"] == PROFILE


def test_local_csrf_ui_uses_gitea_backend_and_passive_get_has_no_transport(tmp_path, monkeypatch):
    import re

    from fastapi.testclient import TestClient

    from provelume.mirror_contract import fingerprint
    from provelume.web import create_app

    instance, mirrors, engine, row, api = synthetic_fixture(tmp_path)
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    app.state.provelume._mirrors_manager = mirrors
    monkeypatch.setattr(app.state.provelume, "gitea_mirrors", lambda: engine)
    client = TestClient(app)
    page = client.get("/mirrors?lang=it")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    assert client.post("/mirrors", data={"action": "gitea-prepare"}).status_code == 403
    result = client.post(
        "/mirrors?lang=it",
        data={"csrf_token": csrf, "action": "gitea-prepare", "destination_id": row["id"],
              "revision": "1", "confirm": "yes"},
    )
    assert result.status_code == 200 and 'id="mirror-gitea-transfer"' in result.text
    plan, git_plan = engine.git_plan(mirrors.plans()[0]["id"])
    result = client.post(
        "/mirrors?lang=it",
        data={"csrf_token": csrf, "action": "gitea-publish", "plan_id": plan["id"],
              "plan_sha256": fingerprint(plan), "git_plan_sha256": fingerprint(git_plan),
              "transfer_sha256": git_plan["transfer_sha256"], "public_confirm": "no",
              "confirm": "yes"},
    )
    assert result.status_code == 200 and 'id="mirror-git-receipt"' in result.text
    count, reads = len(api.calls), mirrors.vault.reads
    with patch.object(GitSession, "run", side_effect=AssertionError("passive process")):
        for language in ["en", "it", "de", "fr", "es", "pt", "ro"]:
            assert (
                client.get("/mirrors?lang=" + language + "&plan=" + plan["id"]).status_code == 200
            )
    assert len(api.calls) == count and mirrors.vault.reads == reads
