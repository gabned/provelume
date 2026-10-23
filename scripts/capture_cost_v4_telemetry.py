"""TEMP C4: bounded PROCESS phases around unchanged full ordinary Capture calls.

Import is stdlib-only. Installation is explicit and happens only in the reviewed
credential-free diagnostic context. No qualifier, evaluator or model runs here.
"""
from __future__ import annotations
import ast
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import threading
import textwrap
import time
import weakref

SCHEMA = 'capture-process-temporary-telemetry/v4'
MODE = 'FULL_ORDINARY_PROCESS_MECHANISM_V4'
REGIME = 'FULL_ORDINARY_ALL19_PROCESS_OBSERVATION_NOT_QUALIFICATION'
PHASES = ('process', 'lifecycle_entry_recovery', 'submission_inventory', 'acquisition',
          'atomic_prepare', 'atomic_publish', 'assurance', 'review_routing', 'index_refresh')
GROUPS = {
    's05_idle': (0, 3, 'deterministic_idle'),
    's05_busy': (3, 3, 'deterministic_busy'),
    's06_busy': (6, 6, 's06.deterministic_busy'),
    's07_busy': (12, 2, 's07.samples'),
    's08_idle': (14, 3, 's08.idle'),
    's08_busy': (17, 2, 's08.performance'),
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(function):
    raw = inspect.getsource(function).encode()
    node = ast.parse(textwrap.dedent(raw.decode()))
    return {'source_sha256': digest(raw),
            'method_ast_sha256': digest(ast.dump(node, include_attributes=False).encode()),
            'module': function.__module__, 'qualname': function.__qualname__}


class Recorder:
    def __init__(self, *, identity, output, control):
        if identity.get('regime') != REGIME:
            raise ValueError('explicit_C4_regime_required')
        self.identity, self.output, self.control = dict(identity), Path(output), control
        # Cache once before the ordinary suite, never gettid/proc per callback.
        self.entry_pid, self.caller_tid = os.getpid(), threading.get_native_id()
        self._caller_ident = threading.get_ident()
        self.callbacks, self.errors, self.native_calls, self.runtime_histories = [], [], [], []
        self.phase_sources, self.calibration = {}, None
        self._restores, self._runtimes = [], []
        self._active, self._stack = None, []
        self._qual_calls, self._native_id = 0, 0
        self.restoration_events = []
        self._calibrating = False
        self.original_probe = None

    def error(self, code):
        if len(self.errors) < 128:
            self.errors.append({'code': code})

    def _clock(self, name, errors):
        try:
            return getattr(time, name)()
        except BaseException as exc:
            errors.append({'clock': name, 'exception_type': type(exc).__name__})
            self.error('phase_clock_unavailable')
            return None

    def _selected(self, store=None):
        row = self._active
        return (row is not None and threading.get_ident() == self._caller_ident
                and (store is None or store is row.get('_store')))

    @staticmethod
    def _valid_spans(spans):
        if CounterPhase(spans) != dict.fromkeys(PHASES, 1):
            return False
        for index, span in enumerate(spans):
            if (span['id'] != index or span['outcome'] != 'RETURNED'
                    or span['instrumentation_errors']):
                return False
            clocks = ('monotonic_ns', 'thread_cpu_ns') + (
                ('process_cpu_ns',) if span['phase'] == 'process' else ())
            for clock in clocks:
                before, after = span['before'].get(clock), span['after'].get(clock)
                if type(before) is not int or type(after) is not int or not 0 <= before <= after:
                    return False
            parent_id = span['parent_id']
            if parent_id is not None:
                if type(parent_id) is not int or not 0 <= parent_id < index:
                    return False
                parent = spans[parent_id]
                for clock in ('monotonic_ns', 'thread_cpu_ns'):
                    if not (parent['before'][clock] <= span['before'][clock]
                            <= span['after'][clock] <= parent['after'][clock]):
                        return False
        return True

    def _record(self, phase, operation):
        row = self._active
        if row is None or not self._selected():
            return operation()
        if len(row['spans']) >= 9:
            row['errors'].append('phase_record_cap_reached')
            self.error('phase_record_cap_reached')
            return operation()
        errors = []
        span = {'id': len(row['spans']), 'parent_id': self._stack[-1]['id'] if self._stack else None,
                'phase': phase, 'source_identity': ({'kind': 'EMPTY_RECIPE'} if self._calibrating else self.phase_sources[phase]),
                'entry_pid': self.entry_pid, 'caller_tid': self.caller_tid,
                'before': {}, 'after': {}, 'outcome': 'INCOMPLETE', 'instrumentation_errors': errors}
        row['spans'].append(span)
        self._stack.append(span)
        span['before']['monotonic_ns'] = self._clock('monotonic_ns', errors)
        span['before']['thread_cpu_ns'] = self._clock('thread_time_ns', errors)
        if phase == 'process':
            span['before']['process_cpu_ns'] = self._clock('process_time_ns', errors)
        try:
            result = operation()
            span['outcome'] = 'RETURNED'
            return result
        except BaseException as exc:
            span.update(outcome='RAISED', exception_type=type(exc).__name__)
            raise
        finally:
            try:
                if phase == 'process':
                    span['after']['process_cpu_ns'] = self._clock('process_time_ns', errors)
                span['after']['thread_cpu_ns'] = self._clock('thread_time_ns', errors)
                span['after']['monotonic_ns'] = self._clock('monotonic_ns', errors)
            finally:
                if self._stack and self._stack[-1] is span:
                    self._stack.pop()
                else:
                    self.error('phase_stack_identity_not_restored')

    def _patch(self, owner, name, installed):
        self._restores.append((owner, name, vars(owner)[name], installed))
        setattr(owner, name, installed)

    def _wrap_method(self, owner, name, phase):
        original = vars(owner)[name]
        self.phase_sources[phase] = identity(original)
        @functools.wraps(original)
        def wrapped(subject, *args, **kwargs):
            if not self._selected(getattr(subject, 'store', None)):
                return original(subject, *args, **kwargs)
            parent = self._stack[-1]['phase'] if self._stack else None
            eligible = (phase == 'process' and parent is None) or (
                phase in ('submission_inventory', 'acquisition') and parent == 'process') or (
                phase == 'assurance' and parent == 'acquisition')
            if phase in ('atomic_prepare', 'atomic_publish'):
                row = self._active
                eligible = (parent == 'acquisition' and subject.profile.key == 'capture-acquisition'
                            and subject.profile.kind == 'capture.acquire'
                            and subject.owner_id == row.get('_acquisition_owner'))
                if eligible and phase == 'atomic_prepare':
                    if row.get('_transaction') is not None and row['_transaction'] is not subject:
                        row['errors'].append('second_acquisition_transaction')
                        self.error('second_acquisition_transaction')
                    row['_transaction'] = subject
                eligible = eligible and row.get('_transaction') is subject
            if not eligible:
                return original(subject, *args, **kwargs)
            def operation():
                if phase == 'acquisition':
                    self._active['_acquisition_owner'] = args[0]['id']
                return original(subject, *args, **kwargs)
            return self._record(phase, operation)
        self._patch(owner, name, wrapped)

    def install(self, *, qualification, jobs, setup, synthesis, diagnostics, report, atomic,
                capture, lifecycle_class, runtime_class):
        self.original_probe = report.deterministic_probe
        if any(module.deterministic_probe is not self.original_probe
               for module in (qualification, jobs, setup, synthesis, diagnostics)):
            raise ValueError('original_probe_alias_identity')
        for owner, name, phase in (
                (capture.CaptureAdapter, 'process', 'process'),
                (capture.CaptureAdapter, '_submission_locked', 'submission_inventory'),
                (capture.CaptureAdapter, '_acquire_locked', 'acquisition'),
                (capture.CaptureAdapter, '_assure', 'assurance'),
                (atomic.AtomicInstanceCommit, '_prepare', 'atomic_prepare'),
                (atomic.AtomicInstanceCommit, '_publish_entries', 'atomic_publish')):
            self._wrap_method(owner, name, phase)
        original_hold = vars(lifecycle_class)['_hold']
        self.phase_sources['lifecycle_entry_recovery'] = identity(original_hold)
        recorder = self
        @functools.wraps(original_hold)
        def hold(manager, *args, **kwargs):
            context = original_hold(manager, *args, **kwargs)
            if not (recorder._selected(getattr(manager, 'store', None)) and recorder._stack
                    and recorder._stack[-1]['phase'] == 'process'
                    and kwargs.get('purpose') == 'capture-acquire'):
                return context
            class EntryOnly:
                def __enter__(self):
                    return recorder._record('lifecycle_entry_recovery', context.__enter__)
                def __exit__(self, *exc):
                    return context.__exit__(*exc)
            return EntryOnly()
        self._patch(lifecycle_class, '_hold', hold)
        for name, phase in (('route_committed_acquisitions_locked', 'review_routing'),
                            ('refresh_search_index', 'index_refresh')):
            original = vars(capture)[name]
            self.phase_sources[phase] = identity(original)
            def make(function, label):
                @functools.wraps(function)
                def alias(store, *args, **kwargs):
                    if recorder._selected(store) and recorder._stack and recorder._stack[-1]['phase'] == 'process':
                        return recorder._record(label, lambda: function(store, *args, **kwargs))
                    return function(store, *args, **kwargs)
                return alias
            self._patch(capture, name, make(original, phase))
        def s05(instance, number):
            index = self._qual_calls
            self._qual_calls += 1
            if index >= 6:
                self.error('unexpected_qualification_probe')
                return self.original_probe(instance, number)
            return self.probe('s05_idle' if index < 3 else 's05_busy', index % 3, instance, number)
        def s06(instance, number):
            if type(number) is not int or not 0 <= number < 6:
                self.error('unexpected_S06_probe')
                return self.original_probe(instance, number)
            return self.probe('s06_busy', number, instance, number)
        def later(instance, number, choices):
            selected = choices.get(number)
            # The module alias as well as sample number selects a source group.
            # Unknown calls still execute their original body exactly once.
            if selected is None:
                self.error('unexpected_later_qualification_probe')
            return (self.original_probe(instance, number) if selected is None
                    else self.probe(*selected, instance, number))
        def s07(instance, number):
            return later(instance, number, {700: ('s07_busy', 0), 701: ('s07_busy', 1)})
        def s08(instance, number):
            return later(instance, number, {800: ('s08_idle', 0), 801: ('s08_idle', 1),
                                          802: ('s08_idle', 2), 810: ('s08_busy', 0),
                                          811: ('s08_busy', 1)})
        self._patch(qualification, 'deterministic_probe', s05)
        self._patch(jobs, 'deterministic_probe', s06)
        self._patch(setup, 'deterministic_probe', s07)
        self._patch(synthesis, 'deterministic_probe', s08)
        original_diagnose = diagnostics.diagnose
        @functools.wraps(original_diagnose)
        def diagnose(*args, **kwargs):
            # This entry guard is outside the unchanged cProfile.runcall body.
            self._restore_without_masking('before_legacy_diagnose')
            return original_diagnose(*args, **kwargs)
        self._patch(diagnostics, 'diagnose', diagnose)
        original_init = runtime_class.__init__
        @functools.wraps(original_init)
        def runtime_init(runtime, *args, **kwargs):
            original_init(runtime, *args, **kwargs)
            try:
                recorder._runtimes.append(weakref.ref(runtime))
                recorder.runtime_histories.append({'id': len(recorder.runtime_histories), 'worker_history': runtime.worker_history})
            except BaseException:
                recorder.error('runtime_registration_unavailable')
        self._patch(runtime_class, '__init__', runtime_init)
        original_infer = runtime_class._infer_admitted
        @functools.wraps(original_infer)
        def infer(runtime, model, selection, prompt, **kwargs):
            row = {'id': recorder._native_id}
            recorder._native_id += 1
            try:
                row.update(prompt_sha256=digest(prompt.encode()), prompt_bytes=len(prompt.encode()),
                           configuration_sha256=digest(selection.configuration),
                           started_ns=time.monotonic_ns())
                recorder.native_calls.append(row)
            except BaseException:
                recorder.error('native_input_identity_unavailable')
            try:
                result = original_infer(runtime, model, selection, prompt, **kwargs)
                try:
                    row.update(output_sha256=digest(result['text'].encode()),
                               input_tokens=result.get('input_tokens'), output_tokens=result.get('output_tokens'))
                except BaseException:
                    recorder.error('native_output_identity_unavailable')
                return result
            except BaseException as exc:
                row['exception_type'] = type(exc).__name__
                raise
            finally:
                try:
                    row.update(completed_ns=time.monotonic_ns(), request=getattr(runtime, '_request_id', None),
                               worker_pid=getattr(getattr(runtime, '_process', None), 'pid', None),
                               worker_observation=dict(runtime.last_observation)
                               if getattr(runtime, 'last_observation', None) else None)
                except BaseException:
                    recorder.error('native_final_identity_unavailable')
        self._patch(runtime_class, '_infer_admitted', infer)

    def _native_pid(self):
        pids = {getattr(getattr(r(), '_process', None), 'pid', None) for r in self._runtimes if r() is not None}
        pids.discard(None)
        if len(pids) > 1:
            self.error('multiple_current_native_workers')
            return 0
        return next(iter(pids)) if pids else 0

    def _restore_without_masking(self, reason):
        event = {'reason': reason, 'status': 'INCOMPLETE'}
        self.restoration_events.append(event)
        try:
            self.uninstall()
            event['status'] = 'ORIGINAL_BINDINGS_RESTORED'
        except BaseException as exc:
            event['exception_type'] = type(exc).__name__
            self.error('automatic_restoration_failed')

    def probe(self, group, index, instance, number=None):
        start, size, path = GROUPS[group]
        if type(index) is not int or not 0 <= index < size:
            self.error('invalid_official_probe_index')
            return self.original_probe(instance, index if number is None else number)
        if number is None:
            number = index
        slot = start + index
        if self._active is not None or threading.get_ident() != self._caller_ident:
            self.error('overlapping_or_foreign_official_probe')
            return self.original_probe(instance, number)
        if len(self.callbacks) >= 19 or any(r['id'] == slot for r in self.callbacks):
            self.error('duplicate_or_excess_official_probe')
            return self.original_probe(instance, number)
        row = {'id': slot, 'group': group, 'original_row_index': index, 'original_report_path': path,
               'number': number, 'entry_pid': self.entry_pid, 'caller_tid': self.caller_tid,
               'native_pid': self._native_pid(), 'spans': [], 'errors': [], 'status': 'OBSERVABILITY_INCOMPLETE',
               '_store': instance.store, '_transaction': None}
        self.callbacks.append(row)
        self._active = row
        self._stack = []
        try:
            try:
                if self.control.publish(slot, self.entry_pid, self.caller_tid, row['native_pid']) is not True:
                    row['errors'].append('descriptor_publication_failed')
                    self.error('descriptor_publication_failed')
            except BaseException as exc:
                row['errors'].append('descriptor_publication:' + type(exc).__name__)
                self.error('descriptor_publication_failed')
            row['before_ns'] = self._clock('monotonic_ns', row['errors'])
            result = self.original_probe(instance, number)
            # Original callers add fields such as worker_observed later. Keep
            # the original object, then bind its final whole row at flush.
            row['_returned_probe'] = result
            try:
                row['base_return_at_callback'] = dict(result)
            except BaseException:
                row['errors'].append('base_return_copy_unavailable')
                self.error('base_return_copy_unavailable')
            row['outcome'] = 'RETURNED'
            return result
        except BaseException as exc:
            row.update(outcome='RAISED', exception_type=type(exc).__name__)
            raise
        finally:
            try:
                row['after_ns'] = self._clock('monotonic_ns', row['errors'])
                try:
                    if self.control.clear(slot) is not True:
                        row['errors'].append('descriptor_clear_failed')
                        self.error('descriptor_clear_failed')
                except BaseException as exc:
                    row['errors'].append('descriptor_clear:' + type(exc).__name__)
                    self.error('descriptor_clear_failed')
                try:
                    valid = self._valid_spans(row['spans']) and not row['errors'] and row.get('outcome') == 'RETURNED'
                except BaseException:
                    valid = False
                if not valid:
                    self.error('official_phase_observation_incomplete')
                row['status'] = 'COMPLETE' if valid else 'OBSERVABILITY_INCOMPLETE'
            finally:
                self._active, self._stack = None, []
                if slot == 18:
                    self._restore_without_masking('after_last_official_callback')

    def calibrate(self):
        previous, previous_stack = self._active, self._stack
        value = {'schema': 'capture-process-nine-span-calibration/v1',
                 'kind': 'EMPTY_NINE_PHASE_RECIPES_NOT_PRODUCT', 'recipes': 512,
                 'complete': False, 'samples': [], 'clock_resolution_ns': {
                     name: time.get_clock_info(name).resolution * 1e9
                     for name in ('monotonic', 'thread_time', 'process_time')}}
        self.calibration = value
        self._calibrating = True
        try:
            for recipe in range(512):
                row = {'recipe': recipe, 'spans': [], 'errors': []}
                value['samples'].append(row)
                self._active, self._stack = row, []
                def acquisition():
                    for phase in ('atomic_prepare', 'atomic_publish', 'assurance'):
                        self._record(phase, lambda: None)
                def body():
                    for phase in ('lifecycle_entry_recovery', 'submission_inventory'):
                        self._record(phase, lambda: None)
                    self._record('acquisition', acquisition)
                    for phase in ('review_routing', 'index_refresh'):
                        self._record(phase, lambda: None)
                self._record('process', body)
            value['complete'] = len(value['samples']) == 512 and all(
                self._valid_spans(r['spans']) for r in value['samples'])
        finally:
            self._calibrating = False
            self._active, self._stack = previous, previous_stack
        return value

    def uninstall(self):
        failures, retry = [], []
        for owner, name, original, installed in reversed(self._restores):
            if vars(owner).get(name) is not installed:
                failures.append(name + ':identity_changed')
            try:
                setattr(owner, name, original)
            except BaseException as exc:
                failures.append(name + ':' + type(exc).__name__)
                retry.append((owner, name, original, installed))
        self._restores = list(reversed(retry))
        if failures:
            self.error('original_bindings_not_restored')
            raise RuntimeError('original_bindings_not_restored')

    def flush(self, *, ordinary_report):
        bindings = []
        store_ids = {}
        for row in self.callbacks:
            store = row.get('_store')
            try:
                key = id(store)
                if key not in store_ids:
                    store_ids[key] = store.read_config()['instance']['id']
                row['store_instance_id'] = store_ids[key]
            except BaseException as exc:
                row['store_instance_id_unavailable'] = type(exc).__name__
                self.error('final_store_instance_identity_unavailable')
            if '_returned_probe' in row:
                try:
                    row['probe'] = dict(row['_returned_probe'])
                except BaseException:
                    self.error('final_returned_row_copy_unavailable')
        for group, (start, size, path) in GROUPS.items():
            source = ordinary_report
            try:
                for part in path.split('.'):
                    source = source[part]
                if group in ('s07_busy', 's08_busy'):
                    source = [r['probe'] for r in source]
                if type(source) is not list:
                    raise ValueError('original_row_list_required')
            except (KeyError, TypeError, ValueError):
                source = []
            if len(source) != size:
                self.error('original_report_callback_group_count')
            for index in range(size):
                row = next((r for r in self.callbacks if r['id'] == start + index), None)
                equal = row is not None and index < len(source) and row.get('probe') == source[index]
                same_object = row is not None and index < len(source) and row.get('_returned_probe') is source[index]
                bindings.append({'callback_id': start + index, 'path': path, 'index': index,
                                 'equal': equal, 'same_returned_object': same_object})
                if not equal or not same_object:
                    self.error('original_report_callback_row_binding')
        if len(self.callbacks) != 19 or any(r['status'] != 'COMPLETE' for r in self.callbacks):
            self.error('complete_nineteen_callback_observations_required')
        if not self.calibration or self.calibration.get('complete') is not True:
            self.error('complete_512_empty_recipes_required')
        callbacks = [{k: v for k, v in row.items() if not k.startswith('_')} for row in self.callbacks]
        payload = {'schema': SCHEMA, 'mode': MODE, 'regime': REGIME, 'identity': self.identity,
                   'status': 'COMPLETE' if not self.errors else 'OBSERVABILITY_INCOMPLETE',
                   'errors': self.errors, 'callbacks': callbacks, 'phase_sources': self.phase_sources,
                   'calibration': self.calibration, 'ordinary_report': ordinary_report,
                   'ordinary_actual_row_binding': bindings, 'registered_runtime_histories': self.runtime_histories,
                   'restoration_events': self.restoration_events,
                   'runtime_history_scope': 'FINAL_ORDINARY_INCLUDING_LEGACY_DIAGNOSTIC',
                   'native_call_scope': 'ADMITTED_WHILE_HOOK_INSTALLED; IN_FLIGHT_COMPLETION_RETAINED_AFTER_RESTORATION',
                   'native_calls': self.native_calls, 'limits': [
                       'No new legacy diagnostic call enters the native ledger after hook restoration.',
                       'Caller CPU excludes sibling workers; process CPU is separate root PROCESS only.',
                       'Inclusive nested phases must never be summed as independent work.',
                       'Instrumented full ordinary execution is diagnostic, not candidate qualification.']}
        self.output.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(payload, sort_keys=True, allow_nan=False) + '\n').encode()
        with self.output.open('xb') as stream:
            stream.write(raw)
        return {'path': str(self.output), 'sha256': digest(raw), 'status': payload['status']}


def CounterPhase(spans):
    result = {}
    for span in spans:
        name = span['phase']
        result[name] = result.get(name, 0) + 1
    return result
