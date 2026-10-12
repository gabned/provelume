"""Bounded, content-free native failure observations; never execution authority."""

from __future__ import annotations

CAUSES = {"worker_exit", "worker_error", "reader_protocol", "cancelled", "deadline",
          "runtime_error", "unknown"}
PHASES = {"hardware-admission", "request_admission", "model_send", "model_load",
          "request_send", "generation", "native_prefill", "native_decode", "result_validation"}
WORKER_PHASES = {"initialization", "model_verification", "model_snapshot",
                 "runtime_verification", "native_load", "idle", "generation"}
NATIVE_STAGES = {"runtime-path", "profile-create", "loopback-exemptions", "public-inventory",
                 "private-model-handle", "job-create", "stdio-handles", "process-attributes",
                 "process-create", "process-verification", "process-resume", "worker-bootstrap"}
CANCELLATIONS = {"request_cancel", "request_deadline", "session_disabled",
                 "authority_changed", "scheduler_busy", "unknown"}


def native_failure(observation, *, code=None, cancellation=None):
    """Project only closed fields. Never retain exception text, paths or native stderr."""
    from .ai_models import ModelError

    observation = observation or {}
    try:
        model_code = ModelError(code).code if code is not None else None
    except (ValueError, TypeError):
        model_code = None
    cause = observation.get("cause", "unknown")
    if type(cause) is not str or cause not in CAUSES:
        cause = "unknown"
    if cause == "unknown" and model_code is not None:
        cause = {"cancelled": "cancelled", "timeout": "deadline"}.get(
            model_code, "runtime_error")
    result = {"schema_version": 1, "cause": cause, "model_code": model_code,
              "phase": closed(observation.get("phase"), PHASES),
              "worker_phase": closed(observation.get("worker_phase"), WORKER_PHASES),
              "native_stage": closed(observation.get("native_stage"), NATIVE_STAGES),
              "cancellation_reason": closed(cancellation, CANCELLATIONS),
              "parent_termination": (observation.get("parent_termination")
                                     if type(observation.get("parent_termination")) is bool
                                     else None)}
    for key in ("exit_code", "native_code"):
        value = observation.get(key)
        result[key] = value if type(value) is int and -(2**31) <= value < 2**32 else None
    return result


def valid_native_failure(value):
    return (type(value) is dict and type(value.get("schema_version")) is int
            and value == native_failure(
        value, code=value.get("model_code"), cancellation=value.get("cancellation_reason")))


def closed(value, choices):
    return value if type(value) is str and value in choices else None
