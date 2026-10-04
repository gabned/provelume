"""Reproduce S06 synthetic scenarios, including real processes and crash injection.

No real provider, credential, model or network is used. Native candidate execution
is measured separately by qualify_ai_runtime.py under the external CI observer.
"""

import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    print(
        "S06 synthetic demonstration: explicit jobs and atomic reservations; real process "
        "contention; current policy revocation; cancellation; crash/restart and one result; "
        "ambiguous transport without replay; ordered allowed/denied fallback; restore and "
        "AI-off deterministic operation. Native Windows/Linux execution is a separate gate.",
        flush=True,
    )
    (root / ".agent").mkdir(exist_ok=True)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-v",
            "tests/test_ai_jobs.py",
            "tests/test_ai_jobs_controls.py",
            "tests/test_ai_jobs_boundaries.py",
            "tests/test_ai_llama_prefix.py",
            "--junitxml=.agent/s06-synthetic-demo.xml",
        ],
        cwd=root,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
