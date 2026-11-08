"""Producer page generations: durable continuation, exact membership, no false completeness."""

from __future__ import annotations

import re
from uuid import uuid4

from .atomic_commit import PRODUCTIVITY_INTAKE_TRANSACTION_PROFILE, AtomicInstanceCommit
from .index_evidence import publish_once
from .instance_lifecycle import InstanceLifecycleManager
from .productivity_connectors import ROOT
from .productivity_contract import fingerprint, require
from .productivity_intake import _bytes, _identifier
from .review_decisions import checked_path, read_json
from .storage import utc_now

MAX_GENERATION_DEPTH = 32


def _generation(value):
    require(
        type(value) is str and re.fullmatch(r"pgen_[0-9a-f]{32}", value) is not None, "integrity"
    )
    return value


class ProductivityGenerations:
    """Caller owns the Instance lifecycle and final policy guard for mutations."""

    def __init__(self, store, source_id):
        self.store, self.source_id = store, source_id
        self.root = f"{ROOT}/{source_id}"

    def prepare(self, binding, page_size, *, allow_delta=True):
        progress = read_json(self.store, self.root + "/page-progress.json")
        if progress and progress.get("binding") == binding and progress.get("status") == "active":
            _generation(progress["generation_id"])
            require(
                progress["source_id"] == self.source_id and progress["page_size"] <= page_size,
                "limit",
            )
            return progress
        latest = read_json(self.store, self.root + "/sync.json")
        delta = bool(
            allow_delta and latest
            and latest.get("schema") == "productivity-generation/v1"
            and latest.get("binding") == binding
            and latest.get("depth", MAX_GENERATION_DEPTH) < MAX_GENERATION_DEPTH
        )
        return {
            "schema": "productivity-page-progress/v1",
            "source_id": self.source_id,
            "generation_id": "pgen_" + uuid4().hex,
            "binding": binding,
            "mode": "delta" if delta else "full",
            "status": "active",
            "parent_generation": latest["generation_id"] if delta else None,
            "depth": latest["depth"] + 1 if delta else 0,
            "base_checkpoint": latest["checkpoint"] if delta else None,
            "page_token": None,
            "page_size": page_size,
            "pages": 0,
            "items": 0,
            "chain_sha256": None,
        }

    def _path(self, generation, category, name):
        return f"{self.root}/generations/{_generation(generation)}/{category}/{name}.json"

    def page_key(self, state):
        return fingerprint([state["generation_id"], state["page_token"]])

    def check_page(self, state, preview):
        require(
            state["source_id"] == self.source_id
            and preview["authority"]["source_id"] == self.source_id,
            "integrity",
        )
        generation, key = state["generation_id"], self.page_key(state)
        for item in preview["items"]:
            identity = _identifier(
                "doc", "productivity:" + self.source_id + ":" + item["remote_id"]
            )
            seen = read_json(self.store, self._path(generation, "seen", identity))
            if seen:
                require(
                    seen["page_key"] == key and seen["item_sha256"] == fingerprint(item),
                    "cursor_invalidated",
                )
        continuation = preview["continuation"]
        if continuation is not None:
            next_key = fingerprint([generation, continuation])
            require(
                next_key != key
                and read_json(self.store, self._path(generation, "tokens", next_key)) is None,
                "cursor_loop",
            )

    def publish_page(self, state, preview, result, *, metadata=()):
        """Cursor + producer metadata become visible together, after every item and index."""
        self.check_page(state, preview)
        generation, key = state["generation_id"], self.page_key(state)
        for item, row in zip(preview["items"], result["results"], strict=True):
            record = {
                "schema": "productivity-generation-member/v1",
                "source_id": self.source_id,
                "generation_id": generation,
                "document_id": row["document_id"],
                "version_id": row["version_id"],
                "page_key": key,
                "item_sha256": fingerprint(item),
            }
            path = self._path(generation, "seen", row["document_id"])
            before = read_json(self.store, path)
            require(before is None or before == record, "cursor_invalidated")
            if before is None:
                publish_once(self.store, path, record)
        token_path = self._path(generation, "tokens", key)
        token = {"page_key": key, "preview_sha256": preview["sha256"]}
        before = read_json(self.store, token_path)
        require(before is None or before == token, "cursor_invalidated")
        if before is None:
            publish_once(self.store, token_path, token)
        complete = preview["continuation"] is None
        require(not complete or preview["checkpoint"] is not None, "incomplete")
        updated = {
            **state,
            "pages": state["pages"] + 1,
            "items": state["items"] + len(preview["items"]),
            "page_token": preview["continuation"],
            "status": "completed" if complete else "active",
            "chain_sha256": fingerprint([state["chain_sha256"], preview["sha256"]]),
        }
        transaction = AtomicInstanceCommit(
            self.store,
            InstanceLifecycleManager(self.store).control_root / "transactions",
            profile=PRODUCTIVITY_INTAKE_TRANSACTION_PROFILE,
            owner_id="productivity_" + uuid4().hex,
        )
        transaction.add(self.root + "/page-progress.json", _bytes(updated), immutable=False)
        transaction.add(
            self._path(generation, "pages", f"{updated['pages']:08d}"),
            _bytes(updated),
            immutable=True,
        )
        for path, value in metadata:
            checked_path(self.store, path)
            transaction.add(path, _bytes(value), immutable=False)
        if complete:
            receipt = {
                "schema": "productivity-generation/v1",
                "source_id": self.source_id,
                "generation_id": generation,
                "parent_generation": state["parent_generation"],
                "depth": state["depth"],
                "mode": state["mode"],
                "binding": state["binding"],
                "checkpoint": preview["checkpoint"],
                "pages": updated["pages"],
                "items": updated["items"],
                "chain_sha256": updated["chain_sha256"],
                "completed_at": utc_now(),
            }
            transaction.add(self.root + "/sync.json", _bytes(receipt), immutable=False)
            transaction.add(
                f"{self.root}/generations/{generation}/complete.json",
                _bytes(receipt),
                immutable=True,
            )
        transaction.commit()
        return updated

    def contains(self, document_id, version_id):
        require(re.fullmatch(r"doc_[0-9a-f]{32}", document_id) is not None, "integrity")
        receipt = read_json(self.store, self.root + "/sync.json")
        if not receipt or receipt.get("schema") != "productivity-generation/v1":
            return False
        generation = receipt["generation_id"]
        for _depth in range(MAX_GENERATION_DEPTH + 1):
            _generation(generation)
            complete = read_json(self.store, f"{self.root}/generations/{generation}/complete.json")
            require(complete is not None and complete["source_id"] == self.source_id, "integrity")
            member = read_json(self.store, self._path(generation, "seen", document_id))
            if member is not None:
                return member["version_id"] == version_id
            if complete["mode"] == "full":
                return False
            generation = complete["parent_generation"]
        require(False, "limit")
