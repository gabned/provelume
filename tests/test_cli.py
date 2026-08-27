from __future__ import annotations

import json
from pathlib import Path

from provelume.cli import main
from provelume.service import ProvelumeInstance


def test_cli_build_info_needs_no_instance(capsys) -> None:
    assert main(["build-info"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["identity_status"] == "development_build"
    assert payload["source_repository"] == "gabned/provelume"
    assert payload["verification"]["status"] == "not_performed"
    assert payload["verification"]["network_used"] is False


def test_cli_about_needs_no_instance_or_network(capsys) -> None:
    assert main(["about"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["product"] == "Provelume"
    assert payload["version"] == "0.4.1"
    assert payload["updates"]["network_required_for_check"] is True
    assert payload["updates"]["check_on_start_default"] is False


def test_cli_update_check_is_explicit_and_reports_transport(monkeypatch, capsys) -> None:
    observed = []

    def check_stub(**kwargs):
        observed.append(kwargs)
        return {
            "schema_version": 1,
            "status": "up_to_date",
            "network_used": True,
            "instance_content_sent": False,
        }

    monkeypatch.setattr("provelume.cli.check_for_updates", check_stub)
    assert main(["check-updates", "--channel", "preview"]) == 0
    assert observed == [{"current_version": "0.4.1", "channel": "preview"}]
    assert json.loads(capsys.readouterr().out)["network_used"] is True


def test_cli_init_ingest_health_and_rebuild(tmp_path: Path, capsys) -> None:
    instance_root = tmp_path / "instance"
    source = tmp_path / "source"
    source.mkdir()
    (source / "hello.txt").write_text("Hello portable knowledge.\n", encoding="utf-8")

    assert main(["init", str(instance_root), "--name", "CLI Demo"]) == 0
    capsys.readouterr()
    assert main(["ingest", str(instance_root), str(source)]) == 0
    ingest_output = capsys.readouterr().out
    assert '"outcome": "created"' in ingest_output

    assert main(["health", str(instance_root)]) == 0
    assert '"index_status": "ready"' in capsys.readouterr().out

    (instance_root / "indexes" / "search.sqlite3").unlink()
    assert main(["rebuild-index", str(instance_root)]) == 0
    assert '"documents_indexed": 1' in capsys.readouterr().out

    restarted = ProvelumeInstance(instance_root)
    assert restarted.search("portable")[0]["title"] == "hello.txt"


def test_cli_serve_configures_release_evidence_at_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    instance_root = tmp_path / "instance"
    release_bundle = tmp_path / "release-bundle"
    app = object()
    created: list[tuple[Path, dict[str, object]]] = []
    served: list[tuple[object, dict[str, object]]] = []

    def create_app_stub(instance: Path, **kwargs):
        created.append((instance, kwargs))
        return app

    def run_stub(selected_app, **kwargs):
        served.append((selected_app, kwargs))

    monkeypatch.setattr("provelume.cli.create_app", create_app_stub)
    monkeypatch.setattr("provelume.cli.uvicorn.run", run_stub)

    assert (
        main(
            [
                "serve",
                str(instance_root),
                "--host",
                "0.0.0.0",
                "--port",
                "8042",
                "--release-bundle",
                str(release_bundle),
                "--expected-manifest-sha256",
                "a" * 64,
            ]
        )
        == 0
    )
    assert created == [
        (
            instance_root,
            {
                "release_bundle": release_bundle,
                "expected_manifest_sha256": "a" * 64,
            },
        )
    ]
    assert served == [(app, {"host": "0.0.0.0", "port": 8042})]
