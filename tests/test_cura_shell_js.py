from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_browser_enhancement_navigation_focus_and_live_publication_expiry() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for the browser enhancement contract")
    repository = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(repository / "tests/fixtures/cura_shell_contract.cjs"),
         str(repository / "core/provelume/static/cura-shell.js")],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "publication expiry contracts passed" in result.stdout
