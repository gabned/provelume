"""Reproduce S07 HTTP controls and S06 process/recovery boundaries with public fixtures."""

import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    print(
        "S07 synthetic demonstration; no live external provider, credential or model.", flush=True
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-v",
            "tests/test_ai_setup.py",
            "tests/test_ai_jobs.py",
            "tests/test_ai_jobs_controls.py",
            "tests/test_ai_jobs_boundaries.py",
            "--junitxml=.agent/s07-synthetic-demo.xml",
            *sys.argv[1:],
        ],
        cwd=root,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
