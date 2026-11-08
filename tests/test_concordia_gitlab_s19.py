"""GitLab-specific contract errors, real native Git and synthetic recovery."""

from unittest.mock import patch

import pytest

from provelume.mirror_contract import MirrorError, findings
from provelume.mirror_git_runtime import GitSession
from provelume.mirror_gitlab_contract import PROFILE, configuration, token_observation
from provelume.mirror_gitlab_helper import credential_response
from provelume.mirror_gitlab_http import GitLabHttp, admitted_request
from provelume.mirror_gitlab_qualification import SyntheticApi, synthetic_fixture, target


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


def test_synthetic_gitlab_capability_and_native_git_are_independent_from_github(tmp_path):
    _instance, mirrors, engine, row, api = synthetic_fixture(tmp_path)
    before = mirrors.snapshots.source_fingerprint()
    assert not mirrors.access()["github"]
    plan = prepare(engine, row)
    binding = plan["git_plan"]["provider_binding"]
    assert binding["identity"]["principal"]["git_write_scope"] == "read_api+write_repository"
    assert binding["repository"]["server_version"] == "19.5.1"
    assert plan["git_plan"]["transfer"]["permission_probe"]["remote_mutation"] is False
    receipt = publish(engine, plan)["receipt"]
    assert receipt["transport_proof"]["profile"] == PROFILE
    count = len(api.calls)
    assert publish(engine, plan)["historical"] and len(api.calls) == count
    assert not publish(engine, prepare(engine, row))["receipt"]["transport_proof"]["commit_written"]
    assert mirrors.snapshots.source_fingerprint() == before


@pytest.mark.parametrize("scopes", [["read_api"], ["read_repository"], ["write_repository"], []])
def test_project_developer_role_does_not_replace_token_write_scope(tmp_path, scopes):
    _instance, mirrors, engine, row, api = synthetic_fixture(tmp_path)
    plan = prepare(engine, row)
    api.token["scopes"] = scopes
    with pytest.raises(MirrorError, match="gitlab_write_unproven|gitlab_token_profile"):
        publish(engine, plan)
    assert mirrors.operation_ledger(row["id"])["serial"] == 0


@pytest.mark.parametrize(
    "key,value,code",
    [
        ("revoked", True, "authorization_required"),
        ("active", False, "authorization_required"),
        ("expires_at", "2020-01-01", "authorization_required"),
        ("user_id", 42, "authorization_required"),
        ("granular_scopes", [{"access": "read"}], "gitlab_token_profile"),
    ],
)
def test_gitlab_token_native_errors_refuse_before_claim(tmp_path, key, value, code):
    _instance, mirrors, engine, row, api = synthetic_fixture(tmp_path)
    plan = prepare(engine, row)
    api.token[key] = value
    with pytest.raises(MirrorError, match=code):
        publish(engine, plan)
    assert mirrors.operation_ledger(row["id"])["serial"] == 0


@pytest.mark.parametrize(
    "key,value,code",
    [
        ("id", 32, "gitlab_repository_changed"),
        ("path_with_namespace", "synthetic/transferred", "gitlab_repository_changed"),
        ("http_url_to_repo", "https://evil.invalid/a.git", "gitlab_repository_changed"),
        ("visibility", "internal", "visibility_unknown"),
        ("visibility", "public", "gitlab_visibility_changed"),
        ("archived", True, "gitlab_read_only"),
        ("repository_access_level", "disabled", "gitlab_read_only"),
        ("permissions", {"project_access": {"access_level": 20}}, "gitlab_write_unproven"),
    ],
)
def test_gitlab_project_errors_refuse_before_claim(tmp_path, key, value, code):
    _instance, mirrors, engine, row, api = synthetic_fixture(tmp_path)
    plan = prepare(engine, row)
    api.repo[key] = value
    with pytest.raises(MirrorError, match=code):
        publish(engine, plan)
    assert mirrors.operation_ledger(row["id"])["serial"] == 0


def test_same_root_restore_and_credential_renewal_recover_without_resend(tmp_path):
    instance, mirrors, engine, row, _api = synthetic_fixture(tmp_path)
    plan = prepare(engine, row)
    backup = instance.backup(destination=tmp_path / "before-send")
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
        mode="classic-pat",
        confirmed=True,
        identity_id=row["identity_id"],
    )
    receipt = engine.reconcile(plan["id"], confirmed=True)["receipt"]
    assert receipt["transport_proof"]["evidence_mode"] == "reconciled_current_state"
    assert len(sends) == 1 and publish(engine, plan)["historical"]


def test_public_transfer_requires_full_logical_inventory_and_control_files(tmp_path):
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
    assert any(f["path"].endswith("namespace.json") for f in plan["git_plan"]["transfer"]["files"])
    assert publish(engine, plan, expected_transfer_sha256=plan["git_plan"]["transfer_sha256"])[
        "receipt"
    ]


def test_own_http_worker_profile_has_closed_readonly_routes():
    request = admitted_request(
        {"route": "/personal_access_tokens/self", "token": "synthetic", "probe": False}
    )
    assert request.full_url == "https://gitlab.com/api/v4/personal_access_tokens/self"
    assert request.get_header("Private-token") == "synthetic" and request.get_method() == "GET"
    for route in [
        "https://evil.invalid/",
        "/projects/31/repository/files/a",
        "/projects/-1",
        "/projects/31?sudo=other",
        "/user/../oauth",
    ]:
        with (
            patch("subprocess.run", side_effect=AssertionError("worker started")),
            pytest.raises(MirrorError, match="gitlab_endpoint"),
        ):
            GitLabHttp().request(route, token="synthetic")


