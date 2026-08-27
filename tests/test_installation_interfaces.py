from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from provelume import cli
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _result(status: str = "package_integrity_verified") -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": status,
        "package": {
            "distribution": "provelume",
            "version": "0.1.0",
            "editable": False,
        },
        "integrity": {
            "verified": status == "package_integrity_verified",
            "checked_files": 12,
            "tracked_files": 12,
            "unhashed_files": 0,
            "unexpected_files": 0,
        },
        "origin": {
            "status": "not_established",
            "detail": "Synthetic origin boundary.",
        },
        "network_used": False,
        "reason": "Synthetic verification result.",
        "findings": [],
        "findings_truncated": False,
    }


def test_read_only_installation_security_api_and_browser(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "instance"
    ProvelumeInstance.initialise(root, name="Security Demo")
    result = _result()
    monkeypatch.setattr("provelume.api.verify_current_installation", lambda: result)
    monkeypatch.setattr("provelume.web.verify_current_installation", lambda: result)

    client = TestClient(create_app(root))
    response = client.get("/api/v1/security/installation")
    assert response.status_code == 200
    assert response.json() == result
    assert client.post("/api/v1/security/installation", json={}).status_code == 405

    english = client.get("/security/installation")
    assert english.status_code == 200
    assert "Verify installation" in english.text
    assert "Package integrity verified" in english.text
    assert "Not established by local package metadata" in english.text
    assert 'href="/security/installation?lang=en">Verify installation</a>' in english.text
    assert 'href="/security?lang=en">Security</a>' in english.text
    assert "Synthetic verification result." not in english.text

    italian = client.get("/security/installation", params={"lang": "it"})
    assert italian.status_code == 200
    assert "Verifica installazione" in italian.text
    assert "Integrità del pacchetto verificata" in italian.text
    assert "Tutti i file del pacchetto con hash corrispondono" in italian.text
    assert "Synthetic verification result." not in italian.text
    assert 'href="http' not in italian.text.lower()
    assert 'src="http' not in italian.text.lower()

    result["status"] = "modified_installation"
    result["integrity"]["verified"] = False
    result["reason"] = "Raw English reason."
    result["findings"] = [
        {
            "path": "provelume/module.py",
            "issue": "modified_file",
            "detail": "Raw English finding detail.",
            "expected_sha256": "expected",
            "actual_sha256": "actual",
        }
    ]
    italian_modified = client.get("/security/installation", params={"lang": "it"})
    assert italian_modified.status_code == 200
    assert "I file del pacchetto installato differiscono" in italian_modified.text
    assert "Il file installato differisce dal RECORD" in italian_modified.text
    assert "Raw English reason." not in italian_modified.text
    assert "Raw English finding detail." not in italian_modified.text

    result["status"] = "verification_unavailable"
    result["findings"] = []
    italian_unavailable = client.get(
        "/security/installation",
        params={"lang": "it"},
    )
    assert italian_unavailable.status_code == 200
    assert "Non è disponibile un elenco completo dei problemi" in italian_unavailable.text
    assert "Non sono stati rilevati problemi" not in italian_unavailable.text

    italian_security = client.get("/security", params={"lang": "it"})
    assert italian_security.status_code == 200
    assert 'href="/security/installation?lang=it">Verifica installazione</a>' in (
        italian_security.text
    )
    assert "Controlla localmente i file installati senza usare la rete" in (
        italian_security.text
    )


def test_installation_page_does_not_read_instance_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "instance"
    ProvelumeInstance.initialise(root, name="Security Isolation")
    app = create_app(root)
    instance = app.state.provelume

    def forbidden_instance_read(*_args, **_kwargs):
        raise AssertionError("installation page must not read Instance context")

    monkeypatch.setattr(instance.store, "read_config", forbidden_instance_read)
    monkeypatch.setattr(instance, "instance_summary", forbidden_instance_read)
    monkeypatch.setattr(instance, "knowledge_health", forbidden_instance_read)
    monkeypatch.setattr(
        "provelume.web.verify_current_installation",
        lambda **_kwargs: _result(),
    )

    response = TestClient(app).get(
        "/security/installation",
        params={
            "lang": "it",
            "release_bundle": str(tmp_path / "release"),
            "expected_manifest_sha256": "a" * 64,
        },
    )

    assert response.status_code == 200
    assert "Verifica installazione" in response.text


def test_verify_installation_cli_uses_shared_contract(
    monkeypatch,
    capsys,
) -> None:
    result = _result()
    monkeypatch.setattr("provelume.cli.verify_current_installation", lambda: result)
    assert cli.main(["verify-installation"]) == 0
    assert json.loads(capsys.readouterr().out) == result


def test_verify_installation_cli_has_distinct_failure_codes(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "provelume.cli.verify_current_installation",
        lambda: _result("modified_installation"),
    )
    assert cli.main(["verify-installation"]) == 2
    capsys.readouterr()

    monkeypatch.setattr(
        "provelume.cli.verify_current_installation",
        lambda: _result("verification_unavailable"),
    )
    assert cli.main(["verify-installation"]) == 3


def test_installation_interfaces_forward_explicit_release_evidence(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "instance"
    bundle = tmp_path / "release-bundle"
    ProvelumeInstance.initialise(root, name="Anchored Security Demo")
    result = _result()
    result["release_linkage"] = {
        "status": "verified",
        "verified": True,
        "bundle": {
            "verification": "externally_anchored_bundle_verified",
            "version": "0.1.0",
            "tag": "v0.1.0",
            "source_commit": "a" * 40,
            "release_manifest_sha256": "b" * 64,
            "externally_anchored": True,
        },
        "wheel": {
            "name": "provelume-0.1.0-py3-none-any.whl",
            "sha256": "c" * 64,
            "size_bytes": 123,
            "checked_members": 20,
            "package_files": 12,
        },
        "checked_files": 12,
        "unexpected_files": 0,
        "reason": "Synthetic linked result.",
    }
    result["origin"] = {
        "status": "trusted_manifest_sha256_matched",
        "detail": "Synthetic anchored boundary.",
    }
    calls: list[dict[str, object]] = []

    def verify_stub(**kwargs):
        calls.append(kwargs)
        return result

    monkeypatch.setattr("provelume.api.verify_current_installation", verify_stub)
    monkeypatch.setattr("provelume.web.verify_current_installation", verify_stub)
    monkeypatch.setattr("provelume.cli.verify_current_installation", verify_stub)
    client = TestClient(create_app(root))
    query = {
        "release_bundle": str(bundle),
        "expected_manifest_sha256": "b" * 64,
    }

    api_response = client.get("/api/v1/security/installation", params=query)
    assert api_response.status_code == 200
    assert api_response.json() == result

    italian = client.get(
        "/security/installation",
        params={"lang": "it", **query},
    )
    assert italian.status_code == 200
    assert "I file installati corrispondono al wheel di release" in italian.text
    assert "Corrisponde allo SHA-256 del manifest fornito" in italian.text
    assert str(bundle) in italian.text
    assert "Synthetic linked result." not in italian.text

    assert (
        cli.main(
            [
                "verify-installation",
                "--release-bundle",
                str(bundle),
                "--expected-manifest-sha256",
                "b" * 64,
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == result
    assert calls == [query, query, {"release_bundle": bundle, "expected_manifest_sha256": "b" * 64}]
