"""Governed job adapters to the existing S03 transport and S05 worker."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from .ai_context import task_payload
from .ai_contract import digest
from .ai_job_contract import check, integer
from .ai_models import ModelError
from .ai_provider import Failure, ProviderError, Transmission
from .ai_runtime_contract import CONFIGURATION, LOCK_SHA256, MODEL_ID, MODEL_SHA256, RUNTIME_ID


@dataclass(frozen=True)
class NativeConfig:
    runtime_lock: str = LOCK_SHA256
    model_sha256: str = MODEL_SHA256
    configuration: str = digest(CONFIGURATION)

    @property
    def fingerprint(self):
        check(self == NativeConfig(), "ai_native_configuration")
        return digest(asdict(self))


@dataclass(frozen=True, repr=False)
class JobOutcome:
    result: dict
    units: int | None = None
    micros: int | None = None
    usage_source: str = "UNKNOWN"

    def __post_init__(self):
        check(self.usage_source in {"UNKNOWN", "LOCAL", "PROVIDER"})
        for value in (self.units, self.micros):
            if value is not None:
                integer(value)


@dataclass(frozen=True)
class LocalFailure:
    """Only returned after the managed runtime confirms worker termination."""

    code: Failure


class ProviderJobAdapter:
    network_used = True

    def __init__(self, transport):
        self.transport = transport

    def exchange(self, current, *, cancel):
        from .ai_provider_http import Cancellation

        result = self.transport.exchange(current, cancel=Cancellation(probe=cancel))
        return JobOutcome({"kind": "context_check", "value": result.candidate.as_record()})


class NativeJobAdapter:
    network_used = False

    def __init__(self, runtime, model_store):
        self.runtime, self.model_store = runtime, model_store
        self.last_observation = None

    def exchange(self, current, *, cancel):
        # Reuse the runtime's reentrant ownership lock. A rejected concurrent
        # caller must never close another operation's worker while cleaning up.
        if not self.runtime._lock.acquire(blocking=False):
            raise ProviderError(Failure.CONFIG)
        try:
            return self._exchange(current, cancel=cancel)
        finally:
            self.runtime._lock.release()

    def _exchange(self, current, *, cancel):
        from .ai_runtime import native_selection

        entered = False
        started = time.monotonic()
        self.last_observation = None
        try:
            inputs = current()
            request, profile = inputs.prepare()
            check(
                type(inputs.config) is NativeConfig
                and profile.provider == RUNTIME_ID
                and profile.model == MODEL_ID
                and profile.revision == MODEL_SHA256,
                "ai_native_configuration",
            )
            check(
                request.limits.max_output_tokens >= CONFIGURATION["output_tokens"],
                "ai_native_limit",
            )
            payload = task_payload(inputs.preview, inputs.current["template"]).decode()
            check(len(payload.encode()) <= CONFIGURATION["input_bytes"], "ai_native_limit")
            selection = native_selection()
            prepared_at = time.monotonic()
            with self.model_store.use(selection) as model:
                admitted_at = time.monotonic()
                current().prepare()
                if cancel():
                    raise ProviderError(Failure.CANCELLED)
                entered = True
                inference_at = time.monotonic()
                value = self.runtime._infer(
                    model, selection, payload, cancel=cancel,
                    reuse_scope=digest({"instance": request.context.instance_id}),
                )
            self.last_observation = {
                "prepare_seconds": prepared_at - started,
                "model_admission_seconds": admitted_at - prepared_at,
                "revalidate_seconds": inference_at - admitted_at,
                "runtime_seconds": time.monotonic() - inference_at,
            }
            return JobOutcome(
                {"kind": "untrusted_text", "value": value["text"]},
                units=value["input_tokens"] + value["output_tokens"],
                micros=0,
                usage_source="LOCAL",
            )
        except ModelError as exc:
            self.runtime.close()
            code = Failure.CANCELLED if exc.code == "cancelled" else Failure.CONFIG
            if entered:
                return LocalFailure(code)
            raise ProviderError(
                code, Transmission.POSSIBLE if entered else Transmission.NOT_SENT
            ) from None
