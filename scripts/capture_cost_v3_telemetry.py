from __future__ import annotations
import ast
from contextlib import contextmanager
import datetime
import functools
import hashlib
import inspect
import itertools
import json
import os
from pathlib import Path
import shutil
import textwrap
import threading
import time
import weakref

def _digest(raw):
    return hashlib.sha256(raw).hexdigest()

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


METHODS = ('_prepare', 'commit', '_publish_entries')
RECIPE = 'wall_process_body_process_wall/v1'
MODE = 'SPARSE_COMPONENT_V3'
REGIME = 'SPARSE_CAPTURE_AND_ATOMIC_COMPONENT_WITH_SEPARATE_C1_CONTROL'
PAYLOAD = (b'Public synthetic atomic component payload.\n' * 128)[:4096].ljust(4096, b'.')


def _boundary(start, cpu_start, cpu_end, end):
    return {'recipe': RECIPE, 'raw_wall_before_seconds': start, 'raw_wall_after_seconds': end,
            'before': {'monotonic_ns': round(start * 1e9), 'process_cpu_ns': cpu_start},
            'after': {'monotonic_ns': round(end * 1e9), 'process_cpu_ns': cpu_end}}


class Recorder:
    """Sparse primary boundaries; separate unscored durability counters only."""

    def __init__(self, *, identity, output, max_callbacks=64):
        if identity.get('regime') != REGIME:
            raise ValueError('explicit_component_regime_required')
        self.identity, self.output = dict(identity), Path(output)
        self.max_callbacks = max_callbacks
        self.callbacks, self.native_calls, self.errors = [], [], []
        self.calibration = None
        self.component_controls = None
        self.component_fixture_cleanup = []
        self.component_fixture_setup = []
        self.cohort_cleanup_completed = False
        self.section, self.section_context, self.arm = 'setup', {}, 'checkout'
        self.schedules, self.schedule_ordinals = {}, {}
        self._ids, self._local = itertools.count(1), threading.local()
        self._variants, self._restores, self._fixtures = {}, [], {}
        self._runtimes, self.runtime_histories = [], []
        self._active = None
        self._atomic_module = None
        self.original_probe = None
        self.partial_appended = None
        self._control_live_pools = set()

    def error(self, code):
        if len(self.errors) < 128:
            try:
                clock = time.monotonic_ns()
            except Exception:
                clock = None
            self.errors.append({'code': code, 'monotonic_ns': clock})

    def _safe_cpu(self):
        try:
            return time.process_time_ns()
        except Exception:
            self.error('process_clock_unavailable')
            return None

    def _patch(self, owner, name, value):
        self._restores.append((owner, name, vars(owner)[name], value))
        setattr(owner, name, value)

    def add_variant(self, arm, *, source, expected_sha256, atomic_module):
        raw = Path(source).read_bytes()
        if arm not in ('A', 'B') or arm in self._variants or _digest(raw) != expected_sha256:
            raise ValueError('exact_private_variant_source_required')
        tree = ast.parse(raw)
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AtomicInstanceCommit']
        if len(classes) != 1:
            raise ValueError('one_AtomicInstanceCommit_class_required')
        selected = [n for n in classes[0].body if isinstance(n, ast.FunctionDef) and n.name in METHODS]
        if sorted(n.name for n in selected) != sorted(METHODS):
            raise ValueError('exact_three_methods_required')
        if any(isinstance(n, ast.Name) and n.id in ('super', '__class__')
               for method in selected for n in ast.walk(method)):
            raise ValueError('unsupported_implicit_class_closure')
        module = ast.Module(body=selected, type_ignores=[])
        environment = {}
        exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), vars(atomic_module), environment)
        private = type('CaptureCostAtomic' + arm, (atomic_module.AtomicInstanceCommit,),
                       {name: environment[name] for name in METHODS})
        method_hashes = {n.name: _digest(ast.dump(n, include_attributes=False).encode()) for n in selected}
        self._variants[arm] = {'class': private, 'identity': {
            'source_sha256': expected_sha256, 'method_ast_sha256': method_hashes}}

    @contextmanager
    def variant(self, arm):
        if arm not in self._variants:
            raise ValueError('unknown_private_variant')
        previous = getattr(self._local, 'arm', None)
        self._local.arm = arm
        try:
            yield
        finally:
            self._local.arm = previous

    def _runtime_observations(self):
        result = []
        for index, reference in enumerate(self._runtimes):
            runtime = reference()
            if runtime is None:
                continue
            process = getattr(runtime, '_process', None)
            prefill = getattr(runtime, '_prefill_observation', None)
            result.append({'runtime_id': self.runtime_histories[index]['id'],
                'pid': getattr(process, 'pid', None), 'request': getattr(runtime, '_request_id', None),
                'phase_last_parent_observation': getattr(runtime, '_phase', None),
                'first_received_last_parent_observation': getattr(runtime, '_first_received', None),
                'prefill_last_parent_observation': dict(prefill) if prefill else None})
        return result

    def _snapshot(self, observations):
        started = time.monotonic_ns()
        result = {'monotonic_ns': started, 'clock_ticks_per_second': os.sysconf('SC_CLK_TCK'), 'processes': []}
        pids = sorted({os.getpid()} | {r['pid'] for r in observations if type(r.get('pid')) is int})
        for pid in pids:
            root = Path('/proc') / str(pid)
            tids = sorted(int(p.name) for p in (root / 'task').iterdir())
            if len(tids) > 64:
                raise ValueError('bounded_thread_inventory_exceeded')
            result['processes'].append({'pid': pid, 'process': _proc_task(root),
                'threads': [{'tid': tid, 'counters': _proc_task(root / 'task' / str(tid))} for tid in tids]})
        result['observation_wall_ns'] = time.monotonic_ns() - started
        return result

    def _safe_observation(self):
        try:
            runtime = self._runtime_observations()
            snapshot = self._snapshot(runtime)
            def unavailable(value):
                if isinstance(value, dict):
                    return 'unavailable_errno' in value or any(unavailable(v) for v in value.values())
                if isinstance(value, list):
                    return any(unavailable(v) for v in value)
                return False
            if unavailable(snapshot):
                raise ValueError('outside_boundary_counter_unavailable')
            return runtime, snapshot
        except Exception:
            self.error('outside_boundary_process_observation_failed')
            return [], {'status': 'UNAVAILABLE'}

    def _compile_capture(self, report):
        """Preserve every original statement/call; add two CPU reads and return boundary."""
        source = textwrap.dedent(inspect.getsource(report.deterministic_probe))
        node = ast.parse(source).body[0]
        self.identity['original_probe_ast_sha256'] = _digest(ast.dump(node, include_attributes=False).encode())
        body, first_start, receipt_seen, capture_seen = [], False, False, False
        for statement in node.body:
            body.append(statement)
            if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)):
                name = statement.targets[0].id
                if name == 'start' and not first_start:
                    body.append(ast.parse('_cc_cpu_before = _cc_safe_cpu()').body[0])
                    first_start = True
                elif name == 'receipt':
                    body.append(ast.parse('_cc_cpu_after = _cc_safe_cpu()').body[0])
                    receipt_seen = True
                elif name == 'capture':
                    if not isinstance(statement.value, ast.BinOp) or not isinstance(statement.value.left, ast.Call):
                        raise ValueError('original_capture_clock_shape')
                    original_clock = statement.value.left
                    statement.value.left = ast.NamedExpr(target=ast.Name(id='_cc_wall_after', ctx=ast.Store()),
                                                        value=original_clock)
                    body.append(ast.parse('_cc_boundary = _cc_make_boundary(start, _cc_cpu_before, _cc_cpu_after, _cc_wall_after)').body[0])
                    capture_seen = True
            if isinstance(statement, ast.Return):
                statement.value = ast.Tuple(elts=[statement.value, ast.Name(id='_cc_boundary', ctx=ast.Load())], ctx=ast.Load())
        if not (first_start and receipt_seen and capture_seen):
            raise ValueError('source_faithful_capture_recipe_not_found')
        node.body = body
        self.identity['sparse_probe_ast_sha256'] = _digest(ast.dump(node, include_attributes=False).encode())
        globals_copy = dict(report.deterministic_probe.__globals__)
        globals_copy.update(_cc_safe_cpu=self._safe_cpu, _cc_make_boundary=_boundary)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                     '<reviewed-sparse-deterministic-probe>', 'exec'), globals_copy)
        self._capture_probe = globals_copy[node.name]

    def install(self, *, qualification, jobs, report, atomic, capture, journal,
                runtime_class, instance_class, store_class):
        del instance_class
        self.original_probe = report.deterministic_probe
        if qualification.deterministic_probe is not self.original_probe or jobs.deterministic_probe is not self.original_probe:
            raise ValueError('probe_alias_identity')
        self._atomic_module, self._store_class = atomic, store_class
        self._base_atomic = atomic.AtomicInstanceCommit
        self._compile_capture(report)

        def factory(*args, **kwargs):
            arm = getattr(self._local, 'arm', None)
            selected = self._variants[arm]['class'] if arm in self._variants else self._base_atomic
            return selected(*args, **kwargs)
        for module in (capture, journal):
            if module.AtomicInstanceCommit is not self._base_atomic:
                raise ValueError('original_capture_atomic_alias_identity')
            self._patch(module, 'AtomicInstanceCommit', factory)
        self._patch(jobs, 'deterministic_probe', lambda instance, number: self.probe(self.section, number, instance))
        original_init, original_infer = runtime_class.__init__, runtime_class._infer_admitted

        @functools.wraps(original_init)
        def runtime_init(runtime, *args, **kwargs):
            original_init(runtime, *args, **kwargs)
            try:
                reference = weakref.ref(runtime)
                history = {'id': next(self._ids), 'worker_history': runtime.worker_history}
                self._runtimes.append(reference)
                self.runtime_histories.append(history)
            except Exception:
                self.error('runtime_history_registration_failed')

        @functools.wraps(original_infer)
        def infer(runtime, model, selection, prompt, **kwargs):
            row = {'id': next(self._ids), 'section': self.section,
                   'section_context': dict(self.section_context)}
            try:
                row.update(prompt_sha256=_digest(prompt.encode()), prompt_bytes=len(prompt.encode()),
                           configuration_sha256=_digest(selection.configuration), started_ns=time.monotonic_ns())
                self.native_calls.append(row)
            except Exception:
                self.error('native_input_identity_failed')
            try:
                result = original_infer(runtime, model, selection, prompt, **kwargs)
                try:
                    row.update(output_sha256=_digest(result['text'].encode()),
                               input_tokens=result.get('input_tokens'), output_tokens=result.get('output_tokens'))
                except Exception:
                    self.error('native_output_identity_failed')
                return result
            except BaseException as exc:
                row['exception_type'] = type(exc).__name__
                raise
            finally:
                try:
                    row.update(completed_ns=time.monotonic_ns(), request=getattr(runtime, '_request_id', None),
                        worker_pid=getattr(getattr(runtime, '_process', None), 'pid', None),
                        worker_observation=dict(runtime.last_observation) if getattr(runtime, 'last_observation', None) else None)
                except Exception:
                    self.error('native_final_identity_failed')
        self._patch(runtime_class, '__init__', runtime_init)
        self._patch(runtime_class, '_infer_admitted', infer)

    @staticmethod
    def _inventory(root):
        result = {}
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise ValueError('component_fixture_symlink')
            if path.is_file():
                raw = path.read_bytes()
                result[path.relative_to(root).as_posix()] = {'bytes': len(raw), 'sha256': _digest(raw)}
        return result

    def prepare_component_fixture(self, pass_index, path):
        if pass_index in self._fixtures or path.exists():
            raise ValueError('fresh_component_fixture_required')
        setup = {'micro_pass': pass_index, 'started_monotonic_ns': time.monotonic_ns(),
                 'status': 'INCOMPLETE'}
        if pass_index in (0, 1):
            self.component_fixture_setup.append(setup)
        try:
            store = self._store_class.initialise(path)
            control = path.parent / ('.' + path.name + '.provelume')
            # Ordinary fixture directories only; each transaction still creates
            # its own stage, candidate, payload, manifest and marker normally.
            control.mkdir()
            (control / 'transactions').mkdir()
            self._fixtures[pass_index] = {'store': store, 'root': path, 'control': control,
                'baseline': self._inventory(path), 'expected': {}, 'fixture_id': store.read_config()['instance']['id']}
            setup.update(fixture_id=self._fixtures[pass_index]['fixture_id'], status='COMPLETE')
        finally:
            setup['completed_monotonic_ns'] = time.monotonic_ns()

    def _postchecks(self, fixture):
        actual = self._inventory(fixture['root'])
        expected = {**fixture['baseline'], **fixture['expected']}
        targets = [{'relative': relative, **actual[relative]} for relative in sorted(fixture['expected']) if relative in actual]
        stage = fixture['control'] / 'transactions'
        return {'expected_target_count': len(fixture['expected']), 'observed_targets': targets,
            'prior_targets_unchanged': all(actual.get(k) == v for k, v in expected.items()),
            'journal_entries': sorted(p.name for p in stage.iterdir()) if stage.exists() else [],
            'unexpected_paths': sorted(set(actual) - set(expected))}

    def run_component_batch(self, group, ordinal, *, counter_only=False, fixture_key=None):
        self._active_batch = None
        key = self.section_context['micro_pass'] if fixture_key is None else fixture_key
        fixture = self._fixtures[key]
        arm = getattr(self._local, 'arm', None) or self.arm
        cls = self._variants[arm]['class']
        profile = self._atomic_module.EMAIL_INTAKE_TRANSACTION_PROFILE
        prefix = ('i' if group == 'appended_idle' else 'b') + f'{ordinal:02d}'
        targets = [{'ordinal': i, 'relative': f'state/component_{prefix}_{i:02d}.bin',
            'owner_id': 'job_' + _digest(f'{key}:{group}:{ordinal}:{i}'.encode())[:32],
            'bytes': len(PAYLOAD), 'sha256': _digest(PAYLOAD)} for i in range(32)]
        if any((fixture['root'] / t['relative']).exists() for t in targets):
            raise ValueError('component_target_must_be_absent')
        before_check = self._postchecks(fixture)
        if not before_check['prior_targets_unchanged'] or before_check['unexpected_paths'] or before_check['journal_entries']:
            raise ValueError('component_fixture_before_integrity')
        row = {'status': 'INCOMPLETE', 'expected_transactions': 32, 'completed_transactions': 0,
            'started_transaction_ordinals': [], 'completed_transaction_ordinals': [],
            'profile': profile.as_dict(), 'payload_sha256': _digest(PAYLOAD),
            'fixture_id': fixture['fixture_id'], 'targets': targets,
            'method_identity': self._variants[arm]['identity'], 'arm': arm, 'boundary': None}
        # Persist the partial identity before any transaction can be interrupted.
        self._active_batch = row
        primary = None
        start = time.monotonic() if not counter_only else None
        cpu_start = self._safe_cpu() if not counter_only else None
        try:
            for target in targets:
                row['started_transaction_ordinals'].append(target['ordinal'])
                transaction = cls(fixture['store'], fixture['control'] / 'transactions',
                                  profile=profile, owner_id=target['owner_id'])
                transaction.add(target['relative'], PAYLOAD, immutable=True)
                transaction.commit()
                row['completed_transaction_ordinals'].append(target['ordinal'])
                row['completed_transactions'] += 1
        except BaseException as exc:
            primary = exc
            row['exception_type'] = type(exc).__name__
            raise
        finally:
            cpu_end = self._safe_cpu() if not counter_only else None
            end = time.monotonic() if not counter_only else None
            if not counter_only:
                row['boundary'] = _boundary(start, cpu_start, cpu_end, end)
            for target in targets[:row['completed_transactions']]:
                fixture['expected'][target['relative']] = {'bytes': target['bytes'], 'sha256': target['sha256']}
            try:
                row['postchecks'] = self._postchecks(fixture)
                row['cleanup'] = {'status': 'COMPLETE' if not row['postchecks']['journal_entries'] else 'INCOMPLETE',
                                  'journal_empty': not row['postchecks']['journal_entries']}
                good = row['postchecks']['prior_targets_unchanged'] and not row['postchecks']['unexpected_paths']
                if row['completed_transactions'] == 32 and good and row['cleanup']['journal_empty']:
                    row['status'] = 'COMPLETE'
            except BaseException as exc:
                row.setdefault('postcheck_errors', []).append(type(exc).__name__)
                self.error('component_postcheck_failed')
                if primary is None:
                    raise
        return row

    def dispose_component_fixture(self, pass_index):
        fixture = self._fixtures.get(pass_index)
        if fixture is None or fixture.get('disposed'):
            return
        result = {'micro_pass': pass_index, 'fixture_id': fixture['fixture_id'], 'status': 'INCOMPLETE',
                  'removed': False, 'started_monotonic_ns': time.monotonic_ns()}
        fixture['cleanup_record'] = result
        if pass_index in (0, 1):
            self.component_fixture_cleanup.append(result)
        try:
            result['partial_before_recovery'] = self._postchecks(fixture)
            if result['partial_before_recovery']['journal_entries']:
                # Failure-only evidence, retained before accepted recovery can
                # remove a journal. All bytes belong to the synthetic fixture.
                journal = fixture['control'] / 'transactions'
                snapshot = self.output.parent / 'failure-journal' / str(next(self._ids))
                snapshot.mkdir(parents=True, exist_ok=False)
                files, total = [], 0
                for path in sorted(journal.rglob('*')):
                    if path.is_symlink():
                        raise ValueError('partial_journal_symlink')
                    if not path.is_file():
                        continue
                    raw = path.read_bytes()
                    total += len(raw)
                    if len(files) >= 256 or len(raw) > 1048576 or total > 4194304:
                        raise ValueError('bounded_partial_journal_inventory_exceeded')
                    entry = {'relative': path.relative_to(journal).as_posix(),
                             'bytes': len(raw), 'sha256': _digest(raw)}
                    retained = snapshot / path.relative_to(journal)
                    retained.parent.mkdir(parents=True, exist_ok=True)
                    with retained.open('xb') as stream:
                        stream.write(raw)
                    entry['snapshot_relative'] = retained.relative_to(self.output.parent).as_posix()
                    if path.name == 'manifest.json':
                        entry['original_manifest_utf8'] = raw.decode('utf-8')
                    files.append(entry)
                result['partial_journal_inventory'] = {
                    'status': 'ORIGINAL_BYTES_RETAINED_BEFORE_RECOVERY',
                    'files': files, 'payload_sha256': _digest(PAYLOAD),
                    'published_targets': [{'relative': name, **value}
                                          for name, value in self._inventory(fixture['root']).items()
                                          if name.startswith('state/component_')]}
                # Recovery is the accepted API, never a blind journal deletion.
                result['recovery'] = self._atomic_module.recover_atomic_transactions(
                    fixture['store'], fixture['control'], handlers=(self._atomic_module.AtomicRecoveryHandler(
                        self._atomic_module.EMAIL_INTAKE_TRANSACTION_PROFILE),))
            checks = self._postchecks(fixture)
            result.update(final_expected_target_count=checks['expected_target_count'],
                          final_observed_targets=checks['observed_targets'], postchecks=checks)
            if (not checks['prior_targets_unchanged'] or checks['journal_entries'] or checks['unexpected_paths']):
                self.error('component_fixture_cleanup_integrity_failed')
                raise RuntimeError('preserved_component_fixture_not_safe_to_remove')
            shutil.rmtree(fixture['root'])
            if fixture['control'].exists():
                shutil.rmtree(fixture['control'])
            result.update(status='COMPLETE', removed=not fixture['root'].exists() and not fixture['control'].exists())
            fixture['disposed'] = True
        except BaseException as exc:
            result['exception_type'] = type(exc).__name__
            raise
        finally:
            result['completed_monotonic_ns'] = time.monotonic_ns()

    def cleanup_component_fixtures(self):
        failures = []
        for key in list(self._fixtures):
            try:
                self.dispose_component_fixture(key)
            except BaseException as exc:
                failures.append(type(exc).__name__)
        if failures:
            self.error('component_fixture_cleanup_failed')
            raise RuntimeError('component_fixture_cleanup_failed')

    def drain_pools(self):
        # Primary production pools are not wrapped; unchanged product contexts
        # join them. Every registered audit pool gets an independent attempt.
        failures = []
        for pool in list(self._control_live_pools):
            try:
                pool.shutdown(wait=True)
                if any(t.is_alive() for t in pool._threads):
                    raise RuntimeError('unscored_pool_thread_still_alive')
                self._control_live_pools.discard(pool)
            except BaseException as exc:
                failures.append(type(exc).__name__)
        if failures:
            self.error('unscored_pool_drain_failed')
            raise RuntimeError('unscored_pool_drain_failed')

    def probe(self, group, number, instance):
        if group not in ('unscored_seed', 'appended_idle', 'appended_governed_busy'):
            raise ValueError('explicit_sparse_probe_group_required')
        if self._active is not None or len(self.callbacks) >= self.max_callbacks:
            raise RuntimeError('overlapping_or_excess_sparse_callback')
        ordinal = None
        arm = self.arm
        if group != 'unscored_seed':
            ordinal = self.schedule_ordinals.get(group, 0)
            self.schedule_ordinals[group] = ordinal + 1
            arm = self.schedules[group][ordinal]
        before_runtime, before_proc = self._safe_observation()
        row = {'id': next(self._ids), 'group': group, 'number': number, 'arm': arm,
            'treatment_ordinal': ordinal, 'section_context': dict(self.section_context),
            'method_identity': self._variants[arm]['identity'], 'runtime_before': before_runtime,
            'proc_before': before_proc, 'before': {'monotonic_ns': time.monotonic_ns()},
            'inner_operation_wrappers_installed': False, 'spans': []}
        self.callbacks.append(row)
        self._active = row
        previous_arm = self.arm
        try:
            self.arm = arm
            with self.variant(arm):
                if group == 'unscored_seed':
                    result = self.original_probe(instance, number)
                else:
                    result, boundary = self._capture_probe(instance, number)
                    row['capture_boundary'] = boundary
                row['probe'] = dict(result)
                if group != 'unscored_seed':
                    row['component_runtime_before'], row['component_proc_before'] = self._safe_observation()
                    row['capture_runtime_after'] = row['component_runtime_before']
                    row['capture_proc_after'] = row['component_proc_before']
                    try:
                        row['component_batch'] = self.run_component_batch(group, ordinal)
                    finally:
                        row.setdefault('component_batch', getattr(self, '_active_batch', None))
                        row['component_runtime_after'], row['component_proc_after'] = self._safe_observation()
                return result
        except BaseException as exc:
            row['exception_type'] = type(exc).__name__
            raise
        finally:
            self._active = None
            self.arm = previous_arm
            row['after'] = {'monotonic_ns': time.monotonic_ns()}
            row['runtime_after'], row['proc_after'] = self._safe_observation()

    def calibrate(self):
        samples = []
        calibration = {'schema': 'capture-cost-sparse-boundary-calibration/v1',
            'kind': 'SPARSE_BOUNDARY_NOOP_NOT_PRODUCT_WORK', 'recipe': RECIPE,
            'pairs': 256, 'complete': False, 'samples': samples,
            'clock_resolution_ns': {name: time.get_clock_info(name).resolution * 1e9
                                    for name in ('monotonic', 'process_time')}}
        self.calibration = calibration
        for pair in range(256):
            order = ['A', 'B'] if pair % 2 == 0 else ['B', 'A']
            row = {'pair': pair, 'order': order, 'patterns': {}}
            samples.append(row)
            for arm in order:
                start = time.monotonic()
                cpu_start = self._safe_cpu()
                cpu_end = self._safe_cpu()
                end = time.monotonic()
                row['patterns'][arm] = {'outcome': 'NOOP_COMPLETE', 'observation_recipes': 1,
                                       'boundary': _boundary(start, cpu_start, cpu_end, end)}
        calibration['complete'] = not self.errors and len(samples) == 256
        return calibration

    def run_component_controls(self, root):
        try:
            return self._run_component_controls(root)
        finally:
            if self.component_controls is not None:
                self.component_controls['completed_monotonic_ns'] = time.monotonic_ns()

    def _run_component_controls(self, root):
        """Only after all primaries: counters, no inner operation clocks."""
        controls = {'status': 'INCOMPLETE', 'scope': 'UNSCORED_SELECTED_PYTHON_DURABLE_OPERATIONS', 'batches': [],
                    'started_monotonic_ns': time.monotonic_ns()}
        self.component_controls = controls
        atomic, store_class = self._atomic_module, self._store_class
        for index, arm in enumerate('AB'):
            operations, pools, restores = [], [], []
            roles = threading.local()
            def patch(owner, name, value):
                restores.append((owner, name, vars(owner)[name]))
                setattr(owner, name, value)
            def record_call(function, label, kind, role=None, *, byte_argument=None, marker=False):
                @functools.wraps(function)
                def call(*args, **kwargs):
                    stack = getattr(roles, 'stack', None)
                    if stack is None:
                        stack = roles.stack = []
                    selected = role or (stack[-1] if stack else 'atomic_publish')
                    event = {'label': label, 'kind': kind, 'role': selected, 'outcome': 'INCOMPLETE'}
                    if byte_argument is not None:
                        event['bytes'] = len(args[byte_argument])
                    if marker:
                        event['marker_status'] = json.loads(args[1])['status']
                    operations.append(event)
                    if role:
                        stack.append(role)
                    try:
                        result = function(*args, **kwargs)
                        event['outcome'] = 'OK'
                        return result
                    except BaseException as exc:
                        event['outcome'] = type(exc).__name__
                        raise
                    finally:
                        if role:
                            stack.pop()
                return call
            original_pool = atomic.ThreadPoolExecutor
            recorder = self
            class AuditPool(original_pool):
                def __init__(pool, *args, **kwargs):
                    pool.audit = {'tasks_submitted': 0, 'tasks_completed': 0,
                        'shutdown_wait': False, 'threads_alive_after': None, 'function': None}
                    pools.append(pool.audit)
                    super().__init__(*args, **kwargs)
                    recorder._control_live_pools.add(pool)
                def submit(pool, function, /, *args, **kwargs):
                    pool.audit['tasks_submitted'] += 1
                    pool.audit['function'] = function.__name__
                    def task():
                        result = function(*args, **kwargs)
                        pool.audit['tasks_completed'] += 1
                        return result
                    return super().submit(task)
                def shutdown(pool, wait=True, *, cancel_futures=False):
                    result = super().shutdown(wait=wait, cancel_futures=cancel_futures)
                    pool.audit.update(shutdown_wait=wait,
                                      threads_alive_after=sum(t.is_alive() for t in pool._threads))
                    if pool.audit['threads_alive_after'] == 0:
                        recorder._control_live_pools.discard(pool)
                    return result
            key = 100 + index
            self.prepare_component_fixture(key, root / ('unscored-control-' + arm))
            primary = None
            batch = None
            try:
                patch(atomic, 'ThreadPoolExecutor', AuditPool)
                patch(atomic, '_write_journal_payload', record_call(atomic._write_journal_payload,
                    'atomic.payload_write_flush_fsync', 'write_journal_payload', 'journal_payload', byte_argument=1))
                original_directory = atomic._fsync_directory
                @functools.wraps(original_directory)
                def directory(path):
                    stack = getattr(roles, 'stack', None)
                    if stack is None:
                        stack = roles.stack = []
                    stack.append('directory')
                    try:
                        return original_directory(path)
                    finally:
                        stack.pop()
                patch(atomic, '_fsync_directory', directory)
                patch(store_class, '_atomic_bytes', staticmethod(record_call(store_class._atomic_bytes,
                    'store.atomic_bytes', 'store_atomic_bytes', 'manifest_marker', byte_argument=1, marker=True)))
                patch(os, 'fsync', record_call(os.fsync, 'os.fsync', 'fsync'))
                patch(os, 'replace', record_call(os.replace, 'os.replace', 'replace'))
                patch(os, 'rename', record_call(os.rename, 'os.rename', 'rename'))
                with self.variant(arm):
                    batch = self.run_component_batch('unscored_control', 0, counter_only=True, fixture_key=key)
                batch.update(operations=operations, pools=pools, inner_operation_clocks_installed=False)
                controls['batches'].append(batch)
            except BaseException as exc:
                primary = exc
                controls.setdefault('errors', []).append({'arm': arm, 'exception_type': type(exc).__name__})
                partial = getattr(self, '_active_batch', None)
                if partial and partial.get('fixture_id') == self._fixtures[key]['fixture_id']:
                    batch = partial
                    batch.update(operations=operations, pools=pools, inner_operation_clocks_installed=False)
                    if not any(b is batch for b in controls['batches']):
                        controls['batches'].append(batch)
                raise
            finally:
                restore_failures = []
                for owner, name, original in reversed(restores):
                    try:
                        setattr(owner, name, original)
                    except BaseException as exc:
                        restore_failures.append(type(exc).__name__)
                        self._restores.append((owner, name, original, vars(owner).get(name)))
                try:
                    self.dispose_component_fixture(key)
                except BaseException as exc:
                    restore_failures.append(type(exc).__name__)
                if batch and self._fixtures[key].get('cleanup_record'):
                    batch.setdefault('cleanup', {}).update(self._fixtures[key]['cleanup_record'])
                if restore_failures:
                    controls.setdefault('cleanup_errors', []).append({'arm': arm, 'exception_types': restore_failures})
                    self.error('unscored_control_restoration_failed')
                    if primary is None:
                        raise RuntimeError('unscored_control_restoration_failed')
        controls['status'] = ('COMPLETE' if len(controls['batches']) == 2
                              and all(b['status'] == 'COMPLETE' for b in controls['batches']) else 'INCOMPLETE')
        return controls

    def uninstall(self):
        failures, retry = [], []
        for owner, name, original, installed in reversed(self._restores):
            if vars(owner).get(name) is not installed:
                failures.append(name)
            try:
                setattr(owner, name, original)
            except BaseException as exc:
                failures.append(name + ':' + type(exc).__name__)
                retry.append((owner, name, original, installed))
        self._restores = list(reversed(retry))
        if failures:
            self.error('temporary_binding_changed_before_restore')
            raise RuntimeError('temporary_binding_restore_identity')

    def flush(self, *, ordinary_report=None, appended_report=None):
        counts = {group: sum(r['group'] == group for r in self.callbacks)
                  for group in ('unscored_seed', 'appended_idle', 'appended_governed_busy')}
        if ordinary_report is not None or counts != {'unscored_seed': 2, 'appended_idle': 12, 'appended_governed_busy': 12}:
            self.error('sparse_callback_or_ordinary_scope')
        if not self.calibration or not self.calibration.get('complete'):
            self.error('sparse_calibration_incomplete')
        if not self.component_controls or self.component_controls.get('status') != 'COMPLETE':
            self.error('unscored_component_controls_incomplete')
        if not appended_report or appended_report.get('status') != 'COMPLETE':
            self.error('complete_two_pass_cohort_required')
        budget = getattr(self, 'micro_budget', None)
        if (not budget or not self.cohort_cleanup_completed
                or budget.get('work_completed_monotonic_ns', 1 << 63) > budget.get('work_deadline_monotonic_ns', 0)
                or budget.get('cleanup_completed_monotonic_ns', 1 << 63) > budget.get('total_deadline_monotonic_ns', 0)):
            self.error('total_component_budget_not_complete')
        primary = [r for r in self.callbacks if r['group'] != 'unscored_seed']
        if (len(primary) != 24 or any(not r.get('capture_boundary')
                or not r.get('component_batch') or r['component_batch'].get('status') != 'COMPLETE'
                or r['component_batch'].get('completed_transactions') != 32 for r in primary)):
            self.error('sparse_component_primary_inventory_incomplete')
        if (len(self.component_fixture_setup) != 2 or len(self.component_fixture_cleanup) != 2
                or any(r.get('status') != 'COMPLETE' or not r.get('removed')
                       or r.get('final_expected_target_count') != 384 for r in self.component_fixture_cleanup)):
            self.error('sparse_component_fixture_inventory_incomplete')
        payload = {'schema': 'capture-cost-temporary-component-telemetry/v1', 'mode': MODE,
            'status': 'COMPLETE' if not self.errors else 'INCOMPLETE', 'identity': self.identity,
            'errors': self.errors, 'callbacks': self.callbacks, 'native_calls': self.native_calls,
            'registered_runtime_histories': self.runtime_histories, 'calibration': self.calibration,
            'component_controls': self.component_controls,
            'component_fixture_cleanup': self.component_fixture_cleanup,
            'component_fixture_setup': self.component_fixture_setup, 'micro_budget': budget,
            'ordinary_report': None, 'ordinary_control_scope': 'SEPARATE_C1_CONTROL_ONLY_NOT_THIS_RESULT',
            'ordinary_callback_counts': {'ordinary_idle': 0, 'ordinary_s05_busy': 0, 'ordinary_s06_busy': 0},
            'ordinary_actual_row_binding': [], 'appended_report': appended_report}
        self.output.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(payload, sort_keys=True) + '\n').encode()
        with self.output.open('xb') as stream:
            stream.write(raw)
        return {'path': str(self.output), 'sha256': _digest(raw), 'status': payload['status']}
