"""TEMP appended fixed Capture cohort. Draft: requires reviewed frozen plan."""
from __future__ import annotations
import signal
import time


class MicroBudgetExpired(BaseException):
    pass


def run(recorder, *, root, store, runtime, initialise, measure_jobs, selection,
        model_id, order, seconds):
    """Two fresh instances, each seed + six idle + unchanged six-job S06."""
    if order not in ("ABBA", "BAAB") or type(seconds) is not int or not 1 <= seconds <= 600:
        raise ValueError("unfrozen_micro_order_or_budget")
    schedule = list(order * 3)
    recorder.schedules["appended_idle"] = schedule
    recorder.schedules["appended_governed_busy"] = schedule
    result = {"authority": "NONE_DIAGNOSTIC_NOT_QUALIFICATION", "order": order,
              "schedule": schedule, "budget_seconds": seconds,
              "started_ns": time.monotonic_ns(), "passes": [],
              "status": "INCOMPLETE", "limitations": [
                  "Fresh instances are matched mechanism fixtures, not the accumulated ordinary instance.",
                  "The accepted S06 callback remains after-first; parent phase is a last observation.",
                  "Fresh authority/context identities may change exact native payloads across conditions.",
                  "No equal-token or byte-parity claim is inferred; actual native hashes are retained."]}
    recorder.partial_appended = result
    deadline = time.monotonic() + seconds
    old_section, old_context = recorder.section, recorder.section_context
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer != (0.0, 0.0):
        raise RuntimeError("existing_alarm_would_be_overridden")

    def expired(_signum, _frame):
        raise MicroBudgetExpired("fixed_microcohort_wall_budget")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        for pass_index in range(2):
            if time.monotonic() >= deadline:
                raise MicroBudgetExpired("fixed_microcohort_wall_budget")
            row = {"index": pass_index, "idle": [], "started_ns": time.monotonic_ns(),
                   "status": "INCOMPLETE"}
            result["passes"].append(row)
            recorder.section_context = {"micro_pass": pass_index}
            # Exact logical ordinals are allocated prospectively. An interrupted
            # earlier pass cannot shift treatment labels for a later pass.
            recorder.schedule_ordinals["appended_idle"] = pass_index * 6
            recorder.schedule_ordinals["appended_governed_busy"] = pass_index * 6
            try:
                instance = initialise(root / ("micro-instance-" + str(pass_index)))
                row["instance_id"] = instance.store.read_config()["instance"]["id"]
                recorder.section = "unscored_seed"
                row["unscored_seed"] = recorder.probe("unscored_seed", 690 + pass_index, instance)
                for index in range(6):
                    if time.monotonic() >= deadline:
                        raise MicroBudgetExpired("fixed_microcohort_wall_budget")
                    recorder.section = "appended_idle"
                    row["idle"].append(recorder.probe("appended_idle", pass_index * 6 + index, instance))
                recorder.section = "appended_governed_setup"
                evidence = store.self_test(model_id, selection, runtime, requested=True)
                row["initial_self_test"] = evidence.public_record()
                store.activate(model_id, selection, evidence, requested=True)
                recorder.section = "appended_governed_busy"
                if time.monotonic() >= deadline:
                    raise MicroBudgetExpired("fixed_microcohort_wall_budget")
                row["governed"] = measure_jobs(instance, store, runtime)
                if row["governed"].get("status") == "MEASURED":
                    row["status"] = "COMPLETE"
            except MicroBudgetExpired:
                raise
            except Exception as exc:
                row["exception_type"] = type(exc).__name__
                # This is not a retry: the other predeclared fresh-instance pass
                # keeps its original ordinals and still executes if budget allows.
            finally:
                try:
                    runtime.close()
                except BaseException as exc:
                    row.setdefault("cleanup_errors", []).append(type(exc).__name__)
                    recorder.error("micro_runtime_cleanup_failed")
                row["completed_ns"] = time.monotonic_ns()
        if (len(result["passes"]) == 2
                and all(row["status"] == "COMPLETE" and len(row["idle"]) == 6
                        and len(row["governed"].get("deterministic_busy", [])) == 6
                        for row in result["passes"])):
            result["status"] = "COMPLETE"
    except MicroBudgetExpired:
        result["exception_type"] = "MicroBudgetExpired"
        # Keep every declared missing cell explicit, never pick successful cells.
        while len(result["passes"]) < 2:
            result["passes"].append({"index": len(result["passes"]),
                                      "status": "NOT_RUN_BUDGET_EXHAUSTED"})
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        try:
            recorder.drain_pools()
        except BaseException as exc:
            result.setdefault("cleanup_errors", []).append(type(exc).__name__)
            recorder.error("micro_pool_cleanup_failed")
        try:
            runtime.close()
        except BaseException as exc:
            result.setdefault("cleanup_errors", []).append(type(exc).__name__)
            recorder.error("micro_runtime_cleanup_failed")
        result["worker_pids"] = list(runtime.worker_history)
        recorder.section, recorder.section_context = old_section, old_context
        result["completed_ns"] = time.monotonic_ns()
    for group in ("appended_idle", "appended_governed_busy"):
        actual = [r for r in recorder.callbacks if r["group"] == group]
        result[group + "_assigned_actual"] = [
            {"ordinal": i, "arm": arm,
             "callback_id": next((r["id"] for r in actual if r["treatment_ordinal"] == i), None)}
            for i, arm in enumerate(schedule)]
    return result
