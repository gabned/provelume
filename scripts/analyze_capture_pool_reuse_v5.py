"""Passive C5 proof: full ordinary path for NEW shared-pool source.

Stdlib only. Root-selected offline use; no Product/ZIP/evaluator imports or runs.
Cross-host CPU/wall are descriptive. All four actual successes and unchanged 28
PASS maps, complete evidence and independent local proof are necessary together.
No diagnostic result grants qualification, release or publication authority.
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

PLAN_SCHEMA = 'capture-pool-reuse-full-ordinary-experiment/v5'
MODE = 'FULL_ORDINARY_SPARSE_POOL_REUSE_V5'
REGIME = 'FULL_ORDINARY_ALL19_TRANSACTION_POOL_REUSE_NOT_QUALIFICATION'
TELEMETRY_SCHEMA = 'capture-pool-reuse-temporary-telemetry/v5'
BASE = '7ec20fe0727a74a312235b53b52a5434707f4dc8'
ATOMIC_A = '28e9773770ce91ed2c7611b2df05a8feca47805543920f4159e3d4a068fde103'
ATOMIC_B = '3f7829c3b121a13f361c53bf861be4dc17f56b3941e914a9c392d041d467334c'
ENTRY_PATH = 'scripts/diagnose_capture_pool_reuse_v5.py'
CPU_SCOPE = 'WHOLE_PROBE_PARENT_PROCESS_INCLUDES_ORIGINAL_AND_SEARCH'
GROUPS = (
    ('s05_idle', 3, ('deterministic_idle',), 0),
    ('s05_busy', 3, ('deterministic_busy',), 0),
    ('s06_busy', 6, ('s06', 'deterministic_busy'), 0),
    ('s07_busy', 2, ('s07', 'samples'), 700),
    ('s08_idle', 3, ('s08', 'idle'), 800),
    ('s08_busy', 2, ('s08', 'performance'), 810),
)

SLOTS = ('A1', 'B1', 'B2', 'A2')

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

def parse_exit(raw):
    require(re.fullmatch(rb'-?[0-9]+\n', raw) is not None, 'original_exit_code_shape')
    return int(raw)

def error_code(error):
    return str(error) if isinstance(error, Unsupported) else type(error).__name__


def validate_plan(plan):
    require((plan.get('schema'), plan.get('status'), plan.get('mode'), plan.get('regime')) ==
            (PLAN_SCHEMA, 'FROZEN', MODE, REGIME), 'frozen_C5_plan')
    fixed = {'repository': 'gabned/provelume', 'repository_id': 1343746770,
             'workflow_runs': 1, 'run_attempt': 1, 'job_count': 4, 'job_seconds': 1200,
             'max_parallel': 2, 'callbacks_per_job': 19, 'callback_count_total': 76}
    require(all(plan.get(k) == v and type(plan[k]) is type(v) for k, v in fixed.items())
            and plan.get('fail_fast') is False and plan.get('base_commit') == BASE,
            'fixed_full_ordinary_cohort')
    require(not any(k in plan for k in ('observer', 'phase_sources', 'micro_budget_seconds',
                                      'work_budget_seconds', 'cleanup_budget_seconds')),
            'unselected_extra_instrumentation')
    require(plan.get('qualification') == 'NOT_GRANTED' and plan.get('slot_order') == list(SLOTS),
            'diagnostic_scope_and_order')
    require(plan.get('workflow_job_id') == 'measure', 'actual_workflow_job_key')
    require(plan.get('atomic_source_sha256') == {'A': ATOMIC_A, 'B': ATOMIC_B}, 'new_pool_B_only')
    require(set(plan.get('helper_sha256', {})) == {ENTRY_PATH}, 'one_sparse_entry')
    require(len(plan.get('ordinary_script_sha256', {})) == 8, 'eight_unchanged_ordinary_leaves')
    require(len(plan.get('cells', [])) == 4, 'four_cells')
    for i, cell in enumerate(plan['cells']):
        arm = ('A', 'B', 'B', 'A')[i]
        variant = 'original' if arm == 'A' else 'shared-pool'
        require(cell == {'ordinal': i, 'slot': SLOTS[i], 'ordinary_arm': arm,
                         'job_name': 'capture-cost-c5-' + SLOTS[i],
                         'artifact_name': 'capture-cost-c5-' + SLOTS[i] + '-' + variant},
                'fixed_cell_names')
    require(all(re.fullmatch('[0-9a-f]{40}', plan.get(k, '')) is not None
                for k in ('original_commit', 'fast_commit')), 'actual_A_B_commits')
    require(plan['source_parents'] == {'A': BASE, 'B': plan['original_commit']}
            and plan['original_commit'] != plan['fast_commit'], 'linear_new_source_graph')
    expected = []
    for group, count, path, start in GROUPS:
        for index in range(count):
            suffix = '.probe' if group in ('s07_busy', 's08_busy') else ''
            expected.append({'id': len(expected), 'group': group, 'original_row_index': index,
                             'number': start + index,
                             'report_path': '.'.join(path) + '.' + str(index) + suffix})
    require(plan.get('selected_callbacks') == expected, 'source_selected_nineteen_paths')
    require(plan['analysis']['accepted_source'] == '210512725f1826861585278214d21fd31093e123'
            and plan['analysis']['accepted_evaluator_sha256'] ==
            '754802fe6b2eb0b5bd67d6a962dcd9ed31179c9acd8e0526df6d176600410e22'
            and plan['analysis']['accepted_observer_sha256'] ==
            '9acb929c7f708a9590d9fe961744437882699daf38a9f46b2f6f14f428e624e9',
            'unchanged_accepted_unmasked_replay')


def original_source(plan, plan_sha, members, workflow_head, ordinal):
    names, cell = plan['source_proof_members'], plan['cells'][ordinal]
    arm = cell['ordinary_arm']
    head = plan['original_commit' if arm == 'A' else 'fast_commit']
    raw = lambda key: members[names[key]]['raw']
    require(raw('checkout_git').decode('ascii').splitlines() ==
            [head, plan['source_parents'][arm], plan['source_trees'][arm]], 'checkout_git_original')
    workflow = raw('workflow_git').decode('ascii').splitlines()
    require(len(workflow) == 3 and workflow[:2] == [workflow_head, plan['fast_commit']]
            and re.fullmatch('[0-9a-f]{40}', workflow[2]) is not None, 'workflow_git_original')
    require(digest(raw('frozen_plan')) == plan_sha and raw('source_status_after') == b'',
            'frozen_plan_clean_after')
    for key in ('ordinary_copy_exit', 'source_status_exit', 'source_head_exit', 'source_tree_exit'):
        require(raw(key) == b'0\n', 'copy_or_source_exit')
    require(raw('source_head_after').decode('ascii').strip() == head
            and raw('source_tree_after').decode('ascii').strip() == plan['source_trees'][arm],
            'source_changed_after_measurement')
    return {'source_head': head, 'source_tree': plan['source_trees'][arm],
            'actual_entry_exit': parse_exit(raw('entry_exit')),
            'actual_network_exit': parse_exit(raw('network_exit')),
            'proof_member_sha256': {key: members[name]['sha256'] for key, name in names.items()}}


def replay_binding(replay, plan, ordinal, report, before, refs, job):
    rows = [r for r in replay['slots'] if r.get('ordinal') == ordinal]
    require(len(rows) == 1, 'independent_replay_slot')
    row = rows[0]
    source = plan['original_commit' if plan['cells'][ordinal]['ordinary_arm'] == 'A' else 'fast_commit']
    require(row.get('slot') == SLOTS[ordinal] and row.get('result') == 'FULL_ORDINARY_REPLAYED_NOT_QUALIFIED'
            and row.get('ordinary_report_sha256') == refs['ordinary']['sha256']
            and row.get('before_network_report_sha256') == refs['ordinary_before_network']['sha256']
            and row.get('source_head') == report.get('source_commit') == before.get('source_commit') == source,
            'replay_exact_original_member_source')
    require(set(report.get('gates', {})) == GATES and row.get('gates') == report['gates']
            and row.get('original_status') == report.get('status')
            and row.get('network') == report.get('network')
            and row.get('network_observation') == report.get('network_observation')
            and row.get('legacy_profile_original') == report.get('capture_diagnostic'),
            'full_original_values_not_verbatim')
    require(row.get('full_gate_and_status_replay_equal') is True
            and row.get('network_replay_equal') is True and row.get('full_previous_load_coverage') is True
            and row.get('evaluator_sha256') == plan['analysis']['accepted_evaluator_sha256']
            and row.get('observer_sha256') == plan['analysis']['accepted_observer_sha256'],
            'unmasked_accepted_replay_not_complete')
    require(row.get('original_job_id') == job['job_id']
            and row.get('original_job_conclusion') == job['direct_original']['conclusion'],
            'replay_actual_job_binding')
    full_ordinary_coverage(report)
    ordinary_rows(report)
    return {'complete_previous_load': True, 'original_status': report['status'],
            'original_gates': report['gates'], 'recomputed_gates': row['gates'],
            'all_28_PASS': report['status'] == 'PASS' and all(v == 'PASS' for v in report['gates'].values()),
            'scope': 'Unmasked accepted evaluator/network; failures never projected or waived'}


def sparse_rows(telemetry, report, before, plan, plan_sha, ordinal, workflow_head, run_id):
    source = plan['original_commit' if plan['cells'][ordinal]['ordinary_arm'] == 'A' else 'fast_commit']
    require((telemetry.get('schema'), telemetry.get('mode'), telemetry.get('regime')) ==
            (TELEMETRY_SCHEMA, MODE, REGIME), 'C5_sparse_schema')
    identity = telemetry['identity']
    require(identity.get('head') == source and identity.get('cell') == plan['cells'][ordinal]
            and identity.get('frozen_plan_sha256') == plan_sha
            and identity.get('workflow_head') == workflow_head
            and identity.get('workflow_run_id') == str(run_id)
            and identity.get('workflow_run_attempt') == '1'
            and identity.get('workflow_job') == plan['workflow_job_id']
            and identity.get('runtime_coordinates') == plan['runtime_coordinates']
            and identity.get('atomic_source_sha256') == plan['atomic_source_sha256'][plan['cells'][ordinal]['ordinary_arm']],
            'sparse_actual_checkout_workflow_runtime_identity')
    require(telemetry.get('status') == 'COMPLETE' and telemetry.get('errors') == []
            and telemetry.get('error_recording_failed') is False and telemetry.get('bindings_restored') is True,
            'sparse_observation_incomplete')
    require(telemetry.get('cpu_scope') == CPU_SCOPE and telemetry.get('clock_read_attempts') == 76
            and telemetry.get('clock_order') == ['monotonic_ns', 'process_time_ns', 'ORIGINAL_PROBE',
                                                'process_time_ns', 'monotonic_ns']
            and telemetry.get('legacy_six_probes') == 'UNCHANGED_UNWRAPPED_PASSTHROUGH',
            'four_clock_scope_and_legacy_passthrough')
    require(set(telemetry['clock_resolutions']) == {'monotonic', 'process_time'}
            and all(type(v) in (int, float) and math.isfinite(v) and v > 0
                    for v in telemetry['clock_resolutions'].values()), 'clock_resolution')
    expected = ordinary_rows(report)
    require([r['probe'] for r in expected] == [r['probe'] for r in ordinary_rows(before)],
            'network_changed_original_probe_rows')
    rows = telemetry['callbacks']
    require(type(rows) is list and len(rows) == 19 and len(plan['selected_callbacks']) == 19,
            'exact_nineteen_callbacks')
    parsed, last_wall, last_cpu = [], None, None
    for i, (row, probe, selected) in enumerate(zip(rows, expected, plan['selected_callbacks'])):
        require({k: row.get(k) for k in selected} == selected
                and all(row.get(k) == probe[k] for k in ('id', 'group', 'original_row_index', 'number')),
                'selected_original_row_identity')
        require(row.get('original_row') == probe['probe'] and row.get('primary_exception_type') is None
                and row.get('clock_errors') == [], 'late_returned_dict_or_error')
        require(all(probe['probe'].get(k) is True for k in ('preserved', 'search_found', 'product_dispatch_blocked')),
                'Original_search_dispatch_control')
        w0, w1 = [integer(row[k], 'wall_endpoint') for k in ('wall_before_ns', 'wall_after_ns')]
        c0, c1 = [integer(row[k], 'parent_cpu_endpoint') for k in ('process_cpu_before_ns', 'process_cpu_after_ns')]
        require(w0 <= w1 and c0 <= c1 and row.get('elapsed_wall_ns') == w1 - w0
                and row.get('elapsed_parent_cpu_ns') == c1 - c0, 'raw_endpoint_delta')
        require((last_wall is None or last_wall <= w0) and (last_cpu is None or last_cpu <= c0),
                'sequential_probe_clock_order')
        last_wall, last_cpu = w1, c1
        parsed.append({'id': i, 'group': row['group'], 'report_path': row['report_path'],
                       'wall_before_ns': w0, 'wall_after_ns': w1, 'process_cpu_before_ns': c0,
                       'process_cpu_after_ns': c1, 'whole_probe_wall_ns': w1 - w0,
                       'whole_probe_parent_cpu_ns': c1 - c0, 'original_row': probe['probe']})
    return {'callbacks': parsed, 'groups': [{'group': name, 'callbacks': count,
                'whole_probe_wall_ns': summarize([r['whole_probe_wall_ns'] for r in parsed if r['group'] == name]),
                'whole_probe_parent_cpu_ns': summarize([r['whole_probe_parent_cpu_ns'] for r in parsed if r['group'] == name])}
                for name, count, _, _ in GROUPS],
            'scope': 'Descriptive cross-host observations include wrapper cost; no causal gain, subtraction or universal overhead bound'}


def entry_binding(entry, telemetry, report, before, refs, source, identity):
    require(entry.get('schema') == 'capture-pool-reuse-entry-execution/v5'
            and entry.get('mode') == MODE and entry.get('regime') == REGIME
            and entry.get('identity') == identity, 'entry_identity')
    require(entry.get('diagnostic_complete') is True and entry.get('diagnostic_returncode') == 0
            and entry.get('primary_exception_type') is None and entry.get('observation_setup_errors') == []
            and entry.get('cleanup_errors') == [], 'entry_observation_incomplete')
    require(entry.get('ordinary_before_network') == telemetry.get('ordinary_raw_before_network_observer')
            and entry['ordinary_before_network']['sha256'] == refs['ordinary_before_network']['sha256']
            and entry['ordinary_before_network']['bytes'] == refs['ordinary_before_network']['bytes'],
            'before_network_exact_bytes')
    require(entry.get('original_status_before_network') == before['status']
            and entry.get('original_gates_before_network') == before['gates']
            and entry.get('original_cli_equivalent_returncode_before_network') == (0 if before['status'] == 'PASS' else 1),
            'original_before_network_verdict')
    pending = (before['status'] == 'BLOCKED' and set(before['gates']) == GATES
               and before['gates']['network'] == 'NOT_RUN'
               and all(v == 'PASS' for k, v in before['gates'].items() if k != 'network'))
    passed = before['status'] == 'PASS' and set(before['gates']) == GATES and all(v == 'PASS' for v in before['gates'].values())
    intended = 0 if pending or passed else 1
    require(entry.get('intended_entry_returncode') == source['actual_entry_exit'] == intended
            and source['actual_network_exit'] == (0 if report['status'] == 'PASS' else 1),
            'actual_original_exit_bindings')
    return {'diagnostic_complete': True, 'actual_entry_exit': intended,
            'actual_network_exit': source['actual_network_exit'], 'before_network_neutral_pending': pending}


def local_binding(proof, comparison, plan, proof_sha, comparison_sha):
    pins = plan['local_dataset']
    require(pins['proof_sha256'] == proof_sha and pins['comparison_sha256'] == comparison_sha,
            'root_selected_actual_local_inputs')
    require(proof.get('schema') == 'independent-local-transaction-shared-pool-review/v1'
            and proof.get('result') == 'COMPLETE_LOCAL_ONLY'
            and proof.get('all_128_probe_semantics') is True and proof.get('all_32_expected_controls') is True
            and proof.get('source_restoration_resources_verified') is True
            and proof['inputs']['comparison']['sha256'] == comparison_sha,
            'independent_local_safety_evidence')
    require(all(proof['inputs'][key]['sha256'] == pins[pin] for key, pin in (
                ('safety', 'safety_sha256'), ('controller', 'controller_receipt_sha256'),
                ('receipt', 'execution_receipt_sha256'), ('wrapper', 'host_launch_sha256')))
            and comparison.get('plan_sha256') == pins['local_plan_sha256']
            and comparison.get('source_head') == BASE, 'local_selected_actual_provenance')
    require(proof['variant_source_sha256'] == comparison['variant_source_sha256'] ==
            plan['atomic_source_sha256'] == {'A': ATOMIC_A, 'B': ATOMIC_B}, 'exact_local_B_to_C5_B')
    require(comparison.get('status') == 'COMPLETE' and comparison.get('errors') == []
            and comparison.get('all_aliases_restored') is True and comparison.get('source_unchanged_after') is True
            and comparison.get('source_before') == comparison.get('source_after')
            and comparison.get('controls', {}).get('results') == 32
            and comparison['controls']['sha256'] == proof['inputs']['safety']['sha256']
            and comparison.get('cpu_scope') == 'WHOLE_PROBE_INCLUDE_ORIGINAL_SEARCH', 'local_complete_scope')
    slots = comparison['slots']
    require([(s['slot'], s['arm']) for s in slots] == list(zip(SLOTS, ('A', 'B', 'B', 'A')))
            and all(len(s['samples']) == 32 for s in slots) and len(comparison['calibration']) == 128,
            'local_fixed_128_and_calibration')
    vectors = []
    for slot in slots:
        require(slot.get('source_sha256') == plan['atomic_source_sha256'][slot['arm']],
                'actual_local_slot_source_mapping')
        numbers = []
        for i, row in enumerate(slot['samples']):
            require(row.get('ordinal') == i and row.get('outcome') == 'RETURNED'
                    and row['probe'].get('sample') == i
                    and all(row['probe'].get(k) is True for k in ('preserved', 'search_found', 'product_dispatch_blocked')),
                    'local_all_128_semantics')
            before, after = row['before']['process_cpu_ns'], row['after']['process_cpu_ns']
            integer(before, 'local_cpu_before'); integer(after, 'local_cpu_after')
            require(after >= before and row['process_cpu_ns'] == after - before, 'local_raw_CPU_delta')
            numbers.append(after - before)
        vectors.append(numbers)
    blanks = []
    for i, row in enumerate(comparison['calibration']):
        require(row['ordinal'] == i and row['outcome'] == 'RETURNED', 'local_all_empty_recipes')
        before, after = row['before']['process_cpu_ns'], row['after']['process_cpu_ns']
        require(type(before) is int and type(after) is int and 0 <= before <= after
                and row['process_cpu_ns'] == after - before, 'local_raw_calibration_CPU_delta')
        blanks.append(after - before)
    signed = [(vectors[0][i] + vectors[3][i] - vectors[1][i] - vectors[2][i]) / 2 for i in range(32)]
    resolution = comparison['clock_resolution_ns']['process_time']
    require(type(resolution) in (int, float) and math.isfinite(resolution) and resolution > 0,
            'local_CPU_clock_resolution')
    R = max(blanks) - min(blanks) + 2 * resolution
    mean, median = statistics.mean(signed), statistics.median(signed)
    reported = comparison['contrasts']['process_cpu_ns']
    require(reported['all_32'] == signed and reported['mean_D'] == mean and reported['median_D'] == median
            and reported['R'] == R, 'local_CPU_math_mismatch')
    return {'positive_prespecified_local_CPU': mean > R and median > R,
            'all_32_signed_CPU_ns': signed, 'mean_D_ns': mean, 'median_D_ns': median, 'R_ns': R,
            'all_32_safety_controls': True, 'exact_B_mapping': True,
            'scope': 'Local controlled cost only; whole-probe observation includes overhead; no hosted tail cause or qualification'}


def analyze_cell(plan, plan_sha, manifest, audit, replay, ordinal, workflow_head, run_id):
    cell = {'ordinal': ordinal, 'slot': SLOTS[ordinal], 'complete_evidence': False, 'errors': []}
    job = original_job(manifest, plan, ordinal, workflow_head, run_id)
    cell['actual_job'] = {'id': job['job_id'], 'listed': job['listed_original']['conclusion'],
                         'direct': job['direct_original']['conclusion']}
    checked = [r for r in audit['slots'] if r.get('ordinal') == ordinal]
    require(len(checked) == 1 and checked[0].get('job_id') == job['job_id']
            and checked[0].get('actual_job_conclusion') == job['direct_original']['conclusion']
            and checked[0].get('metadata_and_bytes_verified') is True
            and checked[0].get('original_checkout_proof_verified') is True, 'audited_original_slot')
    names = set(plan['member_names'].values()) | set(plan['source_proof_members'].values())
    members = audited_members(checked[0], names)
    refs = {k: members[v] for k, v in plan['member_names'].items()}
    report, before, telemetry, entry = [load_json(refs[key]['raw']) for key in
                                      ('ordinary', 'ordinary_before_network', 'telemetry', 'entry_execution')]
    cell['original_status'], cell['original_gates'] = report.get('status'), report.get('gates')
    cell['before_network_status'], cell['before_network_gates'] = before.get('status'), before.get('gates')
    cell['member_sha256'] = {k: v['sha256'] for k, v in refs.items()}
    operations = {
        'source': lambda: original_source(plan, plan_sha, members, workflow_head, ordinal),
        'ordinary': lambda: replay_binding(replay, plan, ordinal, report, before, refs, job),
        'observations': lambda: sparse_rows(telemetry, report, before, plan, plan_sha, ordinal, workflow_head, run_id),
    }
    for key, operation in operations.items():
        try: cell[key] = operation()
        except Exception as error: cell['errors'].append({'section': key, 'code': error_code(error)})
    if 'source' in cell:
        try: cell['entry'] = entry_binding(entry, telemetry, report, before, refs, cell['source'], telemetry['identity'])
        except Exception as error: cell['errors'].append({'section': 'entry', 'code': error_code(error)})
    cell['complete_evidence'] = not cell['errors'] and all(k in cell for k in ('source', 'ordinary', 'observations', 'entry'))
    cell['actual_success_and_28_PASS'] = (job['listed_original']['conclusion'] ==
        job['direct_original']['conclusion'] == 'success' and cell.get('ordinary', {}).get('all_28_PASS') is True)
    return cell


def cohort_decision(cells, run_conclusions, local):
    require(len(cells) == 4 and [c['ordinal'] for c in cells] == list(range(4)), 'four_decision_cells')
    complete = all(c.get('complete_evidence') is True for c in cells)
    all_four = all(c.get('actual_success_and_28_PASS') is True for c in cells)
    run_success = set(run_conclusions) == {'run_original', 'attempt_original'} and all(v == 'success' for v in run_conclusions.values())
    local_positive = local.get('positive_prespecified_local_CPU') is True and local.get('all_32_safety_controls') is True and local.get('exact_B_mapping') is True
    return {'complete_four_slot_evidence': complete, 'all_four_actual_success_and_28_PASS': all_four,
            'actual_run_and_attempt_success': run_success, 'independent_local_cost_and_safety': local_positive,
            'clean_candidate_preparation_supported': complete and all_four and run_success and local_positive,
            'qualification': 'NOT_GRANTED', 'correction_support': 'NOT_GRANTED', 'publication': 'NOT_GRANTED',
            'scope': 'Joint prerequisites only; a separate clean exact-head candidate still requires all ordinary/native/preflight/merge/post-merge gates'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'originals-manifest', 'original-audit', 'ordinary-replay',
                 'local-proof', 'local-comparison', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('plan-sha256', 'manifest-sha256', 'original-audit-sha256', 'ordinary-replay-sha256',
                 'local-proof-sha256', 'local-comparison-sha256', 'workflow-head'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--run-id', type=int, required=True)
    args = parser.parse_args()
    result = {'schema': 'independent-capture-pool-reuse-analysis/v5', 'mode': MODE, 'regime': REGIME,
              'result': 'PARTIAL_C5_EVIDENCE_NOT_QUALIFIED', 'cells': [], 'errors': [],
              'clean_candidate_preparation_supported': False, 'qualification': 'NOT_GRANTED',
              'correction_support': 'NOT_GRANTED', 'publication': 'NOT_GRANTED'}
    try:
        plan, plan_raw = pinned_json(args.plan, args.plan_sha256); validate_plan(plan)
        require(plan['analysis']['analyzer_sha256'] == digest(Path(__file__).read_bytes()), 'selected_passive_analyzer')
        manifest, manifest_raw = pinned_json(args.originals_manifest, args.manifest_sha256)
        audit, _ = pinned_json(args.original_audit, args.original_audit_sha256)
        replay, _ = pinned_json(args.ordinary_replay, args.ordinary_replay_sha256)
        proof, _ = pinned_json(args.local_proof, args.local_proof_sha256)
        comparison, _ = pinned_json(args.local_comparison, args.local_comparison_sha256)
        require(audit.get('schema') == 'capture-cost-C5-original-audit/v1' and audit.get('errors') == []
                and audit.get('all_four_original_slots_verified') is True and audit.get('source_identities_verified') is True
                and audit.get('helper_sha256') == plan['analysis']['original_auditor_sha256']
                and audit.get('workflow_head') == args.workflow_head and audit.get('run_id') == args.run_id
                and audit.get('run_attempt') == 1 and audit.get('plan', {}).get('sha256') == args.plan_sha256
                and audit.get('original_manifest', {}).get('sha256') == digest(manifest_raw), 'raw_audit_identity')
        require(replay.get('schema') == 'capture-pool-reuse-independent-ordinary-replay/v5'
                and replay.get('helper_sha256') == plan['analysis']['ordinary_replayer_sha256']
                and replay.get('original_audit_sha256') == args.original_audit_sha256
                and replay.get('manifest_sha256') == args.manifest_sha256 and replay.get('plan_sha256') == args.plan_sha256
                and replay.get('workflow_head') == args.workflow_head and replay.get('run_id') == args.run_id
                and replay.get('run_attempt') == 1 and replay.get('errors') == []
                and replay.get('network_probe', {}).get('result') == 'REFUSED', 'full_ordinary_replay_identity')
        result['local'] = local_binding(proof, comparison, plan, args.local_proof_sha256, args.local_comparison_sha256)
        result['actual_run_conclusions'] = execution_identity(manifest, args.workflow_head, args.run_id, args.plan_sha256)
        result['selected_inputs'] = {name: getattr(args, name) for name in (
            'plan_sha256', 'manifest_sha256', 'original_audit_sha256', 'ordinary_replay_sha256',
            'local_proof_sha256', 'local_comparison_sha256', 'workflow_head', 'run_id')}
        for ordinal in range(4):
            try: cell = analyze_cell(plan, args.plan_sha256, manifest, audit, replay, ordinal, args.workflow_head, args.run_id)
            except Exception as error:
                cell = {'ordinal': ordinal, 'slot': SLOTS[ordinal], 'complete_evidence': False,
                        'errors': [{'section': 'original_inputs', 'code': error_code(error)}]}
            result['cells'].append(cell)
        result.update(cohort_decision(result['cells'], result['actual_run_conclusions'], result['local']))
        if result['complete_four_slot_evidence']:
            result['result'] = 'COMPLETE_C5_COMPARISON_NOT_QUALIFIED'
    except Exception as error:
        result['errors'].append({'section': 'selected_inputs', 'code': error_code(error)})
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    print(json.dumps({k: result[k] for k in ('result', 'clean_candidate_preparation_supported', 'qualification', 'errors')}))
    return 0 if result['result'] == 'COMPLETE_C5_COMPARISON_NOT_QUALIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
