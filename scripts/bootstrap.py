from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    environment = root / ".venv"
    if not environment.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    python = (
        environment / "Scripts" / "python.exe"
        if os.name == "nt"
        else environment / "bin" / "python"
    )
    subprocess.check_call(
        [str(python), "-m", "pip", "install", "-e", ".[dev]"],
        cwd=root,
    )
    launcher = (
        environment / "Scripts" / "provelume.exe"
        if os.name == "nt"
        else environment / "bin" / "provelume"
    )
    print(f"Provelume development environment is ready: {launcher}")
    print("Next: provelume init <instance-directory>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
