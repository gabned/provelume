"""TEMP prospective sparse Capture plus full Atomic component cohort."""
from __future__ import annotations

import signal
import time


class MicroBudgetExpired(BaseException):
    pass


def run(recorder, *, root, store, runtime, initialise, measure_jobs, selection,
        model_id, order, seconds, work_seconds=540, cleanup_seconds=60,
        upload_reserve_seconds=90):
    if (order not in ('ABBA', 'BAAB') or type(seconds) is not int or seconds != 600
            or type(work_seconds) is not int or work_seconds != 540
            or type(cleanup_seconds) is not int or cleanup_seconds != 60
            or upload_reserve_seconds != 90):
        raise ValueError('fixed_sparse_cohort_order_or_budget_required')
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer != (0.0, 0.0):
        raise RuntimeError('existing_alarm_would_be_overridden')
    started = time.monotonic_ns()
    work_deadline, total_deadline = started + work_seconds * 10**9, started + seconds * 10**9
    recorder.micro_budget = {'total_seconds': seconds, 'work_seconds': work_seconds,
        'cleanup_seconds': cleanup_seconds, 'upload_reserve_seconds': upload_reserve_seconds,
        'started_monotonic_ns': started, 'work_deadline_monotonic_ns': work_deadline,
        'total_deadline_monotonic_ns': total_deadline}
    schedule = list(order * 3)
    recorder.schedules.update(appended_idle=schedule, appended_governed_busy=schedule)
    result = {'authority': 'NONE_DIAGNOSTIC_NOT_QUALIFICATION', 'order': order,
        'schedule': schedule, 'budget_seconds': seconds, 'started_ns': started,
        'passes': [], 'status': 'INCOMPLETE', 'limitations': [
            'Full Capture wall/CPU contrasts are descriptive, not a universal benefit claim.',
            'The subsequent Atomic batch is configured S06 context, not continuous native activity.',
            'Whole parent-process CPU can include other parent-process threads.',
            'Native identities and all zero-activity observations are retained.']}
    recorder.partial_appended = result
    previous_section, previous_context = recorder.section, recorder.section_context

    def expired(_signum, _frame):
        raise MicroBudgetExpired('fixed_sparse_micro_budget')

    def check_work():
        if time.monotonic_ns() >= work_deadline:
            raise MicroBudgetExpired('fixed_sparse_work_budget')

    alarm_handler_installed = False
    try:
        signal.signal(signal.SIGALRM, expired)
        alarm_handler_installed = True
        signal.setitimer(signal.ITIMER_REAL, work_seconds)
        # All extra observation/control work is inside the declared 600 seconds.
        recorder.calibrate()
        for pass_index in range(2):
            check_work()
            row = {'index': pass_index, 'idle': [], 'status': 'INCOMPLETE',
                   'started_ns': time.monotonic_ns()}
            result['passes'].append(row)
            recorder.section_context = {'micro_pass': pass_index}
            recorder.schedule_ordinals['appended_idle'] = pass_index * 6
            recorder.schedule_ordinals['appended_governed_busy'] = pass_index * 6
            try:
                recorder.prepare_component_fixture(pass_index, root / ('component-instance-' + str(pass_index)))
                instance = initialise(root / ('micro-instance-' + str(pass_index)))
                row['instance_id'] = instance.store.read_config()['instance']['id']
                recorder.section = 'unscored_seed'
                row['unscored_seed'] = recorder.probe('unscored_seed', 690 + pass_index, instance)
                for index in range(6):
                    check_work()
                    recorder.section = 'appended_idle'
                    row['idle'].append(recorder.probe('appended_idle', pass_index * 6 + index, instance))
                recorder.section = 'appended_governed_setup'
                check_work()
                evidence = store.self_test(model_id, selection, runtime, requested=True)
                row['initial_self_test'] = evidence.public_record()
                store.activate(model_id, selection, evidence, requested=True)
                recorder.section = 'appended_governed_busy'
                check_work()
                row['governed'] = measure_jobs(instance, store, runtime)
                if (row['governed'].get('status') == 'MEASURED'
                        and len(row['governed'].get('samples', [])) == 6
                        and len(row['governed'].get('cancellations', [])) == 2
                        and len(row['governed'].get('deterministic_busy', [])) == 6):
                    row['status'] = 'COMPLETE'
            except MicroBudgetExpired:
                raise
            except Exception as exc:
                row['exception_type'] = type(exc).__name__
            finally:
                for name, operation in (('runtime', runtime.close),
                                        ('component_fixture', lambda: recorder.dispose_component_fixture(pass_index))):
                    try:
                        operation()
                    except MicroBudgetExpired:
                        raise
                    except BaseException as exc:
                        row.setdefault('cleanup_errors', []).append({'phase': name, 'exception_type': type(exc).__name__})
                        recorder.error('pass_cleanup_failed')
                row['completed_ns'] = time.monotonic_ns()
        check_work()
        recorder.run_component_controls(root)
        check_work()
        components = [r.get('component_batch') for r in recorder.callbacks if r['group'] != 'unscored_seed']
        if (len(result['passes']) == 2 and all(p['status'] == 'COMPLETE' for p in result['passes'])
                and len(components) == 24 and all(c and c['status'] == 'COMPLETE' for c in components)
                and recorder.component_controls['status'] == 'COMPLETE' and not recorder.errors):
            result['status'] = 'COMPLETE'
    except MicroBudgetExpired:
        result['exception_type'] = 'MicroBudgetExpired'
        result['status'] = 'INCOMPLETE_WORK_BUDGET'
    except Exception as exc:
        result['exception_type'] = type(exc).__name__
        result['status'] = 'INCOMPLETE_WORK_ERROR'
    finally:
        recorder.micro_budget['work_completed_monotonic_ns'] = time.monotonic_ns()
        def timer_cleanup(label, operation, attempts=1):
            for attempt in range(attempts):
                try:
                    operation()
                    break
                except BaseException as exc:
                    result.setdefault('cleanup_errors', []).append({'phase': label,
                        'attempt': attempt + 1, 'exception_type': type(exc).__name__})
                    recorder.error('sparse_timer_cleanup_failed')
                    result['status'] = 'INCOMPLETE_CLEANUP'
        timer_cleanup('disable_work_timer', lambda: signal.setitimer(signal.ITIMER_REAL, 0))
        remaining = max(0, (total_deadline - time.monotonic_ns()) / 1e9)
        if remaining and alarm_handler_installed:
            timer_cleanup('arm_cleanup_timer', lambda: signal.setitimer(signal.ITIMER_REAL, remaining))
        for label, operation in (('component_fixtures', recorder.cleanup_component_fixtures),
                                 ('unscored_pools', recorder.drain_pools),
                                 ('runtime', runtime.close), ('bindings', recorder.uninstall)):
            try:
                operation()
            except BaseException as exc:
                result.setdefault('cleanup_errors', []).append({'phase': label, 'exception_type': type(exc).__name__})
                recorder.error('sparse_final_cleanup_failed')
                result['status'] = 'INCOMPLETE_CLEANUP'
        timer_cleanup('disable_cleanup_timer', lambda: signal.setitimer(signal.ITIMER_REAL, 0), attempts=2)
        timer_cleanup('restore_previous_handler', lambda: signal.signal(signal.SIGALRM, previous_handler), attempts=2)
        recorder.micro_budget['cleanup_completed_monotonic_ns'] = time.monotonic_ns()
        if (recorder.micro_budget['work_completed_monotonic_ns'] > work_deadline
                or recorder.micro_budget['cleanup_completed_monotonic_ns'] > total_deadline):
            result['status'] = 'INCOMPLETE_BUDGET'
        while len(result['passes']) < 2:
            result['passes'].append({'index': len(result['passes']), 'status': 'NOT_RUN_WORK_INCOMPLETE'})
        recorder.cohort_cleanup_completed = (result['status'] == 'COMPLETE'
            and not result.get('cleanup_errors')
            and recorder.micro_budget['cleanup_completed_monotonic_ns'] <= total_deadline)
        result['worker_pids'] = list(runtime.worker_history)
        recorder.section, recorder.section_context = previous_section, previous_context
        result['completed_ns'] = time.monotonic_ns()
    for group in ('appended_idle', 'appended_governed_busy'):
        actual = [r for r in recorder.callbacks if r['group'] == group]
        result[group + '_assigned_actual'] = [{'ordinal': i, 'arm': arm,
            'callback_id': next((r['id'] for r in actual if r['treatment_ordinal'] == i), None)}
            for i, arm in enumerate(schedule)]
    return result
