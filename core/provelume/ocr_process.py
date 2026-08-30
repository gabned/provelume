from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .ocr_contract import OcrContractError


@dataclass(frozen=True, slots=True)
class BoundedProcessResult:
    command: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    duration_ms: int


def minimal_child_environment(
    temporary_directory: Path,
    *,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a small, content-free environment for local OCR child processes."""

    root = str(Path(temporary_directory).resolve())
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": root,
        "TMP": root,
        "TEMP": root,
    }
    if os.name == "nt":
        for key in ("SystemRoot", "WINDIR"):
            value = os.environ.get(key)
            if value:
                environment[key] = value
    for key, value in (extra or {}).items():
        if (
            not isinstance(key, str)
            or not key
            or "\x00" in key
            or "=" in key
            or not isinstance(value, str)
            or "\x00" in value
        ):
            raise OcrContractError(
                "ocr_contract_violation",
                "OCR child environment contains an invalid field",
            )
        environment[key] = value
    return environment


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
        try:
            process.wait(timeout=0.5)
            return
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
    elif os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
        taskkill = (
            Path(system_root) / "System32" / "taskkill.exe"
            if system_root
            else None
        )
        if taskkill is not None and taskkill.is_file():
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=2,
            )
        if process.poll() is None:
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def run_bounded_process(
    command: Sequence[str],
    *,
    temporary_directory: Path,
    timeout_seconds: int,
    stdout_limit: int,
    stderr_limit: int,
    cancelled: Callable[[], bool] | None = None,
    environment: Mapping[str, str] | None = None,
    produced_file_limits: Mapping[Path, int] | None = None,
) -> BoundedProcessResult:
    """Run an allowlisted command without a shell and bound every captured byte."""

    selected = tuple(command)
    if (
        not selected
        or any(not isinstance(item, str) or not item or "\x00" in item for item in selected)
        or type(timeout_seconds) is not int
        or timeout_seconds < 1
        or type(stdout_limit) is not int
        or stdout_limit < 1
        or type(stderr_limit) is not int
        or stderr_limit < 1
    ):
        raise OcrContractError(
            "ocr_contract_violation", "OCR process request is invalid"
        )
    working = Path(temporary_directory)
    if working.is_symlink() or not working.is_dir():
        raise OcrContractError(
            "ocr_contract_violation", "OCR process directory is not private"
        )
    selected_file_limits: dict[Path, int] = {}
    for path, limit in (produced_file_limits or {}).items():
        selected_path = Path(path).resolve()
        try:
            selected_path.relative_to(working.resolve())
        except ValueError as exc:
            raise OcrContractError(
                "ocr_contract_violation",
                "OCR produced-file limit is outside the private process directory",
            ) from exc
        if type(limit) is not int or limit < 1:
            raise OcrContractError(
                "ocr_contract_violation", "OCR produced-file limit is invalid"
            )
        selected_file_limits[selected_path] = limit
    token = uuid4().hex
    stdout_path = working / f".process-{token}.stdout"
    stderr_path = working / f".process-{token}.stderr"
    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    try:
        with stdout_path.open("xb") as stdout_handle, stderr_path.open(
            "xb"
        ) as stderr_handle:
            options: dict[str, object] = {
                "args": list(selected),
                "cwd": working,
                "env": dict(environment or minimal_child_environment(working)),
                "stdin": subprocess.DEVNULL,
                "stdout": stdout_handle,
                "stderr": stderr_handle,
                "shell": False,
                "close_fds": True,
            }
            if os.name == "posix":
                options["start_new_session"] = True
            elif os.name == "nt":
                options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                process = subprocess.Popen(**options)  # type: ignore[arg-type]
            except OSError as exc:
                raise OcrContractError(
                    "ocr_engine_unavailable",
                    "The configured local OCR executable could not be started",
                ) from exc
            while process.poll() is None:
                if cancelled is not None and cancelled():
                    _terminate_process_tree(process)
                    raise OcrContractError(
                        "ocr_cancelled", "OCR execution was cancelled"
                    )
                if time.monotonic() - started > timeout_seconds:
                    _terminate_process_tree(process)
                    raise OcrContractError(
                        "ocr_deadline_exceeded", "OCR process exceeded its deadline"
                    )
                stdout_handle.flush()
                stderr_handle.flush()
                if stdout_path.stat().st_size > stdout_limit:
                    _terminate_process_tree(process)
                    raise OcrContractError(
                        "ocr_output_limit_exceeded",
                        "OCR process stdout exceeded its configured limit",
                    )
                if stderr_path.stat().st_size > stderr_limit:
                    _terminate_process_tree(process)
                    raise OcrContractError(
                        "ocr_output_limit_exceeded",
                        "OCR process stderr exceeded its configured limit",
                    )
                if any(
                    path.is_file() and path.stat().st_size > limit
                    for path, limit in selected_file_limits.items()
                ):
                    _terminate_process_tree(process)
                    raise OcrContractError(
                        "ocr_output_limit_exceeded",
                        "OCR process produced file exceeded its configured limit",
                    )
                time.sleep(0.02)
        if process is None:
            raise OcrContractError("ocr_internal_error", "OCR process did not start")
        if stdout_path.stat().st_size > stdout_limit or stderr_path.stat().st_size > stderr_limit:
            raise OcrContractError(
                "ocr_output_limit_exceeded", "OCR process output exceeded its limit"
            )
        if any(
            path.is_file() and path.stat().st_size > limit
            for path, limit in selected_file_limits.items()
        ):
            raise OcrContractError(
                "ocr_output_limit_exceeded",
                "OCR process produced file exceeded its configured limit",
            )
        return BoundedProcessResult(
            command=selected,
            returncode=int(process.returncode),
            stdout=stdout_path.read_bytes(),
            stderr=stderr_path.read_bytes(),
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        )
    finally:
        if process is not None and process.poll() is None:
            _terminate_process_tree(process)
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)


__all__ = [
    "BoundedProcessResult",
    "minimal_child_environment",
    "run_bounded_process",
]
