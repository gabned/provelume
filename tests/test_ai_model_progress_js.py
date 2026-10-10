"""Execute the shipped observer against delayed/status/lifecycle browser events."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_model_progress_browser_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "tests/fixtures/ai_model_progress.cjs"),
         str(root / "core/provelume/static/ai-model-progress.js")],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "contracts passed" in result.stdout
