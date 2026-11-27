"""A failed Docker client create is not proof that no owned container exists."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from provelume import mirror_rsync_qualification as qualification
from provelume.mirror_contract import MirrorError


@pytest.mark.parametrize("state", ["created", "running"])
def test_cleanup_reconciles_owned_container_even_after_client_timeout(tmp_path, monkeypatch, state):
    calls = []

    def docker(*args, **_options):
        calls.append(args)
        if "inspect" in args:
            value = {"Labels": {"org.provelume.qualification.owner": "ours"}}
            if args[0] == "inspect":
                value = {"Config": value, "State": {"Status": state}}
            return SimpleNamespace(returncode=0, stdout=json.dumps([value]).encode())
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(qualification, "docker", docker)
    qualification.cleanup_fixture(tmp_path, "fresh-owned-name", "ours")
    assert ("rm", "--force", "fresh-owned-name") in calls
    assert ("network", "rm", "fresh-owned-name") in calls
    rows = json.loads((tmp_path / "cleanup-original.json").read_bytes())
    assert all(row["result"] == "OWNED_REMOVAL_CONFIRMED" for row in rows)
    assert rows[0]["observed_state"] == state


@pytest.mark.parametrize("failure", ["foreign", "not_observed", "timeout", "remove_failed"])
def test_cleanup_preserves_unknown_and_never_removes_foreign_resources(
    tmp_path, monkeypatch, failure
):
    calls = []

    def docker(*args, **_options):
        calls.append(args)
        if failure == "timeout":
            raise subprocess.TimeoutExpired("docker", 30)
        if "inspect" in args:
            if failure == "not_observed":
                return SimpleNamespace(returncode=1)
            labels = {"org.provelume.qualification.owner":
                      "foreign" if failure == "foreign" else "ours"}
            value = {"Labels": labels}
            if args[0] == "inspect":
                value = {"Config": value, "State": {"Status": "created"}}
            return SimpleNamespace(returncode=0, stdout=json.dumps([value]).encode())
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr(qualification, "docker", docker)
    with pytest.raises(MirrorError) as error:
        qualification.cleanup_fixture(tmp_path, "fresh-owned-name", "ours")
    assert error.value.code == "rsync_fixture_cleanup_unconfirmed"
    rows = json.loads((tmp_path / "cleanup-original.json").read_bytes())
    assert all(row["result"] != "OWNED_REMOVAL_CONFIRMED" for row in rows)
    if failure != "remove_failed":
        assert all("rm" not in call for call in calls)
