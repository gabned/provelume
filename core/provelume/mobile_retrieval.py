"""Bounded inert Knowledge reads on the existing explicitly configured Capture listener."""

from __future__ import annotations

import hashlib
import re

from fastapi import HTTPException, Request
from fastapi.responses import Response

from .capture_http import capture_json
from .capture_journal import CaptureJournal, CaptureJournalError, _read
from .index import index_status, search_index
from .paths import safe_instance_path
from .retention_model import effective_dispositions

MAX_RESULTS = 20
MAX_ORIGINAL = 25 * 1024 * 1024
MAX_INVENTORY = 10000
_DOCUMENT = re.compile(r"doc_[0-9a-f]{32}\Z")


class MobileRetrieval:
    def __init__(self, store, authorize):
        self.store, self.authorize = store, authorize

    def scope(self):
        CaptureJournal(self.store)._read_ready()
        return self.authorize()

    def documents(self, scope):
        rows = self.store.list_canonical("documents")
        if len(rows) > MAX_INVENTORY:
            raise CaptureJournalError("Mobile inventory limit; use local Knowledge")
        dispositions = effective_dispositions(self.store)
        return {
            d["id"]: d
            for d in rows
            if d["source_id"] in scope["source_ids"]
            and dispositions[d["id"]]["status"] == "active"
            and dispositions[d["id"]]["projected"]
        }

    @staticmethod
    def summary(document):
        return {
            k: document.get(k)
            for k in ("id", "title", "source_id", "current_version_id", "created_at")
        }

    def recent(self):
        scope = self.scope()
        documents = self.documents(scope)
        acquisitions = self.store.list_canonical("acquisitions")
        if len(acquisitions) > MAX_INVENTORY:
            raise CaptureJournalError("Mobile acquisition inventory limit")
        seen, rows = set(), []
        for row in sorted(acquisitions, key=lambda r: (r["observed_at"], r["id"]), reverse=True):
            identity = row["document_id"]
            if identity in documents and identity not in seen:
                seen.add(identity)
                rows.append(
                    {**self.summary(documents[identity]), "observed_at": row["observed_at"]}
                )
                if len(rows) == MAX_RESULTS:
                    break
        self.scope()
        return {"items": rows, "limit": MAX_RESULTS, "grant": scope}

    def search(self, query):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 128:
            raise HTTPException(400, "Enter a search of 1–128 characters")
        scope = self.scope()
        documents = self.documents(scope)
        if index_status(self.store) != "ready":
            raise HTTPException(409, "Search unavailable; recover the existing index locally")
        rows = []
        for source in scope["source_ids"]:
            rows.extend(
                r
                for r in search_index(self.store, query, source_id=source, limit=MAX_RESULTS)
                if r["document_id"] in documents
                and r["version_id"] == documents[r["document_id"]]["current_version_id"]
            )
        rows.sort(key=lambda r: (r["acquired_at"], r["document_id"]), reverse=True)
        self.scope()
        return {
            "items": [
                {**self.summary(documents[r["document_id"]]), "snippet": str(r["snippet"])[:1024]}
                for r in rows[:MAX_RESULTS]
            ],
            "limit": MAX_RESULTS,
            "ordering": "recent-first within bounded Source matches",
        }

    def document(self, identity, scope):
        if not _DOCUMENT.fullmatch(identity):
            raise HTTPException(404, "Document unavailable")
        document = self.documents(scope).get(identity)
        if document is None:
            raise HTTPException(404, "Document unavailable")
        return document

    def version(self, identity, version_id, scope):
        document = self.document(identity, scope)
        if not re.fullmatch(r"ver_[0-9a-f]{32}", version_id):
            raise HTTPException(404, "Version unavailable")
        version = self.store.read_canonical("versions", version_id)
        if version is None or version.get("document_id") != document["id"]:
            raise HTTPException(404, "Version unavailable")
        return version

    def detail(self, identity):
        scope = self.scope()
        document = self.document(identity, scope)
        versions = self.store.versions_for_document(identity)
        if len(versions) > 128:
            raise HTTPException(409, "Version inventory exceeds mobile limit; inspect locally")
        acquisitions = [
            a for a in self.store.list_canonical("acquisitions") if a["document_id"] == identity
        ]
        if len(acquisitions) > 128:
            raise HTTPException(409, "Provenance exceeds mobile limit; inspect locally")
        source = self.store.read_canonical("sources", document["source_id"])
        if source is None:
            raise HTTPException(409, "Source provenance unavailable; inspect locally")
        identities = {identity, document["source_id"]}
        identities.update(v["id"] for v in versions)
        identities.update(v["original_id"] for v in versions)
        identities.update(a["id"] for a in acquisitions)
        edges = self.store.list_canonical("provenance")
        if len(edges) > MAX_INVENTORY:
            raise HTTPException(409, "Provenance inventory exceeds mobile limit; inspect locally")
        edges = [e for e in edges if e["from_id"] in identities and e["to_id"] in identities]
        if len(edges) > 768:
            raise HTTPException(409, "Provenance exceeds mobile limit; inspect locally")
        result = {
            "document": self.summary(document),
            "source": {k: source.get(k) for k in ("id", "kind", "name", "created_at")},
            "versions": [
                {
                    k: v.get(k)
                    for k in (
                        "id",
                        "original_id",
                        "content_hash",
                        "size_bytes",
                        "media_type",
                        "sequence",
                        "acquired_at",
                    )
                }
                for v in reversed(versions)
            ],
            "acquisitions": [
                {
                    k: a.get(k)
                    for k in (
                        "id",
                        "version_id",
                        "observed_at",
                        "outcome",
                        "source_id",
                        "original_id",
                        "acquisition_kind",
                        "content_hash",
                        "derived_status",
                    )
                }
                for a in acquisitions
            ],
            "preview": "metadata-only",
            "provenance": edges,
            "original_download": "explicit-authenticated-attachment",
            "persistent_cache": False,
            "grant": scope,
        }
        self.scope()
        return result

    def original(self, identity, version_id):
        scope = self.scope()
        version = self.version(identity, version_id, scope)
        original = self.store.read_canonical("originals", version["original_id"])
        if original is None:
            raise HTTPException(404, "Original unavailable")
        size = original.get("size_bytes")
        if type(size) is not int or not 0 <= size <= MAX_ORIGINAL:
            raise HTTPException(
                413, "Original exceeds 25 MiB mobile download limit; use local Knowledge"
            )
        try:
            path = safe_instance_path(self.store.paths.root, original["storage_ref"])
            data = _read(path, MAX_ORIGINAL)
        except (OSError, ValueError) as exc:
            raise HTTPException(409, "Original unavailable; recover locally") from exc
        digest = hashlib.sha256(data).hexdigest()
        if (
            digest != original["sha256"]
            or digest != version["content_hash"]
            or len(data) != size
            or len(data) != version["size_bytes"]
        ):
            raise HTTPException(409, "Original failed integrity verification; recover locally")
        self.scope()
        return Response(
            data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="original.bin"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )


