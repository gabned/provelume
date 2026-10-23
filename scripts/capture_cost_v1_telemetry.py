"""TEMP diagnostic recorder draft. Import uses stdlib only; install is explicit.

Not a qualifier. No model acquisition, benchmark, source mutation, threshold
change, implicit installation or automatic execution happens on import.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import datetime
import functools
import hashlib
import itertools
import json
import os
from pathlib import Path
import resource
import threading
import time
import types
import weakref


METHODS = ("_prepare", "commit", "_publish_entries")
EXPECTED_ORDINARY = {"ordinary_idle": 3, "ordinary_s05_busy": 3,
                     "ordinary_s06_busy": 6}
RUSAGE_FIELDS = ("ru_utime", "ru_stime", "ru_minflt", "ru_majflt",
                "ru_inblock", "ru_oublock", "ru_nvcsw", "ru_nivcsw")
CALIBRATION_PATTERNS = {
    "A": ("pool.create", "pool.submit", "pool.task", "atomic.payload_write_flush_fsync",
          "os.fsync", "pool.future_result_wait", "pool.shutdown_join", "pool.create",
          "atomic._publish_entries", "os.replace", "pool.submit", "pool.task",
          "atomic.directory_fsync", "os.fsync", "pool.future_result_wait", "pool.shutdown_join"),
    "B": ("atomic.payload_write_flush_fsync", "os.fsync", "atomic._publish_entries",
          "os.replace", "atomic.directory_fsync", "os.fsync"),
}


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _clock():
    usage = resource.getrusage(resource.RUSAGE_THREAD)
    return {"monotonic_ns": time.monotonic_ns(),
            "thread_cpu_ns": time.thread_time_ns(),
            "process_cpu_ns": time.process_time_ns(),
            "thread_usage": {key: getattr(usage, key) for key in RUSAGE_FIELDS}}


def _difference(before, after):
    return {"wall_ns": after["monotonic_ns"] - before["monotonic_ns"],
            "thread_cpu_ns": after["thread_cpu_ns"] - before["thread_cpu_ns"],
            "process_cpu_ns": after["process_cpu_ns"] - before["process_cpu_ns"],
            "thread_usage": {key: after["thread_usage"][key] - before["thread_usage"][key]
                             for key in RUSAGE_FIELDS}}


def _read_proc_file(path):
    try:
        # Proc telemetry is an allowlisted kernel projection, never argv/env/cwd.
        return path.read_text(encoding="ascii")
    except OSError as exc:
        return {"unavailable_errno": exc.errno}


def _proc_task(root):
    result = {}
    raw = _read_proc_file(root / "stat")
    if isinstance(raw, str):
        # comm can contain spaces or ')'; only the final delimiter owns fields.
        tail = raw[raw.rfind(")") + 2:].split()
        result["stat"] = {"state": tail[0], "minor_faults": int(tail[7]),
                          "major_faults": int(tail[9]), "user_ticks": int(tail[11]),
                          "system_ticks": int(tail[12]), "start_ticks": int(tail[19])}
    else:
        result["stat"] = raw
    raw = _read_proc_file(root / "schedstat")
    result["schedstat"] = ([int(x) for x in raw.split()] if isinstance(raw, str) else raw)
    for filename, allowed in (("status", {"voluntary_ctxt_switches", "nonvoluntary_ctxt_switches"}),
                              ("io", {"rchar", "wchar", "syscr", "syscw", "read_bytes",
                                      "write_bytes", "cancelled_write_bytes"})):
        raw = _read_proc_file(root / filename)
        result[filename] = ({key: int(value.strip()) for line in raw.splitlines()
                             if ":" in line for key, value in [line.split(":", 1)]
                             if key in allowed} if isinstance(raw, str) else raw)
    return result


class Recorder:
    """Bounded RAM recorder. Application values/exceptions pass through unchanged."""

    def __init__(self, *, identity, output, max_callbacks=64,
                 max_spans_per_callback=4096, max_spans_total=32768, max_threads=64):
        self.identity = dict(identity)
        self.output = Path(output)
        self.max_callbacks = max_callbacks
        self.max_spans_per_callback = max_spans_per_callback
        self.max_spans_total = max_spans_total
        self.max_threads = max_threads
        self.callbacks = []
        self.native_calls = []
        self.calibration = None
        self.errors = []
        self._ids = itertools.count(1)
        self._local = threading.local()
        self._active = None
        self._atomic_active = set()
        self._guard = threading.RLock()
        self._live_pools = {}
        self._live_tasks = set()
        self._pool_class = None
        self._runtimes = []
        self.runtime_histories = []
        self._restores = []
        self._span_total = 0
        self._s05_calls = 0
        self._s06_calls = 0
        self.section = "ordinary"
        self.section_context = {}
        self.arm = "checkout"
        self.method_identity = None
        self._variants = {}
        self._selected_methods = {}
        self._variant_owner = None
        self._variant_poisoned = False
        self._checkout_methods = {}
        self.schedules = {}
        self.schedule_ordinals = {}
        self.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.original_probe = None

    def error(self, code):
        if len(self.errors) < 128:
            try:
                clock = time.monotonic_ns()
            except Exception:
                clock = None
            self.errors.append({"code": code, "monotonic_ns": clock})

    def _safe_clock(self):
        try:
            return _clock()
        except Exception:
            self.error("clock_collection_failed")
            return None

    def _safe_difference(self, before, after):
        if before is None or after is None:
            return None
        try:
            return _difference(before, after)
        except Exception:
            self.error("clock_delta_failed")
            return None

    def _safe_runtime_observations(self):
        try:
            return self._runtime_observations()
        except Exception:
            self.error("runtime_observation_failed")
            return []

    def _safe_snapshot(self, observations):
        try:
            result = self._snapshot(observations)
            def unavailable(value):
                if isinstance(value, dict):
                    return "unavailable_errno" in value or any(unavailable(v) for v in value.values())
                if isinstance(value, list):
                    return any(unavailable(v) for v in value)
                return False
            if unavailable(result):
                self.error("proc_counter_unavailable")
            return result
        except Exception:
            self.error("proc_snapshot_failed")
            return {"status": "UNAVAILABLE"}

    def _patch(self, owner, name, value):
        original = vars(owner)[name]
        self._restores.append((owner, name, original, value))
        setattr(owner, name, value)

    def _runtime_observations(self):
        result = []
        for index, reference in enumerate(self._runtimes):
            runtime = reference()
            if runtime is None:
                continue
            process = getattr(runtime, "_process", None)
            prefill = getattr(runtime, "_prefill_observation", None)
            result.append({"runtime_id": self.runtime_histories[index]["id"],
                           "pid": getattr(process, "pid", None),
                           "request": getattr(runtime, "_request_id", None),
                           "phase_last_parent_observation": getattr(runtime, "_phase", None),
                           "first_received_last_parent_observation": getattr(runtime, "_first_received", None),
                           "prefill_last_parent_observation": dict(prefill) if prefill else None})
        return result

    def _snapshot(self, observations):
        started = time.monotonic_ns()
        pids = sorted({os.getpid()} | {row["pid"] for row in observations
                                      if type(row["pid"]) is int and row["pid"] > 0})
        result = {"monotonic_ns": started, "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"),
                  "processes": []}
        for pid in pids:
            root = Path("/proc") / str(pid)
            row = {"pid": pid, "process": _proc_task(root), "threads": []}
            try:
                tids = sorted(int(p.name) for p in (root / "task").iterdir())
            except OSError as exc:
                row["threads_unavailable_errno"] = exc.errno
                tids = []
            if len(tids) > self.max_threads:
                self.error("thread_inventory_limit")
                row["thread_inventory_truncated"] = True
            for tid in tids[:self.max_threads]:
                row["threads"].append({"tid": tid, "counters": _proc_task(root / "task" / str(tid))})
            result["processes"].append(row)
        result["observation_wall_ns"] = time.monotonic_ns() - started
        return result

    @contextmanager
    def span(self, label, *, callback=None, parent=None, extra=None):
        selected = callback if callback is not None else self._active
        if selected is None:
            yield
            return
        selected["span_event_attempts"] = selected.get("span_event_attempts", 0) + 1
        if (len(selected["spans"]) >= self.max_spans_per_callback
                or self._span_total >= self.max_spans_total):
            self.error("span_inventory_limit")
            yield
            return
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = self._local.stack = []
        token = next(self._ids)
        row = {"id": token, "label": label, "tid": threading.get_native_id(),
               "parent": parent if parent is not None else (stack[-1] if stack else None),
               "before": self._safe_clock(), "extra": extra or {}}
        selected["spans"].append(row)
        self._span_total += 1
        stack.append(token)
        try:
            yield
        except BaseException as exc:
            row["exception_type"] = type(exc).__name__
            raise
        finally:
            try:
                row["after"] = self._safe_clock()
                row["delta"] = self._safe_difference(row["before"], row["after"])
                if self._active is not selected:
                    self.error("span_completed_outside_callback")
            except Exception:
                self.error("span_finalization_failed")
            finally:
                if stack and stack[-1] == token:
                    stack.pop()
                else:
                    self.error("span_stack_mismatch")
                    stack.clear()

    def _wrap(self, owner, name, label, *, atomic=False, variant=False):
        original = getattr(owner, name)
        static = isinstance(vars(owner).get(name), staticmethod)
        if variant:
            self._selected_methods[name] = original
            self._checkout_methods[name] = original

        @functools.wraps(original)
        def wrapped(*args, **kwargs):
            token = next(self._ids) if atomic else None
            if atomic:
                with self._guard:
                    foreign = (self._variant_owner is not None
                               and self._variant_owner != threading.get_native_id())
                    if foreign:
                        # Never give an unrelated transaction the selected arm.
                        # Preserve its checkout implementation and poison this
                        # comparison rather than mutate its product behavior.
                        self.error("concurrent_unrelated_atomic_transaction_during_variant")
                        self._variant_poisoned = True
                    local_methods = getattr(self._local, "variant_methods", None)
                    implementation = ((local_methods or self._checkout_methods)[name]
                                      if variant else original)
                    self._atomic_active.add((threading.get_native_id(), token))
            else:
                implementation = original
            try:
                details = {}
                if label in ("atomic.payload_write_flush_fsync", "store.atomic_bytes"):
                    details["role"] = ("journal_payload" if label.startswith("atomic.")
                                       else "atomic_private_or_marker")
                    if label == "store.atomic_bytes" and args and isinstance(args[0], Path):
                        details["role"] = ("manifest_marker" if args[0].name == "manifest.json"
                                           else "other_atomic_private_bytes")
                    if len(args) >= 2 and isinstance(args[1], bytes):
                        details["bytes"] = len(args[1])
                elif label == "atomic.directory_fsync":
                    details["role"] = "directory"
                elif label == "atomic._publish_entries":
                    details["role"] = "publication"
                elif label == "os.fsync":
                    stack = getattr(self._local, "roles", [])
                    details["role"] = stack[-1] if stack else "other_required_file"
                elif label in ("os.replace", "os.rename"):
                    stack = getattr(self._local, "roles", [])
                    details["role"] = stack[-1] if stack else "other_required_replacement"
                roles = getattr(self._local, "roles", None)
                if roles is None:
                    roles = self._local.roles = []
                role = details.get("role") if label != "os.fsync" else None
                if role:
                    roles.append(role)
                with self.span(label, extra=details):
                    return implementation(*args, **kwargs)
            finally:
                if "role" in locals() and role:
                    roles.pop()
                if atomic:
                    with self._guard:
                        self._atomic_active.remove((threading.get_native_id(), token))

        self._patch(owner, name, staticmethod(wrapped) if static else wrapped)

    def add_variant(self, name, *, source, expected_sha256, atomic_module):
        """Compile only three independently reviewed methods; never execute a source module."""
        if name not in ("A", "B") or name in self._variants:
            raise ValueError("variant_identity")
        raw = Path(source).read_bytes()
        if _digest(raw) != expected_sha256:
            raise ValueError("variant_source_sha256")
        tree = ast.parse(raw, filename=str(source))
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "AtomicInstanceCommit"]
        if len(classes) != 1:
            raise ValueError("variant_class_inventory")
        selected = {}
        identities = {}
        for name_ in METHODS:
            nodes = [n for n in classes[0].body if isinstance(n, ast.FunctionDef) and n.name == name_]
            if len(nodes) != 1 or nodes[0].decorator_list:
                raise ValueError("variant_method_inventory")
            node = nodes[0]
            if (node.args.defaults or any(value is not None for value in node.args.kw_defaults)
                    or any(isinstance(part, ast.Name) and part.id == "__class__"
                           for part in ast.walk(node))
                    or any(isinstance(part, ast.Call) and isinstance(part.func, ast.Name)
                           and part.func.id == "super" and not part.args and not part.keywords
                           for part in ast.walk(node))):
                raise ValueError("variant_method_closure_or_default_expression")
            identities[name_] = _digest(ast.dump(node, include_attributes=False).encode())
            unit = ast.Module(body=[ast.ImportFrom(module="__future__",
                              names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
            ast.fix_missing_locations(unit)
            namespace = {}
            exec(compile(unit, str(source), "exec"), namespace)
            compiled = namespace[name_]
            if compiled.__code__.co_freevars or compiled.__closure__:
                raise ValueError("variant_method_closure")
            selected[name_] = types.FunctionType(compiled.__code__, atomic_module.__dict__,
                                                  compiled.__name__, compiled.__defaults__)
            selected[name_].__kwdefaults__ = compiled.__kwdefaults__
            selected[name_].__annotations__ = compiled.__annotations__
        self._variants[name] = {"methods": selected,
                                "identity": {"source_sha256": expected_sha256,
                                             "method_ast_sha256": identities}}

    @contextmanager
    def variant(self, name):
        with self._guard:
            if (self._variant_poisoned or self._active is not None or self._atomic_active
                    or self._live_pools or self._live_tasks):
                raise RuntimeError("variant_switch_with_inflight_or_poisoned_transaction")
            selected = self._variants[name]
            previous = (self.arm, self.method_identity,
                        getattr(self._local, "variant_methods", None), self._variant_owner)
            self.arm, self.method_identity = name, selected["identity"]
            self._local.variant_methods = dict(selected["methods"])
            self._variant_owner = threading.get_native_id()
        primary_error = False
        try:
            yield
        except BaseException:
            primary_error = True
            raise
        finally:
            drain_error = None
            try:
                self.drain_pools()
            except BaseException as exc:
                drain_error = exc
                self.error("variant_pool_drain_failed")
                self._variant_poisoned = True
            with self._guard:
                invalid = (self._active is not None or bool(self._atomic_active)
                           or bool(self._live_pools) or bool(self._live_tasks))
                if invalid:
                    self.error("variant_restore_with_inflight_atomic_transaction")
                    self._variant_poisoned = True
                self.arm, self.method_identity, local_previous, self._variant_owner = previous
                self._local.variant_methods = local_previous
            if drain_error is not None and not primary_error:
                raise drain_error
            if invalid and not primary_error:
                raise RuntimeError("variant_restore_with_inflight_atomic_transaction")

    def probe(self, group, number, instance, *, original=None):
        schedule = self.schedules.get(group)
        if schedule is not None:
            ordinal = self.schedule_ordinals.get(group, 0)
            self.schedule_ordinals[group] = ordinal + 1
            if ordinal >= len(schedule):
                self.error("treatment_schedule_exhausted")
                raise RuntimeError("treatment_schedule_exhausted")
            # The ordinal is consumed even when switching or callback fails.
            with self.variant(schedule[ordinal]):
                return self._probe(group, number, instance, original=original,
                                   treatment_ordinal=ordinal)
        return self._probe(group, number, instance, original=original)

    def _probe(self, group, number, instance, *, original=None, treatment_ordinal=None):
        if self._active is not None:
            raise RuntimeError("overlapping_capture_callback")
        implementation = original or self.original_probe
        if len(self.callbacks) >= self.max_callbacks:
            self.error("callback_inventory_limit")
            return implementation(instance, number)
        before_runtime = self._safe_runtime_observations()
        row = {"id": next(self._ids), "group": group, "number": number,
               "section_context": dict(self.section_context),
               "treatment_ordinal": treatment_ordinal,
               "arm": self.arm, "method_identity": self.method_identity,
               "runtime_before": before_runtime, "proc_before": self._safe_snapshot(before_runtime),
               "spans": [], "before": self._safe_clock()}
        self.callbacks.append(row)
        self._active = row
        try:
            result = implementation(instance, number)
            # Only the already-public scalar result is retained; no args, payload,
            # file paths, receipt bodies, document text or exception messages.
            row["probe"] = dict(result)
            return result
        except BaseException as exc:
            row["exception_type"] = type(exc).__name__
            raise
        finally:
            try:
                row["after"] = self._safe_clock()
                row["delta"] = self._safe_difference(row["before"], row["after"])
            except Exception:
                self.error("probe_finalization_failed")
            finally:
                self._active = None
            row["runtime_after"] = self._safe_runtime_observations()
            row["proc_after"] = self._safe_snapshot(row["runtime_after"])

    def install(self, *, qualification, jobs, report, atomic, capture, journal,
                runtime_class, instance_class, store_class):
        """Call in disposable credential-free process, after explicit module loading."""
        self.original_probe = report.deterministic_probe
        if qualification.deterministic_probe is not self.original_probe or jobs.deterministic_probe is not self.original_probe:
            raise ValueError("probe_alias_identity")
        original_init = runtime_class.__init__

        @functools.wraps(original_init)
        def runtime_init(runtime, *args, **kwargs):
            original_init(runtime, *args, **kwargs)
            self._runtimes.append(weakref.ref(runtime))
            self.runtime_histories.append({"id": next(self._ids),
                                           "worker_history": runtime.worker_history})

        self._patch(runtime_class, "__init__", runtime_init)
        original_infer = runtime_class._infer_admitted

        @functools.wraps(original_infer)
        def infer(runtime, model, selection, prompt, **kwargs):
            if len(self.native_calls) >= 512:
                self.error("native_call_inventory_limit")
                return original_infer(runtime, model, selection, prompt, **kwargs)
            try:
                raw = prompt.encode("utf-8")
                configuration_digest = _digest(selection.configuration)
            except Exception:
                self.error("native_input_identity_collection_failed")
                return original_infer(runtime, model, selection, prompt, **kwargs)
            row = {"id": next(self._ids), "section": self.section,
                   "section_context": dict(self.section_context),
                   "prompt_sha256": _digest(raw), "prompt_bytes": len(raw),
                   "configuration_sha256": configuration_digest,
                   "started_ns": time.monotonic_ns()}
            self.native_calls.append(row)
            try:
                result = original_infer(runtime, model, selection, prompt, **kwargs)
                try:
                    row.update(output_sha256=_digest(result["text"].encode("utf-8")),
                               input_tokens=result.get("input_tokens"),
                               output_tokens=result.get("output_tokens"))
                except Exception:
                    self.error("native_output_identity_collection_failed")
                return result
            except BaseException as exc:
                row["exception_type"] = type(exc).__name__
                raise
            finally:
                row["completed_ns"] = time.monotonic_ns()
                try:
                    row["request"] = getattr(runtime, "_request_id", None)
                    row["worker_pid"] = getattr(getattr(runtime, "_process", None), "pid", None)
                    observed = getattr(runtime, "last_observation", None)
                    row["worker_observation"] = dict(observed) if observed else None
                except Exception:
                    self.error("native_final_observation_failed")

        self._patch(runtime_class, "_infer_admitted", infer)
        for name in METHODS:
            self._wrap(atomic.AtomicInstanceCommit, name, "atomic." + name,
                       atomic=True, variant=True)
        for owner, name, label in ((atomic, "_write_journal_payload", "atomic.payload_write_flush_fsync"),
                                   (atomic, "_fsync_directory", "atomic.directory_fsync"),
                                   (capture.CaptureAdapter, "submit", "capture.submit"),
                                   (capture.CaptureAdapter, "process", "capture.process"),
                                   (capture.CaptureAdapter, "_acquire_locked", "capture.acquire_locked"),
                                   (journal.CaptureJournal, "_inventory", "capture.inventory"),
                                   (store_class, "_atomic_bytes", "store.atomic_bytes"),
                                   (os, "fsync", "os.fsync"),
                                   (os, "replace", "os.replace"),
                                   (os, "rename", "os.rename"),
                                   (instance_class, "search", "instance.search")):
            self._wrap(owner, name, label)
        original_pool = atomic.ThreadPoolExecutor
        self._pool_class = original_pool
        recorder = self

        class RecordingPool(original_pool):
            def __init__(pool, *args, **kwargs):
                pool._capture_cost_pool_id = next(recorder._ids)
                with recorder.span("pool.create", extra={"pool": pool._capture_cost_pool_id}):
                    super().__init__(*args, **kwargs)
                with recorder._guard:
                    recorder._live_pools[pool._capture_cost_pool_id] = pool

            def submit(pool, function, /, *args, **kwargs):
                callback = recorder._active
                if callback is None:
                    return super().submit(function, *args, **kwargs)
                stack = getattr(recorder._local, "stack", [])
                parent = stack[-1] if stack else None
                safe_name = getattr(function, "__name__", "unknown")
                if safe_name not in ("_write_journal_payload", "_fsync_directory"):
                    safe_name = "other_atomic_task"
                def task():
                    token = next(recorder._ids)
                    with recorder._guard:
                        recorder._live_tasks.add(token)
                    try:
                        with recorder.span("pool.task", callback=callback, parent=parent,
                                           extra={"pool": pool._capture_cost_pool_id, "function": safe_name}):
                            return function(*args, **kwargs)
                    finally:
                        with recorder._guard:
                            recorder._live_tasks.remove(token)
                with recorder.span("pool.submit", extra={"pool": pool._capture_cost_pool_id}):
                    future = super().submit(task)
                    original_result = future.result
                    def result(*result_args, **result_kwargs):
                        with recorder.span("pool.future_result_wait", callback=callback,
                                           extra={"pool": pool._capture_cost_pool_id}):
                            return original_result(*result_args, **result_kwargs)
                    # This specific future retains its type/state/ordering and
                    # exact wait semantics; no global Future class is changed.
                    future.result = result
                    return future

            def shutdown(pool, wait=True, *, cancel_futures=False):
                with recorder.span("pool.shutdown_join", extra={"pool": pool._capture_cost_pool_id}):
                    result = super().shutdown(wait=wait, cancel_futures=cancel_futures)
                if not any(thread.is_alive() for thread in pool._threads):
                    with recorder._guard:
                        recorder._live_pools.pop(pool._capture_cost_pool_id, None)
                return result

        self._patch(atomic, "ThreadPoolExecutor", RecordingPool)

        def s05(instance, number):
            index = self._s05_calls
            self._s05_calls += 1
            group = "ordinary_idle" if index < 3 else "ordinary_s05_busy"
            if index >= 6:
                self.error("unexpected_ordinary_s05_callback")
            return self.probe(group, number, instance)

        def s06(instance, number):
            if self.section == "ordinary":
                self._s06_calls += 1
                group = "ordinary_s06_busy"
            else:
                group = self.section
            return self.probe(group, number, instance)

        def unscored(instance, number):
            # Later imports by diagnose_ai_capture retain original behavior and
            # do not acquire an active recorder context or score association.
            return self.original_probe(instance, number)

        self._patch(qualification, "deterministic_probe", s05)
        self._patch(jobs, "deterministic_probe", s06)
        self._patch(report, "deterministic_probe", unscored)
        return self

    def flush(self, *, ordinary_report=None, appended_report=None):
        """Only persistent write path; call in launcher finally after workloads stop."""
        if self._active is not None or self._atomic_active or self._live_pools or self._live_tasks:
            self.error("flush_with_inflight_work")
        counts = {group: sum(row["group"] == group for row in self.callbacks)
                  for group in EXPECTED_ORDINARY}
        if counts != EXPECTED_ORDINARY:
            self.error("ordinary_callback_coverage")
        # Bind returned scalar rows to their actual official positions. No gate,
        # status, threshold or report content is rewritten by this projection.
        ordinary_rows = []
        if ordinary_report is not None:
            for group, values in (("ordinary_idle", ordinary_report.get("deterministic_idle", [])),
                                  ("ordinary_s05_busy", ordinary_report.get("deterministic_busy", [])),
                                  ("ordinary_s06_busy", ordinary_report.get("s06", {}).get("deterministic_busy", []))):
                selected = [r for r in self.callbacks if r["group"] == group]
                for index, value in enumerate(values):
                    matched = (index < len(selected) and selected[index].get("probe") is not None
                               and all(value.get(k) == v for k, v in selected[index]["probe"].items()))
                    ordinary_rows.append({"group": group, "index": index,
                                          "callback_id": selected[index]["id"] if index < len(selected) else None,
                                          "actual_row_matches": matched,
                                          "actual_public_row": value})
                    if not matched:
                        self.error("ordinary_result_row_binding")
        else:
            self.error("ordinary_report_missing")
        operation_labels = {"os.fsync": "fsync", "os.replace": "replace",
                            "os.rename": "rename", "atomic.payload_write_flush_fsync": "write_journal_payload",
                            "store.atomic_bytes": "store_atomic_bytes"}
        for callback in self.callbacks:
            callback["operations"] = [
                {"span_id": span["id"], "label": span["label"], "kind": operation_labels[span["label"]],
                 "role": span["extra"].get("role", "UNOBSERVED"),
                 "bytes": span["extra"].get("bytes"), "observer": False,
                 "outcome": ("UNOBSERVED" if span.get("after") is None else
                             span["exception_type"] if "exception_type" in span else "OK")}
                for span in callback["spans"] if span["label"] in operation_labels]
            callback["operation_coverage"] = "COMPLETE_SELECTED_WRAPPED_OPERATIONS"
            callback["operation_coverage_limits"] = {
                "fsync": "ALL_PATCHED_OS_FSYNC_CALLS_WHILE_CALLBACK_ACTIVE",
                "replace_rename": "ALL_PATCHED_OS_REPLACE_RENAME_CALLS_WHILE_CALLBACK_ACTIVE",
                "write_bytes": "EXPLICIT_JOURNAL_PAYLOAD_AND_INSTANCESTORE_ATOMIC_BYTES_ARGUMENTS_ONLY",
                "kernel_or_buffered_write_syscalls": "NOT_OBSERVED"}
            callback["observer_outer_events"] = 1
        payload = {"schema": "capture-cost-temporary-telemetry/v1",
                   "authority": "NONE_DIAGNOSTIC_NOT_QUALIFICATION", "identity": self.identity,
                   "started_at": self.started_at,
                   "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "status": "COMPLETE" if not self.errors else "INCOMPLETE",
                   "errors": self.errors, "ordinary_callback_counts": counts,
                   "ordinary_actual_row_binding": ordinary_rows,
                   "callbacks": self.callbacks, "appended_report": appended_report,
                   "native_calls": self.native_calls,
                   "calibration": self.calibration,
                   "registered_runtime_histories": self.runtime_histories,
                   "limits": ["Matched instrumentation overhead remains inside official measured spans.",
                              "Proc snapshots occur outside the original probe timer; transient TIDs may be censored.",
                              "Parent phase is last received observation, especially stale during S06 cancel callbacks.",
                              "Span wall and CPU times overlap through nesting/concurrency; never add them as disjoint time.",
                              "No arguments, payload bytes, arbitrary paths, messages, credentials or native worker mutation."]}
        raw = (json.dumps(payload, indent=2, ensure_ascii=True) + "\n").encode()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        with self.output.open("xb") as stream:
            stream.write(raw)
        return {"path": str(self.output), "bytes": len(raw), "sha256": _digest(raw),
                "status": payload["status"]}

    def uninstall(self):
        if self._active is not None or self._atomic_active or self._live_pools or self._live_tasks:
            raise RuntimeError("uninstall_with_inflight_work")
        for owner, name, original, installed in reversed(self._restores):
            if vars(owner).get(name) is not installed:
                raise RuntimeError("instrumented_binding_changed")
            setattr(owner, name, original)
        self._restores.clear()

    def drain_pools(self):
        """Outside measured spans only; attest completion after interrupted joins."""
        with self._guard:
            pools = list(self._live_pools.items())
        for pool_id, pool in pools:
            self._pool_class.shutdown(pool, wait=True)
            if any(thread.is_alive() for thread in pool._threads):
                raise RuntimeError("atomic_pool_thread_still_alive")
            with self._guard:
                self._live_pools.pop(pool_id, None)
        with self._guard:
            if self._live_tasks:
                raise RuntimeError("atomic_task_still_active")

    def calibrate(self):
        """Exactly 256 paired no-op patterns; workload-free, after ordinary only."""
        if self.calibration is not None or self._active is not None or self._atomic_active:
            raise RuntimeError("calibration_state")
        self.calibration = {
            "schema": "capture-cost-recorder-calibration/v1",
            "kind": "RECORDER_NOOP_OVERHEAD_NOT_PRODUCT_WORK",
            "pairs": 256, "patterns": {key: list(value) for key, value in CALIBRATION_PATTERNS.items()},
            "clock_resolution_ns": {name: time.get_clock_info(name).resolution * 1e9
                                    for name in ("monotonic", "process_time", "thread_time")},
            "formula_interface": "differential-envelope-v2: all512 e=outer_delta/event_count; l=max(0,min(e)-resolution),u=max(e)+resolution, wall/processCPU separately; cycle[A-B]bias=[l*meanN_A-u*meanN_B,u*meanN_A-l*meanN_B]; raw effects are never corrected or subtracted; max/median/min propagate per-row intervals into M6/I; independent analyzer recomputes every value.",
            "samples": [], "limitations": [
                "No-op events run on one thread and model recorder overhead only, not task or filesystem work.",
                "Fixed patterns are representative labels; actual callback event counts scale conservative bounds.",
                "No hardware-counter, full scheduler, syscall-causality or cProfile claim follows."]}
        for pair in range(256):
            order = ("A", "B") if pair % 2 == 0 else ("B", "A")
            result = {"pair": pair, "order": list(order), "patterns": {}}
            self.calibration["samples"].append(result)
            for arm in order:
                row = {"spans": [], "before": self._safe_clock()}
                self._active = row
                try:
                    for label in CALIBRATION_PATTERNS[arm]:
                        with self.span(label, extra={"noop_calibration": True}):
                            pass
                finally:
                    row["after"] = self._safe_clock()
                    row["delta"] = self._safe_difference(row["before"], row["after"])
                    self._active = None
                row["event_count"] = len(row["spans"])
                row["observer_outer_events"] = 1
                result["patterns"][arm] = row
        self.calibration["complete"] = all(
            row.get("delta") is not None and row["event_count"] == len(CALIBRATION_PATTERNS[arm])
            and all(row["delta"].get(key, -1) >= 0
                    for key in ("wall_ns", "thread_cpu_ns", "process_cpu_ns"))
            for pair in self.calibration["samples"]
            for arm, row in pair["patterns"].items())
        if not self.calibration["complete"]:
            self.error("calibration_incomplete")
        return self.calibration
