from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _fixture(tmp_path: Path) -> tuple[Path, Path, ProvelumeInstance]:
    source = tmp_path / "source"
    (source / "Projects").mkdir(parents=True)
    (source / "Projects" / "alpha.md").write_text(
        "# Alpha\n\nProvenance makes durable knowledge traceable.\n",
        encoding="utf-8",
    )
    (source / "notes.txt").write_text(
        "Portable knowledge can outlive a search index.\n",
        encoding="utf-8",
    )
    root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(root, name="Public Demo")
    instance.ingest(source, source_name="Synthetic files")
    return root, source, instance


def test_read_only_api_contract(tmp_path: Path) -> None:
    root, _source, instance = _fixture(tmp_path)
    client = TestClient(create_app(root))

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert health.json()["build_identity_status"] == "development_build"
    assert health.json()["official_build_metadata"] is False

    build = client.get("/api/v1/build-info")
    assert build.status_code == 200
    assert build.json()["identity_status"] == "development_build"
    assert build.json()["source_repository"] == "gabned/provelume"
    assert build.json()["verification"]["status"] == "not_performed"
    assert build.json()["verification"]["network_used"] is False

    summary = client.get("/api/v1/instance")
    assert summary.status_code == 200
    assert summary.json()["documents"] == 2
    assert summary.json()["network"] == {
        "external_access": False,
        "update_checks": False,
        "configured_external_providers": 0,
    }

    sources = client.get("/api/v1/sources").json()
    assert len(sources) == 1
    source_id = sources[0]["id"]
    assert client.get(f"/api/v1/sources/{source_id}").status_code == 200

    documents = client.get("/api/v1/documents").json()
    assert len(documents) == 2
    project_documents = client.get("/api/v1/documents", params={"area": "Projects"}).json()
    assert [item["title"] for item in project_documents] == ["alpha.md"]

    document = next(item for item in documents if item["title"] == "alpha.md")
    other_document = next(item for item in documents if item["title"] == "notes.txt")
    document_id = document["id"]
    assert client.get(f"/api/v1/documents/{document_id}").status_code == 200
    versions = client.get(f"/api/v1/documents/{document_id}/versions").json()
    assert len(versions) == 1
    provenance = client.get(f"/api/v1/documents/{document_id}/provenance").json()
    assert provenance["document"]["id"] == document_id
    assert any(edge["relation"] == "captured" for edge in provenance["edges"])
    unrelated_ids = {
        other_document["id"],
        other_document["current_version"]["id"],
    }
    assert all(
        edge["from_id"] not in unrelated_ids and edge["to_id"] not in unrelated_ids
        for edge in provenance["edges"]
    )

    original = client.get(f"/api/v1/documents/{document_id}/original")
    assert original.status_code == 200
    assert b"Provenance makes durable knowledge traceable" in original.content

    search = client.get("/api/v1/search", params={"q": "durable knowledge"})
    assert search.status_code == 200
    assert search.json()["results"][0]["document_id"] == document_id

    malformed = client.get("/api/v1/search", params={"q": '" OR * NOT ('})
    assert malformed.status_code == 200
    assert isinstance(malformed.json()["results"], list)

    today = datetime.now(UTC).date().isoformat()
    inclusive = client.get(
        "/api/v1/documents",
        params={"date_from": today, "date_to": today},
    )
    assert len(inclusive.json()) == 2

    assert client.get("/api/v1/knowledge-health").status_code == 200
    assert client.post("/api/v1/build-info", json={}).status_code == 405
    assert client.post("/api/v1/documents", json={}).status_code == 405
    assert instance.store.read_config()["network"]["external_access"] is False


def test_browser_routes_and_italian_catalog(tmp_path: Path) -> None:
    root, _source, instance = _fixture(tmp_path)
    client = TestClient(create_app(root))
    document_id = instance.list_documents()[0]["id"]

    home = client.get("/")
    assert home.status_code == 200
    assert "Instance overview" in home.text
    assert "/security?lang=en" in home.text
    assert 'href="http' not in home.text.lower()
    assert 'src="http' not in home.text.lower()

    italian = client.get("/", params={"lang": "it"})
    assert italian.status_code == 200
    assert (
        "Panoramica dell&#39;istanza" in italian.text
        or "Panoramica dell'istanza" in italian.text
    )

    browse = client.get("/browse", params={"area": "Projects"})
    assert browse.status_code == 200
    assert "alpha.md" in browse.text
    assert "notes.txt" not in browse.text

    browse_all = client.get("/browse", params={"area": ""})
    assert browse_all.status_code == 200
    assert "alpha.md" in browse_all.text
    assert "notes.txt" in browse_all.text

    browse_root = client.get("/browse", params={"area": "__root__"})
    assert browse_root.status_code == 200
    assert "notes.txt" in browse_root.text
    assert "alpha.md" not in browse_root.text

    search = client.get("/search", params={"q": "traceable"})
    assert search.status_code == 200
    assert "alpha.md" in search.text

    document = client.get(f"/documents/{document_id}")
    assert document.status_code == 200
    assert "Extracted text preview" in document.text

    provenance = client.get(f"/documents/{document_id}/provenance")
    assert provenance.status_code == 200
    assert "Source" in provenance.text
    assert "Acquisition" in provenance.text

    health = client.get("/knowledge-health")
    assert health.status_code == 200
    assert "Derived search state can be rebuilt" in health.text

    security = client.get("/security")
    assert security.status_code == 200
    assert "Security &amp; build identity" in security.text
    assert "Development build" in security.text
    assert "does not by itself verify installed files" in security.text
    assert "No network request performed" in security.text
    assert 'href="http' not in security.text.lower()
    assert 'src="http' not in security.text.lower()

    security_it = client.get("/security", params={"lang": "it"})
    assert security_it.status_code == 200
    assert "Sicurezza e identità della build" in security_it.text
    assert "Build di sviluppo" in security_it.text
    assert "Nessuna richiesta di rete eseguita" in security_it.text


def test_browser_and_api_survive_restart(tmp_path: Path) -> None:
    root, _source, instance = _fixture(tmp_path)
    expected_ids = {item["id"] for item in instance.list_documents()}
    restarted = ProvelumeInstance(root)
    assert {item["id"] for item in restarted.list_documents()} == expected_ids
    client = TestClient(create_app(root))
    assert {item["id"] for item in client.get("/api/v1/documents").json()} == expected_ids
    assert client.get("/api/v1/build-info").json()["verification"]["network_used"] is False