def test_gitlab_credential_helper_never_answers_github_or_other_project():
    for host, repository in [
        ("github.com", "synthetic/group/qualification"),
        ("gitlab.com", "synthetic/other"),
    ]:
        query = f"protocol=https\nhost={host}\npath={repository}.git\n\n".encode()
        with pytest.raises(MirrorError, match="gitlab_credential_query"):
            credential_response(query, target=target(), credential={"token": "synthetic"})
    assert (
        credential_response(
            b"protocol=https\nhost=gitlab.com\npath=synthetic/group/qualification.git\n\n",
            target=target(),
            credential={"token": "synthetic"},
        )
        == b"username=x-access-token\npassword=synthetic\n\n"
    )


def test_private_secret_pattern_includes_gitlab_classic_pat():
    assert findings(b"glpat-" + b"SYNTHETIC" * 4) == ["secret_pattern"]


def test_group_role_and_api_scope_are_observed_independently():
    from provelume.mirror_gitlab_contract import repository_observation

    api = SyntheticApi()
    api.repo["permissions"] = {"project_access": None, "group_access": {"access_level": 40}}
    assert repository_observation(api.repo, target())["effective_access_level"] == 40
    api.token["scopes"] = ["api"]
    assert token_observation(api.token, api.user)["git_write_scope"] == "api"
    selected = target()
    selected["api_version"] = "v5"
    with pytest.raises(MirrorError, match="gitlab_profile_not_qualified"):
        configuration(selected)


def test_global_off_and_status_do_not_read_vault_or_start_git(tmp_path):
    _instance, mirrors, engine, row, _api = synthetic_fixture(tmp_path)
    mirrors.set_access(
        enabled=False, github=False, rsync=False, expected_revision=1, confirmed=True
    )
    with (
        patch.object(mirrors.vault, "read", side_effect=AssertionError("vault")),
        patch.object(GitSession, "run", side_effect=AssertionError("Git")),
    ):
        assert not engine.status()["network_used"]
        with pytest.raises(MirrorError, match="local_only"):
            prepare(engine, row)


def test_source_frozen_operator_and_cli_passive_status(tmp_path, monkeypatch, capsys):
    import json

    from provelume.cli import main
    from provelume.ocr_desktop import run_ocr_command

    output = tmp_path / "result.json"
    assert run_ocr_command(["gitlab-mirror-qualify", str(tmp_path / "Fresh GitLab")], output) == 0
    report = json.loads(output.read_bytes())
    assert report["result"] == "PASS" and report["real_gitlab"] == "NOT_RUN"
    assert report["http_worker_refusal"] == "PASS" and report["resends"] == 0

    def forbidden(*_args, **_kwargs):
        pytest.fail("Passive status started Git")

    monkeypatch.setattr(GitSession, "run", forbidden)
    root = tmp_path / "Fresh GitLab" / "Instance"
    assert main(["mirror-gitlab-status", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["profile"] == PROFILE


def test_local_csrf_ui_uses_gitlab_backend_and_passive_get_has_no_transport(tmp_path, monkeypatch):
    import re

    from fastapi.testclient import TestClient

    from provelume.mirror_contract import fingerprint
    from provelume.web import create_app

    instance, mirrors, engine, row, api = synthetic_fixture(tmp_path)
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    app.state.provelume._mirrors_manager = mirrors
    monkeypatch.setattr(app.state.provelume, "gitlab_mirrors", lambda: engine)
    client = TestClient(app)
    page = client.get("/mirrors?lang=it")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    assert client.post("/mirrors", data={"action": "gitlab-prepare"}).status_code == 403
    result = client.post(
        "/mirrors?lang=it",
        data={
            "csrf_token": csrf,
            "action": "gitlab-prepare",
            "destination_id": row["id"],
            "revision": "1",
            "confirm": "yes",
        },
    )
    assert result.status_code == 200 and 'id="mirror-gitlab-transfer"' in result.text
    plan, git_plan = engine.git_plan(mirrors.plans()[0]["id"])
    result = client.post(
        "/mirrors?lang=it",
        data={
            "csrf_token": csrf,
            "action": "gitlab-publish",
            "plan_id": plan["id"],
            "plan_sha256": fingerprint(plan),
            "git_plan_sha256": fingerprint(git_plan),
            "transfer_sha256": git_plan["transfer_sha256"],
            "public_confirm": "no",
            "confirm": "yes",
        },
    )
    assert result.status_code == 200 and 'id="mirror-git-receipt"' in result.text
    count, reads = len(api.calls), mirrors.vault.reads
    with patch.object(GitSession, "run", side_effect=AssertionError("passive process")):
        for language in ["en", "it", "de", "fr", "es", "pt", "ro"]:
            assert (
                client.get("/mirrors?lang=" + language + "&plan=" + plan["id"]).status_code == 200
            )
    assert len(api.calls) == count and mirrors.vault.reads == reads
