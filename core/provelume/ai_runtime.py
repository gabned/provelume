"""S05 internal runtime qualification, never a product dispatcher.

One worker and no queue. S06 must supply job/budget authority before a product
adapter can call this boundary. Public service execution remains fail-closed.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import queue
import subprocess
import sys
import sysconfig
import threading
import time
from pathlib import Path

from .ai_model_download import checkpoint
from .ai_model_file import VerifiedModelFile
from .ai_models import ModelError, RuntimeSelection, check
from .ai_runtime_contract import (
    CONFIGURATION,
    MODEL_FORMAT,
    MODEL_ID,
    RUNTIME_ID,
    RUNTIME_VERSION,
    hardware,
    runtime_lock,
)
from .maintenance_local_files import open_local_file
from .ocr_process import minimal_child_environment
from .representations import canonical_json_bytes

# Process-wide ceiling also covers different instances/managers. It is not a job
# queue or budget engine. OS containment prevents worker-created descendants.
_SLOT = threading.BoundedSemaphore(1)


def native_selection():
    return RuntimeSelection(
        RUNTIME_ID,
        RUNTIME_VERSION,
        MODEL_FORMAT,
        platform="windows" if os.name == "nt" else "linux",
        configuration=canonical_json_bytes(CONFIGURATION),
    )


class LocalRuntime:
    def __init__(self, runtime_directory: Path):
        # Pure construction; no probing, worker, acquisition or implicit self-test.
        self.directory = Path(runtime_directory)
        self._lock = threading.RLock()
        self._process = None
        self._reader = None
        self._writer = None
        self._timer = None
        self._slot = False
        self._model = None
        self._messages = queue.Queue(maxsize=8)
        self._load = None
        self.last_observation = None
        self.worker_history = []

    def validate_installation(self):
        """Revalidate native bytes at activation/use, including a warm worker."""
        inventory = runtime_lock()["platforms"][native_selection().platform]
        try:
            check({p.name for p in self.directory.iterdir()} == set(inventory), "integrity")
            for name, expected in inventory.items():
                with open_local_file(self.directory / name) as stream:
                    check(os.fstat(stream.fileno()).st_size == expected["size"] and
                          hashlib.file_digest(stream, "sha256").hexdigest() == expected["sha256"],
                          "integrity")
        except ModelError:
            raise
        except Exception:
            raise ModelError("integrity") from None

    @property
    def loaded(self):
        return self._process is not None and self._process.poll() is None

    def _drain(self, process, messages):
        try:
            while True:
                line = process.stdout.readline(32769)
                if not line:
                    return
                check(len(line) <= 32768 and line.endswith(b"\n"), "limit")
                value = json.loads(line)
                check(type(value) is dict, "state")
                messages.put_nowait(value)
        except Exception:
            process.kill()
        finally:
            with contextlib.suppress(queue.Full):
                messages.put_nowait({"event": "eof"})

    def _send(self, value, *, deadline, cancel):
        raw = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"
        check(len(raw) <= 32768, "limit")
        # A worker that stops reading must not trap the supervisor in a pipe
        # write (especially escaped Unicode/control input on Windows' small pipe).
        # One writer at a time, no queue; cancellation/deadline still owns cleanup.
        done, failed = threading.Event(), []
        process = self._process

        def write():
            try:
                check(process.stdin.write(raw) == len(raw), "state")
                process.stdin.flush()
            except Exception:
                failed.append(True)
            finally:
                done.set()

        checkpoint(cancel, deadline)
        self._writer = threading.Thread(target=write, daemon=True)
        self._writer.start()
        while not done.wait(0.02):
            checkpoint(cancel, deadline)
            check(self.loaded, "state")
        check(not failed, "state")
        self._writer.join()
        self._writer = None

    def _receive(self, event, *, deadline, cancel):
        while True:
            checkpoint(cancel, deadline)
            try:
                # Worker messages wake this wait immediately. During generation,
                # re-read authority at 10 Hz rather than contending with Capture
                # for metadata I/O at 50 Hz. Every poll still checks current
                # authority; cancellation/cleanup retains its two-second bound.
                value = self._messages.get(timeout=0.1)
            except queue.Empty:
                check(self.loaded, "state")
                continue
            if value.get("event") == "error":
                self.last_observation = {"failure": value.get("code", "state"),
                                         "phase": value.get("phase"),
                                         "failure_type": value.get("failure_type")}
                raise ModelError(value.get("code", "state"))
            if value.get("event") == "eof":
                self.last_observation = {"failure": "worker_exit",
                                         "returncode": self._process.poll()}
            check(value.get("event") in (event, "first"), "state")
            if value["event"] == "first":
                self._first_received = time.monotonic()
            if value["event"] == event:
                return value

    def _start(self, model, *, deadline, cancel):
        check(
            type(model.model) is VerifiedModelFile and model.entry.id == MODEL_ID, "compatibility"
        )
        hardware()
        check(_SLOT.acquire(blocking=False), "busy")
        self._slot = True
        try:
            check(self.directory.is_absolute(), "unsafe_path")
            env = minimal_child_environment(
                self.directory,
                extra={
                    "OMP_NUM_THREADS": "2",
                    "OMP_THREAD_LIMIT": "2",
                    "OPENBLAS_NUM_THREADS": "2",
                    # Without HOME, Python/site and dependencies can ask NSS for
                    # the account home before containment. This content-free path
                    # prevents implicit identity lookup; it is not network proof.
                    "HOME": str(self.directory),
                },
            )
            # Isolated Python omits user site/PYTHONPATH; only this installed Core
            # package is added, never a model/runtime directory to Python imports.
            root = str(Path(__file__).resolve().parent.parent)
            command = [
                getattr(sys, "_base_executable", sys.executable) if os.name == "nt"
                else sys.executable,
                "-I",
                "-c",
                "import sys;sys.path[:0]=sys.argv[1:3];"
                "from provelume.ai_runtime_limits import contain;limits=contain();"
                "from provelume.ai_runtime_worker import main;main(containment=limits)",
                root,
                sysconfig.get_path("purelib"),
            ]
            options = (
                {"creationflags": subprocess.CREATE_NO_WINDOW}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=root,
                bufsize=0,
                **options,
            )
            self.worker_history.append(self._process.pid)
            self._messages = queue.Queue(maxsize=8)
            self._reader = threading.Thread(
                target=self._drain, args=(self._process, self._messages), daemon=True
            )
            self._reader.start()
            self._send({"runtime": str(self.directory), "model": str(model.model.path)},
                       deadline=deadline, cancel=cancel)
            self._load = self._receive("loaded", deadline=deadline, cancel=cancel)
            check(self._load.get("pid") == self._process.pid, "state")
            self._model = model.entry.model_sha256
        except BaseException:
            self._stop()
            raise

    def _stop(self):
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        process = self._process
        try:
            if process is not None:
                if process.poll() is None:
                    if os.name == "posix":
                        import signal

                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()  # Job active-process limit forbids descendants.
                process.wait(timeout=2)
                if self._reader is not None and self._reader.ident is not None:
                    self._reader.join(timeout=0.25)
                if self._writer is not None and self._writer.ident is not None:
                    self._writer.join(timeout=0.25)
                process.stdin.close()
                process.stdout.close()
        finally:
            # If termination cannot be confirmed, keep both ownership and the slot.
            # A later explicit close may recover it; another worker must not start.
            if process is not None and process.poll() is None:
                raise ModelError("busy")
            self._process = None
            self._reader = self._writer = self._model = self._load = None
            if self._slot:
                self._slot = False
                _SLOT.release()

    def close(self):
        with self._lock:
            self._stop()

    def _idle(self, marker):
        with self._lock:
            if self._timer is marker:
                self._stop()

    def _infer(self, model, selection, prompt, *, cancel=lambda: False, reuse_scope=None):
        """Internal primitive for lifecycle qualification and governed S06 attempts."""
        check(self._lock.acquire(blocking=False), "busy")
        try:
            selection.validate(model.entry)
            check(selection.platform == native_selection().platform, "compatibility")
            check(type(prompt) is str and 0 < len(prompt.encode("utf-8")) <= 4096, "limit")
            check(not any(token in prompt for token in ("<|im_start|>", "<|im_end|>")), "limit")
            check(reuse_scope is None or (type(reuse_scope) is str and len(reuse_scope) == 64
                  and all(ch in "0123456789abcdef" for ch in reuse_scope)), "state")
            deadline = time.monotonic() + 60
            started = time.monotonic()
            self._first_received = None
            checkpoint(cancel, deadline)
            self.validate_installation()
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            cold = not self.loaded
            if cold:
                self._stop()
                self._start(model, deadline=deadline, cancel=cancel)
            check(self._model == model.entry.model_sha256, "stale")
            message = {"prompt": prompt}
            if reuse_scope is not None:
                message["scope"] = reuse_scope
            self._send(message, deadline=deadline, cancel=cancel)
            value = self._receive("result", deadline=deadline, cancel=cancel)
            check(
                type(value.get("text")) is str and len(value["text"].encode("utf-8")) <= 4096,
                "limit",
            )
            value.update(cold=cold, total_seconds=time.monotonic() - started, load=self._load)
            value["first_wall_seconds"] = (self._first_received - started
                                           if self._first_received is not None else None)
            self.last_observation = {k: v for k, v in value.items() if k != "text"}
            timer = threading.Timer(5, lambda: self._idle(timer))
            self._timer = timer
            self._timer.daemon = True
            self._timer.start()
            return value
        except ModelError:
            self._stop()
            raise
        except Exception:
            self._stop()
            raise ModelError("state") from None
        finally:
            self._lock.release()

    def __call__(self, model, selection, cancel):
        value = self._infer(
            model,
            selection,
            "Text: The synthetic code is ORCHID. Question: What is the code? "
            "Return only the code.",
            cancel=cancel,
        )
        return "PASSED" if value["text"].strip().strip(".").upper() == "ORCHID" else "FAILED"

    def qualify(self, store, prompt, *, requested=False, cancel=lambda: False):
        check(requested is True, "consent")
        selection = native_selection()
        started = time.monotonic()
        try:
            with store.use(selection) as model:
                admission = time.monotonic() - started
                result = self._infer(model, selection, prompt, cancel=cancel)
                result["total_seconds"] = time.monotonic() - started
                if result["first_wall_seconds"] is not None:
                    result["first_wall_seconds"] += admission
                return result
        except BaseException:
            self.close()
            raise

    def status(self):
        return {
            "runtime": RUNTIME_ID,
            "version": RUNTIME_VERSION,
            "loaded": self.loaded,
            "qualification": "CANDIDATE_NOT_QUALIFIED",
            "offline_qualified": False,
            "inference_authorized": False,
            "product_dispatch": "governed_job_required",
        }
