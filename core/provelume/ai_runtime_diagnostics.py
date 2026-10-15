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
PUBLIC_INVENTORY_STAGES = {"pin-root", "read-manifest", "enumerate", "pin-directories",
                           "pin-file", "hash-file", "pin-executable", "grant-acl"}
PUBLIC_INVENTORY_BOUNDS = {
    "elapsed_ms": (0, 86400000), "stage_elapsed_ms": (0, 86400000),
    "budget_at_entry_ms": (-86400000, 60000), "budget_remaining_ms": (-86400000, 60000),
    "files_total": (0, 8192), "files_verified": (0, 8192),
    "bytes_hashed": (0, 512 * 1024**2),
    "grants_total": (0, 8194), "grants_completed": (0, 8194),
}


def public_inventory_observation(value):
    """Accept a complete content-free observation, never a partially trusted map."""
    if (type(value) is not dict
            or set(value) != {"stage", *PUBLIC_INVENTORY_BOUNDS}
            or type(value["stage"]) is not str
            or value["stage"] not in PUBLIC_INVENTORY_STAGES):
        return None
    for key, (low, high) in PUBLIC_INVENTORY_BOUNDS.items():
        if key in {"files_total", "grants_total"} and value[key] is None:
            continue
        if type(value[key]) is not int or not low <= value[key] <= high:
            return None
    if (value["stage_elapsed_ms"] > value["elapsed_ms"]
            or value["budget_remaining_ms"] > value["budget_at_entry_ms"]):
        return None
    if value["files_total"] is None:
        if (value["grants_total"] is not None or value["files_verified"]
                or value["bytes_hashed"] or value["grants_completed"]
                or value["stage"] not in {"pin-root", "read-manifest", "enumerate"}):
            return None
    elif (value["grants_total"] is None
          or not value["files_total"]
          or value["grants_total"] < value["files_total"] + 2
          or value["files_verified"] > value["files_total"]
          or value["grants_completed"] > value["grants_total"]
          or value["stage"] in {"pin-root", "read-manifest", "enumerate"}
          or ((value["grants_completed"] or
               value["stage"] in {"pin-executable", "grant-acl"})
              and value["files_verified"] != value["files_total"])):
        return None
    return dict(value)


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
    # Optional additive data: historical records retain their exact original shape.
    inventory = public_inventory_observation(observation.get("public_inventory"))
    if result["native_stage"] == "public-inventory" and inventory is not None:
        result["public_inventory"] = inventory
    return result


def valid_native_failure(value):
    return (type(value) is dict and type(value.get("schema_version")) is int
            and value == native_failure(
        value, code=value.get("model_code"), cancellation=value.get("cancellation_reason")))


def closed(value, choices):
    return value if type(value) is str and value in choices else None
