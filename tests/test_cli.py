from __future__ import annotations

from pathlib import Path

from provelume.cli import main
from provelume.service import ProvelumeInstance


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
