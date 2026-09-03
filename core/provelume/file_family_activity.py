from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response

from .file_family_profiles import FileFamilyContractError
from .paths import safe_instance_path
from .service import ProvelumeInstance

_JSON_OUTPUTS = {"profile.json", "preview.json"}


def _target_key(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _browser_model(model: Mapping[str, Any]) -> dict[str, Any]:
    selected = {**model, "profiles": []}
    for item in model["profiles"]:
        anchor_ids = {_target_key(anchor["target"]): anchor["id"] for anchor in item["anchors"]}
        record = item["record"]
        tables = []
        if record["profile_id"].endswith("csv-cell-v1"):
            source_tables = [{"sheet_name": "CSV", "sheet_index": None, **record["profile"]}]
        elif record["profile_id"].endswith("xlsx-sheet-cell-v1"):
            source_tables = record["profile"]["sheets"]
        else:
            source_tables = []
        for table in source_tables:
            rows = []
            for row in table["rows"]:
                cells = []
                for cell in row["cells"]:
                    target = {
                        "schema_version": 1,
                        "profile": "csv" if table["sheet_index"] is None else "xlsx",
                        **(
                            {}
                            if table["sheet_index"] is None
                            else {
                                "sheet_index": table["sheet_index"],
                                "sheet_name": table["sheet_name"],
                            }
                        ),
                        "row": cell["row"],
                        "column": cell["column"],
                        "coordinate": cell["coordinate"],
                    }
                    cells.append({**cell, "anchor_id": anchor_ids.get(_target_key(target))})
                rows.append({**row, "cells": cells})
            tables.append({**table, "rows": rows})
        members = []
        if record["profile_id"].endswith("zip-member-v1"):
            for member in record["profile"]["members"]:
                target = {
                    "schema_version": 1,
                    "member_index": member["member_index"],
                    "path": member["path"],
                    "sha256": member["sha256"],
                }
                members.append({**member, "anchor_id": anchor_ids.get(_target_key(target))})
        selected["profiles"].append({**item, "browser_tables": tables, "browser_members": members})
    return selected


def attach_file_family_routes(
    app: FastAPI,
    instance: ProvelumeInstance,
    templates: Any,
    context_factory: Callable[..., dict[str, Any]],
) -> None:
    @app.get("/api/v1/file-families/support")
    def api_file_family_support() -> dict[str, Any]:
        return instance.file_family_support()

    @app.get("/api/v1/file-families")
    def api_file_families(
        profile_id: str | None = None,
        version_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            return instance.file_family_read_model(
                profile_id=profile_id,
                version_id=version_id,
                limit=limit,
            )
        except FileFamilyContractError as exc:
            raise HTTPException(status_code=400, detail=exc.code) from exc

    @app.get("/api/v1/file-families/{representation_id}/outputs/{output_name}")
    def api_file_family_output(representation_id: str, output_name: str) -> Response:
        if output_name not in _JSON_OUTPUTS:
            raise HTTPException(status_code=404, detail="file-family output not found")
        selected = instance.get_file_family(representation_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="file-family representation not found")
        output = next(
            (
                item
                for item in selected["outputs"]
                if Path(str(item["storage_ref"])).name == output_name
                and item["media_type"] == "application/json"
            ),
            None,
        )
        if output is None:
            raise HTTPException(status_code=404, detail="file-family output not found")
        try:
            payload = safe_instance_path(instance.root, str(output["storage_ref"])).read_bytes()
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="file-family output invalid") from exc
        if (
            len(payload) != output["size_bytes"]
            or hashlib.sha256(payload).hexdigest() != output["sha256"]
        ):
            raise HTTPException(status_code=409, detail="file-family output invalid")
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/v1/file-families/{representation_id}/anchors/{anchor_id}")
    def api_file_family_anchor(representation_id: str, anchor_id: str) -> dict[str, Any]:
        selected = instance.get_file_family(representation_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="file-family representation not found")
        anchor = next((item for item in selected["anchors"] if item["id"] == anchor_id), None)
        if anchor is None:
            raise HTTPException(status_code=404, detail="file-family anchor not found")
        return anchor

    @app.get("/api/v1/file-families/{representation_id}")
    def api_file_family_profile(representation_id: str) -> dict[str, Any]:
        selected = instance.get_file_family(representation_id)
        if selected is None:
            raise HTTPException(status_code=404, detail="file-family representation not found")
        return selected

    @app.get("/file-families")
    def file_family_page(request: Request):
        model = _browser_model(instance.file_family_read_model(limit=250))
        return templates.TemplateResponse(
            request=request,
            name="file_families.html",
            context=context_factory(request, instance, model=model),
        )


__all__ = ["attach_file_family_routes"]
