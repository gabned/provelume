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
    assets = [*package.glob("templates/*.html"), *package.glob("static/*")]
    text = "\n".join(path.read_text(encoding="utf-8") for path in assets).casefold()
    assert 'href="http' not in text
    assert 'src="http' not in text
