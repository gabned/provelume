"""Passive C4 full-ordinary process-mechanism analysis; never qualification.

Stdlib only. No candidate imports or execution. Original artifacts are read only
in the host-selected credential-free offline laboratory after original-byte and
accepted-evaluator/network replay. Real performance failures remain failures.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import statistics

PLAN_SCHEMA = 'capture-process-mechanism-experiment/v4'
MODE = 'FULL_ORDINARY_PROCESS_MECHANISM_V4'
REGIME = 'FULL_ORDINARY_ALL19_PROCESS_OBSERVATION_NOT_QUALIFICATION'
TELEMETRY_SCHEMA = 'capture-process-temporary-telemetry/v4'
CALIBRATION_SCHEMA = 'capture-process-nine-span-calibration/v1'
PHASE_PARENT = {
    'process': None,
    'lifecycle_entry_recovery': 'process',
    'submission_inventory': 'process',
    'acquisition': 'process',
    'atomic_prepare': 'acquisition',
    'atomic_publish': 'acquisition',
    'assurance': 'acquisition',
    'review_routing': 'process',
    'index_refresh': 'process',
}
GROUPS = (
    ('s05_idle', 3, ('deterministic_idle',), 0),
    ('s05_busy', 3, ('deterministic_busy',), 0),
    ('s06_busy', 6, ('s06', 'deterministic_busy'), 0),
    ('s07_busy', 2, ('s07', 'samples'), 700),
    ('s08_idle', 3, ('s08', 'idle'), 800),
    ('s08_busy', 2, ('s08', 'performance'), 810),
)
SLOTS = ('A1', 'B1', 'B2', 'A2')
OBSERVER_POLICY = {
    'interval_ns': 50_000_000, 'per_callback_round_cap': 128, 'total_round_cap': 2432,
    'tid_cap': 16, 'target_cap': 3, 'encoded_bytes_cap': 16 * 1024**2,
    'rss_limit_bytes': 64 * 1024**2, 'control_bytes': 4096, 'slot_bytes': 128,
    'slots': 19, 'calibration_recipes': 512, 'max_read_attempts': 192,
    'max_read_bytes': 256 * 1024,
}
GATES = {
    'cold_load', 'cold_first', 'cold_total', 'warm_first', 'warm_total',
    'warm_preparation', 'worker_peak_rss', 'cancel_load', 'cancel_generation',
    'unload', 'parent_ram_after_unload', 'quality_en', 'quality_it',
    'absent_model', 'altered_model', 'deterministic', 'network', 'next_caller',
    's06_governed', 's07_setup', 's08_references', 's08_abstention',
    's08_quality_en_summary', 's08_quality_en_key-points',
    's08_quality_it_summary', 's08_quality_it_key-points', 's08_performance',
    'iudicium_execution_conformance',
}
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 4096


class Unsupported(ValueError):
    """Fixed error codes only; never interpolate untrusted matched content."""


def require(condition, code):
    if not condition:
        raise Unsupported(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result

    def nonfinite(_value):
        raise Unsupported('nonfinite_json_number')

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def integer(value, code, *, positive=False):
    require(type(value) is int and value >= (1 if positive else 0), code)
    return value


def finite_seconds(value, code):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, code)
    return value


def interval_union(intervals):
    """Union length, never a sum of inclusive overlapping spans."""
    ordered = sorted(intervals)
    if not ordered:
        return 0
    start, end = ordered[0]
    require(start <= end, 'negative_interval')
    total = 0
    for left, right in ordered[1:]:
        require(left <= right, 'negative_interval')
        if left > end:
            total += end - start
            start, end = left, right
        else:
            end = max(end, right)
    return total + end - start


def span_tree(spans, expected_sources=None):
    """Closed nine-stage geometry and same-caller CPU checks; no latency gate."""
    require(type(spans) is list and len(spans) == 9, 'nine_phase_count')
    require(Counter(s.get('phase') for s in spans) == Counter(PHASE_PARENT.keys()), 'nine_phase_identity')
    by_name = {s['phase']: s for s in spans}
    require(len({s.get('id') for s in spans}) == 9, 'duplicate_phase_id')
    pid = integer(by_name['process']['entry_pid'], 'phase_entry_pid', positive=True)
    tid = integer(by_name['process']['caller_tid'], 'phase_caller_tid', positive=True)
    metrics = {}
    for name, span in by_name.items():
        require(span.get('entry_pid') == pid and span.get('caller_tid') == tid,
                'phase_caller_identity_changed')
        parent_name = PHASE_PARENT[name]
        parent = by_name[parent_name] if parent_name else None
        require(span.get('parent_id') == (parent['id'] if parent else None), 'phase_parent_identity')
        if expected_sources is not None:
            require(span.get('source_identity') == expected_sources[name], 'phase_source_identity')
        require(span.get('instrumentation_errors') == [], 'phase_instrumentation_error')
        require(span.get('outcome') == 'RETURNED' and span.get('exception_type') is None,
                'original_phase_not_returned')
        before, after = span['before'], span['after']
        start = integer(before['monotonic_ns'], 'phase_wall_before')
        end = integer(after['monotonic_ns'], 'phase_wall_after')
        cpu0 = integer(before['thread_cpu_ns'], 'phase_thread_cpu_before')
        cpu1 = integer(after['thread_cpu_ns'], 'phase_thread_cpu_after')
        require(start <= end and cpu0 <= cpu1, 'phase_clock_decreased')
        if parent:
            require(parent['before']['monotonic_ns'] <= start <= end <= parent['after']['monotonic_ns'],
                    'phase_crossed_parent_wall')
            require(parent['before']['thread_cpu_ns'] <= cpu0 <= cpu1 <= parent['after']['thread_cpu_ns'],
                    'phase_crossed_parent_cpu')
            require('process_cpu_ns' not in before and 'process_cpu_ns' not in after,
                    'nonroot_process_cpu_not_contract')
        else:
            p0 = integer(before['process_cpu_ns'], 'process_cpu_before')
            p1 = integer(after['process_cpu_ns'], 'process_cpu_after')
            require(p0 <= p1, 'process_cpu_decreased')
        metrics[name] = {
            'wall_ns': end - start, 'caller_thread_cpu_ns': cpu1 - cpu0,
            'start_ns': start, 'end_ns': end,
            'parent_phase': parent_name,
        }
        if name == 'process':
            metrics[name]['net_parent_process_cpu_ns'] = p1 - p0
        children = [s for s in spans if s.get('parent_id') == span['id']]
        intervals = [(s['before']['monotonic_ns'], s['after']['monotonic_ns']) for s in children]
        # These direct children are serial source calls. An overlap is a recording
        # defect, not removable overhead or a permissible double count.
        length_sum = sum(b - a for a, b in intervals)
        child_union = interval_union(intervals)
        require(child_union == length_sum, 'sibling_phase_overlap')
        residual = end - start - child_union
        require(residual >= 0, 'negative_phase_residual')
        metrics[name]['direct_child_union_ns'] = child_union
        metrics[name]['unassigned_wall_residual_ns'] = residual
    return metrics


def ordinary_rows(report):
    """All nineteen source-selected original rows; no newly invoked probes."""
    rows = []
    for group, count, path, first_number in GROUPS:
        selected = report
        for key in path:
            selected = selected[key]
        require(type(selected) is list and len(selected) == count, 'original_group_count')
        for index, value in enumerate(selected):
            probe = value['probe'] if group in ('s07_busy', 's08_busy') else value
            require(type(probe) is dict and probe.get('sample') == first_number + index,
                    'original_probe_sample')
            for key in ('capture_seconds', 'capture_submit_seconds', 'capture_process_seconds', 'search_seconds'):
                finite_seconds(probe[key], 'original_probe_time')
            rows.append({'id': len(rows), 'group': group, 'original_row_index': index,
                         'number': first_number + index, 'probe': probe})
    require(len(rows) == 19, 'original_nineteen_rows')
    return rows


def summarize(values):
    require(type(values) is list and values, 'empty_descriptive_summary')
    return {'n': len(values), 'min': min(values), 'median': statistics.median(values), 'max': max(values)}


def calibration_summary(calibration):
    require(calibration.get('schema') == CALIBRATION_SCHEMA
            and calibration.get('recipes') == 512 and calibration.get('complete') is True,
            'calibration_contract')
    samples = calibration.get('samples')
    require(type(samples) is list and len(samples) == 512, 'calibration_exact_512')
    values = {'wall_ns': [], 'caller_thread_cpu_ns': [], 'net_parent_process_cpu_ns': []}
    phases = {name: [] for name in PHASE_PARENT}
    previous_end = None
    for ordinal, sample in enumerate(samples):
        require(sample.get('recipe') == ordinal, 'calibration_fixed_recipe_order')
        metrics = span_tree(sample['spans'])
        require(previous_end is None or metrics['process']['start_ns'] >= previous_end,
                'calibration_recipe_wall_order')
        previous_end = metrics['process']['end_ns']
        for key in values:
            values[key].append(metrics['process'][key])
        for name in PHASE_PARENT:
            phases[name].append(metrics[name]['wall_ns'])
    resolution = calibration['clock_resolution_ns']
    require(set(resolution) == {'monotonic', 'thread_time', 'process_time'}, 'clock_resolution_keys')
    for value in resolution.values():
        require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                'clock_resolution_value')
    return {
        'recipes': 512, 'raw_samples_preserved_in_original_telemetry': True,
        'root_recipe_summaries_ns': {key: summarize(value) for key, value in values.items()},
        'phase_wall_summaries_ns': {key: summarize(value) for key, value in phases.items()},
        'clock_resolution_ns': resolution,
        'scope': 'Observed recorder no-op costs only; no subtraction or universal overhead bound',
    }


def callback_metrics(callback, expected, expected_sources):
    require(all(callback.get(k) == expected[k] for k in ('id', 'group', 'original_row_index', 'number')),
            'callback_original_identity')
    require(callback.get('probe') == expected['probe'], 'callback_original_row_not_verbatim')
    require(callback.get('errors') == [], 'callback_observability_errors')
    before = integer(callback['before_ns'], 'callback_before')
    after = integer(callback['after_ns'], 'callback_after')
    require(before <= after, 'callback_clock_order')
    metrics = span_tree(callback['spans'], expected_sources)
    require(before <= metrics['process']['start_ns'] <= metrics['process']['end_ns'] <= after,
            'process_outside_original_probe_wrapper')
    root = next(s for s in callback['spans'] if s['phase'] == 'process')
    require(callback.get('entry_pid') == root['entry_pid'] and callback.get('caller_tid') == root['caller_tid'],
            'callback_phase_pid_tid_binding')
    return {
        'id': expected['id'], 'group': expected['group'],
        'original_row_index': expected['original_row_index'], 'number': expected['number'],
        'original_probe': expected['probe'], 'entry_pid': callback['entry_pid'],
        'caller_tid': callback['caller_tid'], 'native_pid': callback.get('native_pid'),
        'store_instance_id': callback['store_instance_id'],
        'phase_metrics': metrics,
        'outer_original_probe_window_ns': {'start': before, 'end': after},
        'cpu_scope': 'PROCESS only; excludes observer/native child; includes all parent-process threads',
    }


def full_ordinary_coverage(report):
    """An early aborted FAIL is not a full previous-load control observation."""
    require(report.get("status") in ("PASS", "FAIL") and report.get("failures") == [],
            "ordinary_original_exception_or_partial_status")
    require(report.get("phase") == "final_integrity_and_cleanup"
            and report.get("final_integrity_stage") == "capture_diagnostic", "ordinary_final_phase")
    require(len(report.get("cold", [])) == 3 and len(report.get("samples", [])) == 60,
            "ordinary_3_cold_60_samples")
    require(3 <= len(report.get("warm_preparations", [])) <= 60, "ordinary_warm_preparation_coverage")
    require(len(report.get("deterministic_idle", [])) == 3
            and len(report.get("deterministic_busy", [])) == 3, "ordinary_s05_probe_coverage")
    require(all(report.get(key) for key in ("cancel_load", "cancel_generation", "idle_unload",
                                           "worker_error", "altered_model", "absent_model")),
            "ordinary_lifecycle_coverage")
    s06, s07, s08 = report.get("s06", {}), report.get("s07", {}), report.get("s08", {})
    require(s06.get("status") == "MEASURED" and len(s06.get("samples", [])) == 6
            and len(s06.get("cancellations", [])) == 2
            and len(s06.get("deterministic_busy", [])) == 6, "ordinary_full_s06_coverage")
    require(s07.get("status") == "MEASURED" and len(s07.get("samples", [])) == 2,
            "ordinary_full_s07_coverage")
    require(s08.get("status") == "MEASURED" and len(s08.get("samples", [])) == 32
            and len(s08.get("performance", [])) == 2 and len(s08.get("idle", [])) == 3
            and bool(s08.get("cancellation")), "ordinary_full_s08_coverage")
    iudicium = report.get("iudicium_execution", {})
    require(iudicium.get("status") == "MEASURED" and len(iudicium.get("samples", [])) == 2
            and {r.get("language") for r in iudicium["samples"]} == {"en", "it"}
            and iudicium.get("journey", {}).get("status") == "MEASURED",
            "ordinary_full_iudicium_coverage")
    network = report.get("network_observation", {})
    require(report.get("network") == "PASS" and network.get("status") == "PASS"
            and network.get("complete_phases") is True and bool(report.get("worker_pids")),
            "ordinary_complete_network_observation")
    require(all(v in ("PASS", "FAIL") for v in report["gates"].values()),
            "ordinary_not_run_or_blocked_gate")
    return {"source": "raw final original report", "complete_previous_load": True,
            "three_cold": 3, "samples": 60, "idle": 3, "s05_busy": 3,
            "s06_samples": 6, "s06_cancellations": 2, "s07_samples": 2,
            "s08_samples": 32, "iudicium_samples": 2, "network_complete": True}


def pinned_json(path, expected_sha256):
    raw = Path(path).read_bytes()
    require(re.fullmatch('[0-9a-f]{64}', expected_sha256) is not None
            and digest(raw) == expected_sha256, 'selected_input_sha256')
    return load_json(raw), raw


def validate_plan(plan):
    require(plan.get('schema') == PLAN_SCHEMA and plan.get('status') == 'FROZEN'
            and plan.get('mode') == MODE and plan.get('regime') == REGIME,
            'frozen_plan_mode')
    require(plan.get('repository') == 'gabned/provelume' and plan.get('repository_id') == 1343746770,
            'frozen_plan_repository')
    expected = {'job_seconds': 1200, 'workflow_runs': 1, 'run_attempt': 1, 'job_count': 4,
                'max_parallel': 2, 'callbacks_per_job': 19, 'callback_count_total': 76}
    require(all(type(plan.get(k)) is int and plan[k] == v for k, v in expected.items())
            and plan.get('fail_fast') is False, 'frozen_cohort_geometry')
    require(not any(k in plan for k in ('micro_budget_seconds', 'work_budget_seconds',
                                      'cleanup_budget_seconds', 'total_callbacks', 'diagnostic_helpers')),
            'unselected_legacy_plan_alias')
    require(plan.get('qualification') == plan.get('correction_support') == 'NOT_GRANTED',
            'frozen_plan_scope')
    require(plan.get('observer') == OBSERVER_POLICY, 'fixed_bounded_observer_policy')
    require(plan.get('slot_order') == list(SLOTS) and len(plan.get('cells', [])) == 4,
            'four_fixed_slots')
    for ordinal, cell in enumerate(plan['cells']):
        arm = ('A', 'B', 'B', 'A')[ordinal]
        variant = 'original' if arm == 'A' else 'fastpath'
        require(cell == {'ordinal': ordinal, 'slot': SLOTS[ordinal], 'ordinary_arm': arm,
                         'job_name': 'capture-cost-c4-' + SLOTS[ordinal],
                         'artifact_name': 'capture-cost-c4-' + SLOTS[ordinal] + '-' + variant},
                'fixed_slot_identity')
    for key in ('original_commit', 'fast_commit', 'base_commit'):
        require(re.fullmatch('[0-9a-f]{40}', plan.get(key, '')) is not None, 'actual_source_commit')
    require(plan['original_commit'] != plan['fast_commit']
            and plan['source_parents'] == {'A': plan['base_commit'], 'B': plan['original_commit']},
            'linear_source_graph')
    require(plan['analysis']['accepted_source'] == '210512725f1826861585278214d21fd31093e123'
            and plan['analysis']['accepted_evaluator_sha256'] ==
            '754802fe6b2eb0b5bd67d6a962dcd9ed31179c9acd8e0526df6d176600410e22'
            and plan['analysis']['accepted_observer_sha256'] ==
            '9acb929c7f708a9590d9fe961744437882699daf38a9f46b2f6f14f428e624e9',
            'unchanged_accepted_replay')
    return plan


def execution_identity(manifest, workflow_head, run_id, plan_sha256):
    require(manifest.get('workflow_head') == workflow_head and manifest.get('run_id') == run_id
            and manifest.get('run_attempt') == 1 and manifest.get('plan_sha256') == plan_sha256
            and manifest.get('slot_order') == list(SLOTS), 'original_manifest_execution_identity')
    raw_conclusions = {}
    for key in ('run_original', 'attempt_original'):
        row = manifest[key]
        require(row.get('id') == run_id and row.get('head_sha') == workflow_head
                and row.get('run_attempt') == 1 and row.get('workflow_id') == 374188063
                and row.get('event') == 'workflow_dispatch'
                and row.get('path') == '.github/workflows/ai-runtime-candidate.yml'
                and row.get('actor', {}).get('id') == 25499689
                and row.get('triggering_actor', {}).get('id') == 25499689
                and row.get('repository', {}).get('id') == 1343746770
                and row.get('status') == 'completed' and type(row.get('conclusion')) is str,
                'actual_original_run_attempt_identity')
        raw_conclusions[key] = row['conclusion']
    require(raw_conclusions['run_original'] == raw_conclusions['attempt_original'],
            'raw_run_attempt_conclusions_incoherent')
    return raw_conclusions


def audited_members(audit_slot, names):
    """Use independently audited/extracted bytes; never a second ZIP audit."""
    inventory, _ = pinned_json(audit_slot['zip_inventory']['path'], audit_slot['zip_inventory']['sha256'])
    require(inventory.get('artifact_id') == audit_slot['artifact_id']
            and inventory.get('sha256') == audit_slot['zip_sha256']
            and inventory.get('bytes') == audit_slot['zip_bytes'], 'audited_zip_inventory_binding')
    base = Path(audit_slot['zip_inventory']['path']).parent / 'original-members'
    require(base.is_absolute() and base == base.resolve() and not base.is_symlink(), 'audited_member_root')
    require(len({row['path'] for row in inventory['members']}) == len(inventory['members']),
            'audited_inventory_duplicate')
    result = {}
    for name in names:
        relative = PurePosixPath(name)
        require(not relative.is_absolute() and '..' not in relative.parts and '\\' not in name
                and '\0' not in name and all(':' not in p for p in relative.parts),
                'audited_member_relative_path')
        entries = [r for r in inventory['members'] if r['path'] == name]
        require(len(entries) == 1, 'audited_required_member_missing')
        path = base / name
        require(path.is_file() and not path.is_symlink() and path == path.resolve()
                and path.is_relative_to(base), 'audited_member_path')
        raw = path.read_bytes()
        require(len(raw) == entries[0]['bytes'] and digest(raw) == entries[0]['sha256'],
                'audited_extracted_bytes_differ')
        result[name] = {'raw': raw, 'sha256': digest(raw), 'bytes': len(raw)}
    return result


def original_job(manifest, plan, ordinal, workflow_head, run_id):
    matches = [j for j in manifest['jobs'] if j.get('ordinal') == ordinal]
    require(len(matches) == 1, 'exact_original_job_slot')
    job = matches[0]
    cell = plan['cells'][ordinal]
    require(job.get('slot') == cell['slot'] and job.get('head_sha') == workflow_head
            and job.get('expected_checkout_source') == plan[
                'original_commit' if cell['ordinary_arm'] == 'A' else 'fast_commit'],
            'original_job_slot_source')
    for key in ('listed_original', 'direct_original'):
        row = job[key]
        require(row.get('id') == job['job_id'] and row.get('run_id') == run_id
                and row.get('head_sha') == workflow_head and row.get('run_attempt') == 1
                and row.get('status') == 'completed' and type(row.get('conclusion')) is str,
                'original_job_terminal_identity')
    require(all(job['listed_original'].get(k) == job['direct_original'].get(k)
                for k in ('status', 'conclusion', 'started_at', 'completed_at')),
            'original_list_direct_incoherent')
    return job


def source_integrity(plan, plan_sha256, members, workflow_head, ordinal):
    names, cell = plan['source_proof_members'], plan['cells'][ordinal]
    arm = cell['ordinary_arm']
    head = plan['original_commit'] if arm == 'A' else plan['fast_commit']

    def raw(key):
        return members[names[key]]['raw']

    require(raw('checkout_git').decode('ascii').splitlines() ==
            [head, plan['source_parents'][arm], plan['source_trees'][arm]], 'original_checkout_git_proof')
    workflow = raw('workflow_git').decode('ascii').splitlines()
    require(len(workflow) == 3 and workflow[:2] == [workflow_head, plan['fast_commit']]
            and re.fullmatch('[0-9a-f]{40}', workflow[2]) is not None, 'original_workflow_git_proof')
    require(digest(raw('frozen_plan')) == plan_sha256 and raw('source_status_after') == b'',
            'frozen_plan_or_source_status')
    for key in ('ordinary_copy_exit', 'source_status_exit', 'source_head_exit', 'source_tree_exit'):
        require(raw(key) == b'0\n', 'required_copy_or_source_exit_nonzero')
    require(raw('source_head_after').decode('ascii').strip() == head
            and raw('source_tree_after').decode('ascii').strip() == plan['source_trees'][arm],
            'source_head_tree_changed_after_measurement')
    return {'source_head': head, 'source_parent': plan['source_parents'][arm],
            'source_tree': plan['source_trees'][arm],
            'actual_observer_parent_exit': parse_exit(raw('observer_parent_exit')),
            'actual_canonical_network_exit': parse_exit(raw('network_exit')),
            'source_and_copy_exits_zero': True,
            'proof_member_sha256': {key: members[value]['sha256'] for key, value in names.items()}}


def parse_exit(raw):
    require(re.fullmatch(rb'-?[0-9]+\n', raw) is not None, 'original_exit_code_shape')
    return int(raw)


SYSCALL_FAMILIES_X86_64 = {
    0: 'read', 1: 'write', 2: 'metadata_open', 4: 'metadata_stat', 5: 'metadata_stat',
    6: 'metadata_stat', 17: 'read', 18: 'write', 19: 'read', 20: 'write',
    74: 'fsync', 75: 'fdatasync', 82: 'metadata_rename', 87: 'metadata_unlink',
    202: 'futex', 257: 'metadata_open', 262: 'metadata_stat',
    263: 'metadata_unlink', 264: 'metadata_rename', 316: 'metadata_rename',
    332: 'metadata_stat',
}


def available(observation):
    return isinstance(observation, dict) and observation.get('availability') == 'AVAILABLE'


def wholly_inside(observation, start, end):
    return (available(observation) and type(observation.get('started_ns')) is int
            and type(observation.get('completed_ns')) is int
            and start <= observation['started_ns'] <= observation['completed_ns'] <= end)


def task_observation(task, role, pid, tick, callback):
    """Every observed caller/leader state, without assigning a wait duration."""
    result = {'tick': tick['tick'], 'role': role, 'pid': pid, 'tid': task.get('tid'),
              'birth_identity_verified': task.get('birth_identity_verified'),
              'raw_stat_before': task.get('stat_before'), 'raw_stat_after': task.get('stat_after'),
              'raw_schedstat': task.get('schedstat'), 'raw_wchan': task.get('wchan'),
              'raw_syscall_first_token': task.get('syscall'),
              'sample_read_interval_ns': [tick['started_ns'], tick['completed_ns']],
              'evidence': 'UNKNOWN_OR_UNAVAILABLE', 'aligned_phases': []}
    before, after = task.get('stat_before'), task.get('stat_after')
    syscall, wchan = task.get('syscall'), task.get('wchan')
    if not (task.get('birth_identity_verified') is True and available(before) and available(after)):
        return result
    states = [before['value'].get('state'), after['value'].get('state')]
    result['states_before_after'] = states
    if any(s in ('T', 't') for s in states):
        result['evidence'] = 'OBSERVED_TRACE_OR_JOB_CONTROL_STOP_NOT_SYSCALL_WAIT_PROOF'
    elif available(syscall):
        number = syscall['value'].get('number')
        result['observed_syscall_number'] = number
        result['observed_syscall_family_x86_64'] = SYSCALL_FAMILIES_X86_64.get(number, 'OTHER_OR_NO_ACTIVE_SYSCALL')
        result['evidence'] = 'SYSCALL_TOKEN_OBSERVED_NOT_BLOCKING_PROOF'
        if (states[0] == states[1] and states[0] not in ('R', 'T', 't')
                and available(wchan) and wchan.get('value') not in ('', '0')
                and type(number) is int and number >= 0):
            result['evidence'] = 'READ_SEQUENCE_WAIT_ASSOCIATION_NOT_DURATION_OR_CAUSAL_PROOF'
    elif 'R' in states:
        result['evidence'] = 'OBSERVED_RUNNABLE_STATE_NOT_CONTINUOUS_CPU_PROOF'
    for phase, metric in callback['phase_metrics'].items():
        left, right = metric['start_ns'], metric['end_ns']
        if wholly_inside(before, left, right) and wholly_inside(after, left, right):
            result['aligned_phases'].append(phase)
    return result


def sampler_analysis(sampler, callbacks, plan, plan_sha256, workflow_head, run_id):
    require(sampler.get('schema') == 'capture-process-proc-observation/v4'
            and sampler.get('mode') == MODE and sampler.get('regime') == REGIME,
            'sampler_schema')
    require(sampler.get('plan_sha256') == plan_sha256 and sampler.get('workflow_head') == workflow_head
            and sampler.get('run_id') == str(run_id) and sampler.get('run_attempt') == '1',
            'sampler_execution_identity')
    require(sampler.get('policy') == plan['observer'] and sampler.get('cell') in plan['cells'],
            'sampler_frozen_policy')
    entry_pid = integer(sampler['entry_pid'], 'sampler_entry_pid', positive=True)
    require(integer(sampler['observer_pid'], 'sampler_observer_pid', positive=True) != entry_pid,
            'observer_is_separate_parent_process')
    require(sampler.get('runtime_support', {}).get('supported') is True, 'unsupported_publication_runtime')
    descriptors = sampler.get('final_descriptors')
    require(type(descriptors) is list and len(descriptors) == 19, 'final_nineteen_descriptors')
    by_id = {c['id']: c for c in callbacks}
    for ordinal, row in enumerate(descriptors):
        require(row.get('slot') == ordinal and row.get('generation') == ordinal + 1
                and row.get('published_identity_verified') is True and row.get('entry_pid') == entry_pid,
                'immutable_descriptor_identity')
        if ordinal in by_id:
            require(row.get('caller_tid') == by_id[ordinal]['caller_tid']
                    and row.get('native_pid') == by_id[ordinal]['native_pid'],
                    'descriptor_callback_pid_tid_binding')
    records = sampler.get('records')
    require(type(records) is list, 'sampler_records')
    policy = plan['observer']
    counts, round_counts = Counter(), Counter()
    events = {i: [] for i in range(19)}
    retained_errors, previous = [], None
    for ordinal, tick in enumerate(records):
        require(tick.get('tick') == ordinal, 'fixed_sampler_tick_order')
        for key in ('scheduled_ns', 'started_ns', 'completed_ns', 'lateness_ns',
                    'missed_intervals', 'sampling_body_thread_cpu_ns'):
            integer(tick[key], 'sampler_tick_counter')
        require(tick['scheduled_ns'] <= tick['started_ns'] <= tick['completed_ns']
                and tick['lateness_ns'] == tick['started_ns'] - tick['scheduled_ns'],
                'sampler_tick_clock_order')
        if previous:
            require(tick['scheduled_ns'] == previous['scheduled_ns'] +
                    (previous['missed_intervals'] + 1) * policy['interval_ns'], 'sampler_fixed_cadence')
        previous = tick
        counts['wakeups'] += 1
        counts['missed_intervals'] += tick['missed_intervals']
        descriptor = tick['descriptor']
        state = descriptor.get('status')
        if state == 'INACTIVE':
            require('sample' not in tick, 'inactive_proc_sample_forbidden')
            counts['inactive_ticks'] += 1
            continue
        if state != 'ACTIVE':
            require('sample' not in tick, 'incoherent_proc_sample_forbidden')
            retained_errors.append({'tick': ordinal, 'scope': 'descriptor', 'raw': descriptor})
            continue
        slot = integer(descriptor['slot'], 'active_callback_slot')
        require(slot < 19 and descriptor.get('generation') == slot + 1
                and descriptor.get('active_before') == descriptor.get('active_after') == slot + 1
                and descriptor.get('entry_pid') == entry_pid, 'active_descriptor_identity')
        counts['active_ticks'] += 1
        sample = tick.get('sample')
        if sample is None:
            retained_errors.append({'tick': ordinal, 'scope': 'active_sample_missing'})
            continue
        if (sample.get('active_flag_at_sample_end') != slot + 1
                or sample.get('active_flag_stability') != 'UNCHANGED'):
            retained_errors.append({'tick': ordinal, 'scope': 'torn_callback_boundary',
                                    'active_flag_at_sample_end': sample.get('active_flag_at_sample_end'),
                                    'active_flag_stability': sample.get('active_flag_stability')})
        round_counts[slot] += 1
        counts['active_rounds'] += 1
        require(sample.get('round_in_callback') == round_counts[slot]
                and round_counts[slot] <= policy['per_callback_round_cap']
                and counts['active_rounds'] <= policy['total_round_cap'], 'sampler_round_caps')
        for key in ('read_attempts', 'open_attempts', 'read_calls', 'read_bytes'):
            counts[key] += integer(sample[key], 'sampler_io_counter')
        require(sample['read_attempts'] <= policy['max_read_attempts']
                and sample['read_bytes'] <= policy['max_read_bytes'], 'sampler_read_caps')
        targets = sample['targets']
        require(type(targets) is list and len(targets) <= policy['target_cap']
                and len({t['role'] for t in targets}) == len(targets)
                and all(t['role'] in ('entry', 'native', 'tracer') for t in targets), 'sampler_target_cap_or_role')
        for error in sample.get('errors', []):
            retained_errors.append({'tick': ordinal, 'scope': 'proc_availability', 'raw': error})
        for target in targets:
            tasks = target.get('tasks', [])
            require(type(tasks) is list and len(tasks) <= policy['tid_cap'], 'sampler_tid_cap')
            require(len({t.get('tid') for t in tasks}) == len(tasks), 'sampler_duplicate_tid')
            if target['role'] == 'entry':
                require(target.get('pid') == entry_pid, 'sample_entry_pid_changed')
            if target['role'] == 'native':
                require(target.get('pid') == descriptor.get('native_pid'), 'sample_native_pid_changed')
            if slot in by_id:
                for task in tasks:
                    # Retain all endpoint TIDs; extra wait tokens exist only for
                    # caller/leader. No role is invented for other threads.
                    event = task_observation(task, target['role'], target['pid'], tick, by_id[slot])
                    event['active_flag_at_sample_end'] = sample.get('active_flag_at_sample_end')
                    event['active_flag_stability'] = sample.get('active_flag_stability')
                    event['target_stat_before'] = target.get('stat_before')
                    event['target_stat_after'] = target.get('stat_after')
                    event['target_status'] = target.get('status')
                    event['target_io'] = target.get('io')
                    events[slot].append(event)
    summary = sampler['summary']
    for key in ('wakeups', 'missed_intervals', 'inactive_ticks', 'active_ticks', 'active_rounds',
                'read_attempts', 'open_attempts', 'read_calls', 'read_bytes'):
        actual = summary['counts'].get(key, 0)
        integer(actual, 'sampler_actual_summary_counter')
        if actual != counts[key]:
            require(summary.get('status') == 'INCOMPLETE' and actual >= counts[key],
                    'sampler_summary_not_recomputed')
            retained_errors.append({'scope': 'started_vs_retained_counter', 'counter': key,
                                    'actual_summary': actual, 'recomputed_retained': counts[key]})
    retained_table = {str(i): round_counts[i] for i in range(19)}
    require(summary.get('retained_sample_rounds_per_callback') == retained_table,
            'sampler_per_callback_retained_round_summary')
    attempts = summary['rounds_per_callback']
    require(set(attempts) == set(retained_table), 'sampler_attempt_round_keys')
    for ordinal, descriptor in enumerate(descriptors):
        started_rounds = integer(attempts[str(ordinal)], 'sampler_started_round_count')
        require(round_counts[ordinal] <= started_rounds <= policy['per_callback_round_cap'],
                'sampler_retained_vs_started_rounds')
        require(descriptor.get('sample_rounds') == started_rounds
                and descriptor.get('retained_sample_rounds') == round_counts[ordinal],
                'final_descriptor_round_binding')
        if started_rounds != round_counts[ordinal]:
            retained_errors.append({'scope': 'started_round_not_retained', 'callback_id': ordinal,
                                    'started': started_rounds, 'retained': round_counts[ordinal]})
    encoded = sum(len(json.dumps(r, sort_keys=True, separators=(',', ':')).encode('utf-8')) + 1
                  for r in records)
    require(summary.get('encoded_record_bytes_with_separators') == encoded,
            'retained_encoded_byte_accounting')
    reserve = integer(summary['encoded_metadata_reserve_bytes'], 'encoded_metadata_reserve')
    require(encoded + reserve <= policy['encoded_bytes_cap'],
            'sampler_encoded_cap')
    # Breaching RSS or unavailable proc files makes observations incomplete; do
    # not drop their already observed records or rewrite original conclusions.
    complete = (summary.get('status') == 'COMPLETE' and summary.get('errors') == {}
                and summary['rss_peak_bytes'] <= policy['rss_limit_bytes'] and not retained_errors)
    return {
        'observability_complete': complete, 'actual_summary': summary,
        'recomputed_counts': dict(counts),
        'retained_sample_rounds_per_callback': retained_table,
        'started_rounds_per_callback': attempts,
        'callback_observations': [{'id': i, 'sample_rounds': round_counts[i],
            'zero_sample_meaning': 'NOT_OBSERVED_NOT_NO_WAIT', 'task_observations': events[i]} for i in range(19)],
        'retained_availability_or_control_errors': retained_errors,
        'limits': sampler.get('observation_limits'),
        'scope': 'Read sequences only; no wait-duration, continuous-state, SQLite-file or causal attribution',
    }


def ordinary_replay_binding(replay, plan, ordinal, report, before, member_refs, job):
    rows = [r for r in replay['slots'] if r.get('ordinal') == ordinal]
    require(len(rows) == 1, 'independent_replay_slot')
    row = rows[0]
    require(row.get('slot') == plan['cells'][ordinal]['slot']
            and row.get('result') == 'FULL_ORDINARY_REPLAYED_NOT_QUALIFIED'
            and row.get('ordinary_report_sha256') == member_refs['ordinary']['sha256']
            and row.get('before_network_report_sha256') == member_refs['ordinary_before_network']['sha256']
            and row.get('source_head') == report.get('source_commit') == before.get('source_commit')
            and row.get('source_head') == plan[
                'original_commit' if plan['cells'][ordinal]['ordinary_arm'] == 'A' else 'fast_commit'],
            'independent_replay_raw_source_member_binding')
    require(set(report.get('gates', {})) == GATES and row.get('gates') == report['gates']
            and row.get('original_status') == report.get('status')
            and row.get('network') == report.get('network')
            and row.get('network_observation') == report.get('network_observation')
            and row.get('legacy_profile_original') == report.get('capture_diagnostic'),
            'independent_replay_original_values')
    require(row.get('full_gate_and_status_replay_equal') is True
            and row.get('network_replay_equal') is True
            and row.get('full_previous_load_coverage') is True
            and row.get('evaluator_sha256') == plan['analysis']['accepted_evaluator_sha256']
            and row.get('observer_sha256') == plan['analysis']['accepted_observer_sha256'],
            'independent_full_unmasked_replay_incomplete')
    require(row.get('original_job_id') == job['job_id']
            and row.get('original_job_conclusion') == job['direct_original']['conclusion'],
            'independent_actual_job_verdict_binding')
    coverage = full_ordinary_coverage(report)
    ordinary_rows(report)
    return {'original_status': report['status'], 'original_gates': report['gates'],
            'independently_recomputed_gates': row['gates'], 'full_previous_load': coverage,
            'actual_original_job_conclusion': row['original_job_conclusion'],
            'legacy_profile_original': row.get('legacy_profile_original'),
            'scope': 'Unmasked original evaluator/network replay, including original FAIL; not qualification'}


def execution_sidecars(entry, observer, sampler, telemetry_ref, sampler_ref,
                       before, before_ref, source, plan_sha256, ordinal, parent_exit):
    require(entry.get('schema') == 'capture-process-entry-execution/v4'
            and observer.get('schema') == 'capture-process-observer-execution/v4', 'execution_sidecar_schema')
    require(entry.get('mode') == MODE and entry.get('regime') == REGIME
            and entry.get('head') == source and entry.get('plan_sha256') == plan_sha256
            and entry.get('cell', {}).get('ordinal') == ordinal,
            'entry_sidecar_identity')
    require(entry['telemetry']['sha256'] == telemetry_ref['sha256']
            and observer['sampler']['sha256'] == sampler_ref['sha256']
            and entry['ordinary_before_network']['sha256'] == before_ref['sha256'],
            'sidecar_exact_original_member_hashes')
    require(entry.get('original_status_before_network') == before.get('status')
            and entry.get('original_gates_before_network') == before.get('gates')
            and entry.get('original_cli_equivalent_returncode_before_network') ==
            (0 if before.get('status') == 'PASS' else 1), 'before_network_original_verdict')
    require(observer.get('plan_sha256') == plan_sha256 and observer.get('cell_ordinal') == ordinal
            and observer.get('observer_returncode') == parent_exit
            and observer.get('actual_entry_returncode') == entry.get('intended_entry_returncode'),
            'actual_entry_observer_exit_binding')
    require(observer.get('sampler_status') == sampler['summary']['status'], 'observer_sampler_status_binding')
    complete = (entry.get('diagnostic_complete') is True and entry.get('diagnostic_returncode') == 0
                and entry.get('primary_exception_type') is None and entry.get('cleanup_errors') == []
                and entry.get('control', {}).get('status') == 'COMPLETE'
                and entry['control'].get('published_slots') == list(range(19))
                and entry['control'].get('fd_closed_after_mapping') is True
                and entry['control'].get('mapping_closed') is True
                and observer.get('primary_exception_type') is None and observer.get('setup_errors') == [])
    return {'execution_observability_complete': complete,
            'original_status_before_network': entry['original_status_before_network'],
            'original_gates_before_network': entry['original_gates_before_network'],
            'original_cli_equivalent_returncode_before_network':
            entry['original_cli_equivalent_returncode_before_network'],
            'actual_entry_returncode': observer['actual_entry_returncode'],
            'actual_observer_parent_returncode': observer['observer_returncode'],
            'observer_process_cpu_ns': observer.get('observer_process_cpu_ns'),
            'observer_rss_peak_bytes': observer.get('rss_peak_bytes'),
            'observer_cost_scope': observer.get('cost_scope'),
            'original_exceptions_and_cleanup': {'primary_exception_type': entry.get('primary_exception_type'),
                'cleanup_errors': entry.get('cleanup_errors'), 'observer_primary': observer.get('primary_exception_type'),
                'observer_setup_errors': observer.get('setup_errors')}}


def telemetry_analysis(telemetry, report, before, plan, plan_sha256, ordinal, workflow_head, run_id):
    require(telemetry.get('schema') == TELEMETRY_SCHEMA and telemetry.get('mode') == MODE
            and telemetry.get('regime') == REGIME, 'telemetry_schema')
    identity, cell = telemetry['identity'], plan['cells'][ordinal]
    source = plan['original_commit'] if cell['ordinary_arm'] == 'A' else plan['fast_commit']
    require(identity.get('head') == source and identity.get('cell') == cell
            and identity.get('frozen_plan_sha256') == plan_sha256
            and identity.get('workflow_head') == workflow_head
            and identity.get('workflow_run_id') == str(run_id)
            and identity.get('workflow_run_attempt') == '1'
            and identity.get('runtime_coordinates') == plan['runtime_coordinates'],
            'telemetry_exact_source_execution_identity')
    require(telemetry.get('ordinary_report') == before, 'telemetry_original_before_report_not_verbatim')
    expected_sources = plan['phase_sources'][cell['ordinary_arm']]
    require(set(expected_sources) == set(PHASE_PARENT)
            and telemetry.get('phase_sources') == expected_sources, 'frozen_phase_source_inventory')
    original = ordinary_rows(report)
    require(ordinary_rows(before) == original, 'network_observer_modified_original_probe_rows')
    callbacks = telemetry.get('callbacks', [])
    require(type(callbacks) is list and len({r.get('id') for r in callbacks}) == len(callbacks),
            'duplicate_callback_identity')
    parsed, errors = [], []
    for expected in original:
        matches = [r for r in callbacks if r.get('id') == expected['id']]
        if len(matches) != 1:
            errors.append({'callback_id': expected['id'], 'code': 'selected_callback_missing'})
            continue
        try:
            parsed.append(callback_metrics(matches[0], expected, expected_sources))
        except Exception as error:
            errors.append({'callback_id': expected['id'], 'code': error_code(error)})
    bindings = telemetry.get('ordinary_actual_row_binding', [])
    for expected in original:
        matches = [r for r in bindings if r.get('callback_id') == expected['id']]
        path = '.'.join(next(g[2] for g in GROUPS if g[0] == expected['group']))
        if not (len(matches) == 1 and matches[0].get('path') == path
                and matches[0].get('index') == expected['original_row_index']
                and matches[0].get('equal') is True and matches[0].get('same_returned_object') is True):
            errors.append({'callback_id': expected['id'], 'code': 'returned_object_original_row_binding'})
    if len(parsed) == 19:
        first_ids = {r['store_instance_id'] for r in parsed[:14]}
        last_ids = {r['store_instance_id'] for r in parsed[14:]}
        if not (len(first_ids) == len(last_ids) == 1 and first_ids.isdisjoint(last_ids)
                and all(type(v) is str and v for v in first_ids | last_ids)):
            errors.append({'code': 'source_instance_store_relationship'})
    restoration = telemetry.get('restoration_events', [])
    if not any(r.get('reason') in ('after_last_official_callback', 'before_legacy_diagnose')
               and r.get('status') == 'ORIGINAL_BINDINGS_RESTORED' for r in restoration):
        errors.append({'code': 'core_hooks_not_restored_before_legacy_profile'})
    groups = []
    for group, count, _path, _number in GROUPS:
        rows = [r for r in parsed if r['group'] == group]
        if rows:
            groups.append({'group': group, 'observed_callbacks': len(rows), 'expected_callbacks': count,
                'original_capture_seconds': summarize([r['original_probe']['capture_seconds'] for r in rows]),
                'original_submit_seconds': summarize([r['original_probe']['capture_submit_seconds'] for r in rows]),
                'original_process_seconds': summarize([r['original_probe']['capture_process_seconds'] for r in rows]),
                'phase_wall_ns': {p: summarize([r['phase_metrics'][p]['wall_ns'] for r in rows]) for p in PHASE_PARENT},
                'phase_caller_cpu_ns': {p: summarize([r['phase_metrics'][p]['caller_thread_cpu_ns'] for r in rows]) for p in PHASE_PARENT},
                'net_parent_PROCESS_cpu_ns': summarize([r['phase_metrics']['process']['net_parent_process_cpu_ns'] for r in rows])})
    complete = (len(parsed) == len(callbacks) == 19 and not errors and telemetry.get('errors') == []
                and telemetry.get('status') == 'COMPLETE')
    return {'telemetry_observability_complete': complete, 'callbacks': parsed, 'groups': groups,
            'errors': errors, 'original_telemetry_errors': telemetry.get('errors'),
            'restoration_events': restoration, 'native_calls': telemetry.get('native_calls'),
            'registered_runtime_histories': telemetry.get('registered_runtime_histories'),
            'scope': 'All nineteen selected qualification callbacks; legacy six untouched outside C4'}


def error_code(error):
    return str(error) if isinstance(error, Unsupported) else type(error).__name__


def analyze_cell(plan, plan_sha256, manifest, audit, replay, ordinal, workflow_head, run_id):
    """Keep independent sections and original verdicts even if another is partial."""
    cell = {'ordinal': ordinal, 'slot': SLOTS[ordinal], 'result': 'PARTIAL_MECHANISM_DATA_NOT_QUALIFIED',
            'qualification': 'NOT_GRANTED', 'correction_support': 'NOT_GRANTED', 'errors': []}
    job = original_job(manifest, plan, ordinal, workflow_head, run_id)
    cell['actual_original_job'] = {'id': job['job_id'],
        'listed_status': job['listed_original']['status'], 'listed_conclusion': job['listed_original']['conclusion'],
        'direct_status': job['direct_original']['status'], 'direct_conclusion': job['direct_original']['conclusion'],
        'scope': 'Original run/job responses only; never derived from steps or logs'}
    audit_rows = [r for r in audit['slots'] if r.get('ordinal') == ordinal]
    require(len(audit_rows) == 1, 'independent_original_audit_slot')
    audited = audit_rows[0]
    require(audited.get('job_id') == job['job_id'] and audited.get('slot') == SLOTS[ordinal]
            and audited.get('metadata_and_bytes_verified') is True
            and audited.get('original_checkout_proof_verified') is True
            and audited.get('actual_job_conclusion') == job['direct_original']['conclusion'],
            'audited_original_slot_identity')
    names = set(plan['member_names'].values()) | set(plan['source_proof_members'].values())
    members = audited_members(audited, names)
    refs = {key: members[name] for key, name in plan['member_names'].items()}
    cell['original_member_refs'] = {key: {'sha256': value['sha256'], 'bytes': value['bytes']}
                                     for key, value in refs.items()}
    report = load_json(refs['ordinary']['raw'])
    before = load_json(refs['ordinary_before_network']['raw'])
    telemetry = load_json(refs['telemetry']['raw'])
    sampler = load_json(refs['sampler']['raw'])
    entry = load_json(refs['entry_execution']['raw'])
    observer = load_json(refs['observer_execution']['raw'])
    cell['original_ordinary_status'] = report.get('status')
    cell['original_ordinary_gates'] = report.get('gates')
    cell['original_before_network_status'] = before.get('status')
    cell['original_before_network_gates'] = before.get('gates')
    cell['legacy_profile_original'] = report.get('capture_diagnostic')

    def section(key, operation):
        try:
            cell[key] = operation()
        except Exception as error:
            cell['errors'].append({'section': key, 'code': error_code(error)})
        return cell.get(key)

    source = section('source_integrity', lambda: source_integrity(
        plan, plan_sha256, members, workflow_head, ordinal))
    section('independent_ordinary_replay', lambda: ordinary_replay_binding(
        replay, plan, ordinal, report, before, refs, job))
    parsed = section('process_observations', lambda: telemetry_analysis(
        telemetry, report, before, plan, plan_sha256, ordinal, workflow_head, run_id))
    section('recorder_calibration', lambda: calibration_summary(telemetry['calibration']))
    if source:
        section('execution_sidecars', lambda: execution_sidecars(
            entry, observer, sampler, refs['telemetry'], refs['sampler'], before,
            refs['ordinary_before_network'], source['source_head'], plan_sha256, ordinal,
            source['actual_observer_parent_exit']))
        if source['actual_canonical_network_exit'] != (0 if report.get('status') == 'PASS' else 1):
            cell['errors'].append({'section': 'source_integrity', 'code': 'original_network_exit_status_binding'})
    if parsed:
        section('sampler_observations', lambda: sampler_analysis(
            sampler, parsed['callbacks'], plan, plan_sha256, workflow_head, run_id))
    complete = (not cell['errors'] and parsed is not None
                and parsed['telemetry_observability_complete'] is True
                and cell.get('sampler_observations', {}).get('observability_complete') is True
                and cell.get('execution_sidecars', {}).get('execution_observability_complete') is True)
    if complete:
        cell['result'] = 'COMPLETE_MECHANISM_DATA_NOT_QUALIFIED'
    return cell


def cohort_summary(cells):
    require(type(cells) is list and len(cells) == 4
            and [c.get('ordinal') for c in cells] == list(range(4))
            and [c.get('slot') for c in cells] == list(SLOTS), 'four_ordered_mechanism_cells')
    # No all-jobs-success condition: original performance FAIL and complete
    # mechanism data can coexist. No correction/clean-preparation decision exists.
    complete = all(c.get('result') == 'COMPLETE_MECHANISM_DATA_NOT_QUALIFIED' for c in cells)
    return {'result': ('COMPLETE_MECHANISM_DATASET_NOT_QUALIFIED' if complete
                       else 'PARTIAL_MECHANISM_DATASET_NOT_QUALIFIED'),
            'selected_callback_count': sum(len(c.get('process_observations', {}).get('callbacks', [])) for c in cells),
            'expected_selected_callbacks': 76,
            'actual_job_conclusions': [{'ordinal': c['ordinal'], 'slot': c['slot'],
                'conclusion': c.get('actual_original_job', {}).get('direct_conclusion')}
                for c in cells],
            'qualification': 'NOT_GRANTED', 'correction_support': 'NOT_GRANTED',
            'scope': 'Observation completeness only; even four PASS jobs cannot prepare a Product correction'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'originals-manifest', 'original-audit', 'ordinary-replay', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('plan-sha256', 'manifest-sha256', 'original-audit-sha256',
                 'ordinary-replay-sha256', 'workflow-head'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--run-id', type=int, required=True)
    args = parser.parse_args()
    result = {'schema': 'independent-capture-process-mechanism-analysis/v4',
              'mode': MODE, 'regime': REGIME, 'authority': 'NONE_MECHANISM_ONLY',
              'qualification': 'NOT_GRANTED', 'correction_support': 'NOT_GRANTED',
              'result': 'PARTIAL_MECHANISM_DATASET_NOT_QUALIFIED', 'cells': [], 'errors': []}
    try:
        plan, plan_raw = pinned_json(args.plan, args.plan_sha256)
        validate_plan(plan)
        require(plan['analysis']['analyzer_sha256'] == digest(Path(__file__).read_bytes()), 'selected_analyzer_bytes')
        manifest, manifest_raw = pinned_json(args.originals_manifest, args.manifest_sha256)
        audit, _ = pinned_json(args.original_audit, args.original_audit_sha256)
        replay, _ = pinned_json(args.ordinary_replay, args.ordinary_replay_sha256)
        require(audit.get('schema') == 'capture-cost-C4-original-audit/v1'
                and audit.get('all_four_original_slots_verified') is True
                and audit.get('source_identities_verified') is True and audit.get('errors') == []
                and audit.get('helper_sha256') == plan['analysis']['original_auditor_sha256']
                and audit.get('workflow_head') == args.workflow_head
                and audit.get('run_id') == args.run_id and audit.get('run_attempt') == 1
                and audit.get('plan', {}).get('sha256') == digest(plan_raw)
                and audit.get('original_manifest', {}).get('sha256') == digest(manifest_raw),
                'independent_original_audit_source_execution_binding')
        require(replay.get('schema') == 'capture-process-independent-ordinary-replay/v4'
                and replay.get('helper_sha256') == plan['analysis']['ordinary_replayer_sha256']
                and replay.get('original_audit_sha256') == args.original_audit_sha256
                and replay.get('manifest_sha256') == args.manifest_sha256
                and replay.get('plan_sha256') == args.plan_sha256
                and replay.get('workflow_head') == args.workflow_head and replay.get('run_id') == args.run_id
                and replay.get('run_attempt') == 1
                and replay.get('qualification') == replay.get('correction_support') == 'NOT_GRANTED'
                and replay.get('network_probe', {}).get('result') == 'REFUSED',
                'independent_full_replay_identity')
        result['original_execution_conclusions'] = execution_identity(
            manifest, args.workflow_head, args.run_id, args.plan_sha256)
        result['selected_inputs'] = {'plan_sha256': args.plan_sha256, 'manifest_sha256': args.manifest_sha256,
            'original_audit_sha256': args.original_audit_sha256, 'ordinary_replay_sha256': args.ordinary_replay_sha256,
            'workflow_head': args.workflow_head, 'run_id': args.run_id, 'run_attempt': 1}
        for ordinal in range(4):
            try:
                cell = analyze_cell(plan, args.plan_sha256, manifest, audit, replay, ordinal,
                                    args.workflow_head, args.run_id)
            except Exception as error:
                cell = {'ordinal': ordinal, 'slot': SLOTS[ordinal],
                        'result': 'PARTIAL_MECHANISM_DATA_NOT_QUALIFIED',
                        'qualification': 'NOT_GRANTED', 'correction_support': 'NOT_GRANTED',
                        'errors': [{'section': 'original_cell_inputs', 'code': error_code(error)}]}
                jobs = [j for j in manifest.get('jobs', []) if j.get('ordinal') == ordinal]
                if len(jobs) == 1:
                    cell['actual_original_job'] = {'id': jobs[0].get('job_id'),
                        'listed_conclusion': jobs[0].get('listed_original', {}).get('conclusion'),
                        'direct_conclusion': jobs[0].get('direct_original', {}).get('conclusion')}
            result['cells'].append(cell)
        result.update(cohort_summary(result['cells']))
        result['independent_replay_errors'] = replay.get('errors')
        if replay.get('errors') != []:
            result['result'] = 'PARTIAL_MECHANISM_DATASET_NOT_QUALIFIED'
    except Exception as error:
        result['errors'].append({'section': 'independent_inputs', 'code': error_code(error)})
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'result': result['result'], 'errors': result['errors'],
                      'qualification': result['qualification'], 'correction_support': result['correction_support']}))
    return 0 if result['result'] == 'COMPLETE_MECHANISM_DATASET_NOT_QUALIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
