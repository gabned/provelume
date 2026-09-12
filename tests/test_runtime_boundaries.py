from __future__ import annotations

import tomllib
from pathlib import Path


def test_runtime_dependencies_do_not_require_external_ai_or_github() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = "\n".join(project["project"]["dependencies"]).casefold()
    for forbidden in ("github", "openai", "anthropic", "gemini", "google-generativeai"):
        assert forbidden not in dependencies


def test_browser_assets_are_local() -> None:
    package = Path("core/provelume")
    assets = [*package.glob("templates/*.html"), *package.glob("static/**/*")]
    assets = [path for path in assets if path.is_file()]
    assert all(
        path.suffix in {".html", ".css", ".js", ".svg", ".json", ".png", ".ico"} for path in assets
    )
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in assets if path.suffix not in {".png", ".ico"}
    ).casefold()
    assert 'href="http' not in text
    assert 'src="http' not in text
