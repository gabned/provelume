"""Public synthetic S02 fixture. No adapter is shipped in the product package."""

import hashlib
from dataclasses import replace

from ai_gateway_fakes import DeterministicFakeAdapter, synthetic_case

from provelume.ai_context import (
    ContextLimits,
    OutputBytes,
    RedactionConfig,
    Selection,
    SourceSnapshot,
    TaskTemplate,
    VersionIdentity,
    prepared_request,
    validate_candidate,
)
from provelume.ai_contract import AiContractError, Limits, Outcome, digest
from provelume.ai_gateway import explain, receipt, revalidate
from provelume.representations import build_representation_bundle, canonical_json_bytes


def context_case(text="Contact ada@example.test, code PRIVATE.\fSecond page.", *, asset=False):
    request, gateway = synthetic_case()
    request_limits = Limits(16384, 2048, 2, 10)
    gateway["profiles"] = tuple(replace(p, limits=request_limits) for p in gateway["profiles"])
    gateway["evidence"] = tuple(
        replace(e, profile_fingerprint=p.fingerprint)
        for e, p in zip(gateway["evidence"], gateway["profiles"], strict=True)
    )
    gateway["rules"] = (replace(gateway["rules"][0], limits=request_limits), *gateway["rules"][1:])
    version = VersionIdentity(
        request.context.instance_id,
        request.context.document_id,
        request.context.version_id,
        "synthetic_original",
        digest("synthetic original"),
        100000,
    )
    data = text.encode("utf-8")
    output = {
        "id": "rout_" + hashlib.sha256(data).hexdigest(),
        "media_type": "text/plain",
        "storage_ref": "state/derived/synthetic/text.txt",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }
    outputs = [output]
    if asset:
        outputs.append(
            {
                "id": "rout_" + "f" * 64,
                "media_type": "image/png",
                "storage_ref": "state/derived/synthetic/z.png",
                "sha256": "f" * 64,
                "size_bytes": 100,
            }
        )
    bundle = build_representation_bundle(
        version={
            "id": version.version_id,
            "original_id": version.original_id,
            "original_sha256": version.original_sha256,
            "original_size_bytes": version.original_size_bytes,
        },
        recipe_id="synthetic-text-pages",
        recipe_version="1",
        recipe_settings={},
        outputs=outputs,
        implementation={
            "component": "provelume.core",
            "component_version": "0.11.0",
            "adapter": "synthetic-text",
            "adapter_version": "1",
            "settings": {},
        },
        anchor_targets=tuple({"kind": "page", "page": p + 1} for p in range(len(text.split("\f")))),
        created_at="2026-10-03T00:00:00+00:00",
    )
    rid = bundle["representation_id"]
    source = SourceSnapshot(
        version, (canonical_json_bytes(bundle),), (OutputBytes(rid, output["id"], data),)
    )
    selections, offset = [], 0
    for page, anchor in zip(text.split("\f"), bundle["anchors"], strict=True):
        if page:
            selections.append(
                Selection(
                    version,
                    rid,
                    digest(bundle),
                    output["id"],
                    anchor["id"],
                    offset,
                    offset + len(page),
                )
            )
        offset += len(page) + 1
    current = dict(
        limits=ContextLimits(),
        request_limits=request_limits,
        template=TaskTemplate("context-check-partial-v1", True),
        redaction=RedactionConfig(literals=("PRIVATE",)),
        snapshot=gateway["snapshot"],
        rules=gateway["rules"],
    )
    return source, tuple(selections), current, gateway


def simulate_context(plan, preview, source, selections, *, adapter, gateway, **current):
    """Rebuild context and S01 plan before calling even the fake."""
    try:
        request, snapshot = prepared_request(preview, source, selections, **current)
    except AiContractError:
        return None
    fresh_gateway = {**gateway, "snapshot": snapshot, "rules": current["rules"]}
    fresh = revalidate(plan, request, **fresh_gateway)
    if fresh.outcome != Outcome.PLANNED:
        return receipt(fresh)
    return adapter.simulate(fresh, request, **fresh_gateway)


def context_plan(preview, source, selections, current, gateway):
    request, snapshot = prepared_request(preview, source, selections, **current)
    return explain(request, **{**gateway, "snapshot": snapshot, "rules": current["rules"]})


def candidate(preview, **changes):
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "preview_fingerprint": preview.fingerprint,
            "status": "checked",
            "references": [0],
            **changes,
        }
    )


class ContextFake(DeterministicFakeAdapter):
    def checked(self, preview, source, selections, **current):
        return validate_candidate(candidate(preview), preview, source, selections, **current)
