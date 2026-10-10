from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("explicit_navigation", [False, True])
def test_browser_enhancement_navigation_focus_and_live_publication_expiry(
    explicit_navigation,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for the browser enhancement contract")
    repository = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(repository / "tests/fixtures/cura_shell_contract.cjs"),
         str(repository / "core/provelume/static/cura-shell.js"),
         *([str(repository / "core/provelume/static/navigation.js")]
           if explicit_navigation else [])],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "publication expiry contracts passed" in result.stdout


def test_preference_dialog_cancel_and_keyboard_focus_wrap():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable for the preference dialog contract")
    repository = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(repository / "tests/fixtures/cura_preferences_dialog.cjs"),
         str(repository / "core/provelume/static/cura-shell.js")],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Preference dialog keyboard contracts passed" in result.stdout