def attach_mobile_retrieval(app, store, authority, boundary, owner, paired_origin, attempts):
    def access(request):
        boundary(request, mutation=request.method == "POST")
        if paired_origin is None:
            owner(request)
            return {
                "source_ids": [s["id"] for s in store.list_canonical("sources")],
                "expires_at": "local session",
                "network": "loopback owner",
            }
        token = request.headers.get("authorization", "")
        if not token.startswith("Bearer "):
            raise HTTPException(
                403, "Separate retrieval grant required; Capture pairing is insufficient"
            )
        try:
            return authority.authorize_retrieval(
                request.headers.get("x-retrieval-device", ""), token[7:], origin=paired_origin
            )
        except PermissionError as exc:
            raise HTTPException(
                403, "Retrieval grant expired or revoked; ask the local owner"
            ) from exc

    def reader(request):
        attempts.check(request)
        access(request)
        return MobileRetrieval(store, lambda: access(request))

    @app.get("/capture/knowledge/recent")
    def recent(request: Request):
        return reader(request).recent()

    @app.post("/capture/knowledge/search")
    async def search(request: Request):
        selected = reader(request)
        data = await capture_json(request, {"query"})
        return selected.search(data["query"])

    @app.get("/capture/knowledge/documents/{document_id}")
    def detail(document_id: str, request: Request):
        return reader(request).detail(document_id)

    @app.post("/capture/knowledge/documents/{document_id}/versions/{version_id}/original")
    async def download(document_id: str, version_id: str, request: Request):
        selected = reader(request)
        await capture_json(request, set())
        request.state.capture_original_attachment = True
        return selected.original(document_id, version_id)

    if paired_origin is None:

        @app.post("/capture/admin/retrieval/grant")
        async def grant(request: Request):
            owner(request)
            value = await capture_json(request, {"device_id", "source_ids", "seconds"})
            return authority.grant_retrieval(
                value["device_id"],
                value["source_ids"],
                value["seconds"],
                authorize_owner=lambda: owner(request),
            )

        @app.post("/capture/admin/retrieval/revoke")
        async def revoke(request: Request):
            owner(request)
            value = await capture_json(request, {"device_id"})
            return authority.revoke_retrieval(
                value["device_id"], authorize_owner=lambda: owner(request)
            )
