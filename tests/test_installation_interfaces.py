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
        lambda: _result(),
    )

    response = TestClient(app).get("/security/installation", params={"lang": "it"})

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
