"""Closed internal worker phases; never render a request or backend exception."""

import json
import sys

SCHEMA = "provelume-ssh-agent-phase/v1"
PHASES = frozenset(
    {
        "REQUEST",
        "START_AGENT",
        "PUBLISH_READY",
        "SESSION",
        "STOP_AGENT",
        "PUBLISH_COMPLETION",
        "COMPLETE",
    }
)
CODES = frozenset(
    {
        "ssh_agent_request",
        "ssh_agent_containment",
        "ssh_agent_deadline",
        "ssh_agent_pipe",
        "ssh_identity",
        "ssh_key",
        "ssh_host_key",
    }
)
NATIVE_ERRORS = frozenset({5, 32, 33, 109, 233, 535, 995, 996, 997})


def emit(phase, error=None):
    value = {
        "schema": SCHEMA,
        "phase": phase if type(phase) is str and phase in PHASES else "OTHER",
    }
    if error is not None:
        code = getattr(error, "code", None)
        native = getattr(error, "winerror", None)
        value.update(
            error_code=code if type(code) is str and code in CODES else "OTHER",
            native_error=native if type(native) is int and native in NATIVE_ERRORS else "OTHER",
        )
    try:
        sys.stderr.write(json.dumps(value, sort_keys=True) + "\n")
        sys.stderr.flush()
    except (OSError, ValueError, AttributeError):
        pass


def observe(path):
    result = {"phase": "UNAVAILABLE", "error_code": "NONE", "native_error": "NONE"}
    try:
        with path.open("rb") as stream:
            data = stream.read(16385)
        if len(data) > 16384:
            return result
        for line in data.splitlines():
            value = json.loads(line)
            if type(value) is not dict or value.get("schema") != SCHEMA:
                continue
            phase = value.get("phase")
            code, native = value.get("error_code"), value.get("native_error")
            result = dict(
                phase=phase if type(phase) is str and phase in PHASES else "OTHER",
                error_code=code
                if type(code) is str and code in CODES
                else "OTHER"
                if "error_code" in value
                else "NONE",
                native_error=native
                if type(native) is int and native in NATIVE_ERRORS
                else "OTHER"
                if "native_error" in value
                else "NONE",
            )
    except (OSError, ValueError, TypeError):
        pass
    return result
