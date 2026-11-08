"""Complete bounded mirror generations; transports never read the live Instance."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from uuid import uuid4

from .hierarchy import HierarchyManager
from .instance_validation import inspect_instance
from .library_projection_model import _markdown_label
from .markdown_viewer import MAX_VIEWER_MARKDOWN_CHARS, DocumentContentReader
from .mirror_contract import (
    MAX_DOCUMENTS,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_GENERATIONS,
    MAX_MANIFEST_BYTES,
    MAX_RECORDS,
    MAX_SECONDS,
    MAX_TOTAL_BYTES,
    findings,
    fingerprint,
    includes,
    inventory,
    parse,
    path,
    raw,
    require,
    selection,
    sha,
)
from .review_decisions import checked_path, read_bytes
from .storage import CANONICAL_KINDS, InstanceStore


class MirrorSnapshots:
    def __init__(self, store):
        self.store = store

    def root(self):
        return checked_path(self.store, "state/mirrors/generations")

    def source_fingerprint(self):
        # Admit the entire JSON inventory before any general Core deep reader.
        admitted, admitted_bytes = 0, 0
        for kind in CANONICAL_KINDS:
            directory = checked_path(self.store, "knowledge/" + kind)
            if not directory.exists():
                continue
            for entry in directory.iterdir():
                checked_path(self.store, "knowledge/" + kind + "/" + entry.name)
                require(entry.is_file() and entry.suffix == ".json", "integrity")
                size = entry.stat().st_size
                admitted += 1
                admitted_bytes += size
                require(
                    admitted <= MAX_RECORDS
                    and size <= MAX_MANIFEST_BYTES
                    and admitted_bytes <= MAX_TOTAL_BYTES,
                    "limit",
                )
        count = 0
        original_bytes = 0
        for kind in CANONICAL_KINDS:
            values = self._records(kind)
            count += len(values)
            require(count <= MAX_RECORDS, "limit")
            if kind == "originals":
                for value in values:
                    require(
                        type(value["size_bytes"]) is int
                        and 0 <= value["size_bytes"] <= MAX_FILE_BYTES,
                        "limit",
                    )
                    original_bytes += value["size_bytes"]
                require(original_bytes <= MAX_TOTAL_BYTES, "limit")
        result = inspect_instance(self.store.paths.root, deep=True, _config_source=self.store)
        require(result.get("status") == "valid", "instance_invalid")
        return result["content_fingerprint"]

    def _records(self, kind):
        directory = checked_path(self.store, "knowledge/" + kind)
        count = 0
        if directory.exists():
            for entry in directory.iterdir():
                count += 1
                require(count <= MAX_RECORDS and entry.suffix == ".json", "limit")
                checked_path(self.store, "knowledge/" + kind + "/" + entry.name)
                require(entry.is_file() and entry.stat().st_size <= MAX_MANIFEST_BYTES, "limit")
        values = []
        if directory.exists():
            for entry in sorted(directory.iterdir()):
                data = read_bytes(
                    self.store, "knowledge/" + kind + "/" + entry.name, maximum=MAX_MANIFEST_BYTES
                )
                require(data is not None, "integrity")
                values.append(parse(data))
        return values

    def _payload(self, scope, rules, deadline):
        # Inventory every canonical directory before any unbounded Core list reader.
        records, count = {}, 0
        for kind in CANONICAL_KINDS:
            records[kind] = self._records(kind)
            count += len(records[kind])
            require(count <= MAX_RECORDS, "limit")
        documents = records["documents"]
        if scope["kind"] == "instance":
            require(scope["id"] == self.store.read_config()["instance"]["id"], "scope")
            chosen = {row["id"] for row in documents}
        else:
            hierarchy = HierarchyManager(self.store)
            node = hierarchy.get_node(scope["id"])
            require(node is not None and node["kind"] == scope["kind"], "scope")
            chosen = hierarchy.document_ids_for_node(scope["id"])
        require(len(chosen) <= MAX_DOCUMENTS, "limit")
        files, entries, concerns = {}, [], []
        total = 0

        def add(name, data, category):
            nonlocal total
            require(time.monotonic() <= deadline, "deadline")
            path(name)
            require(name not in files and type(data) is bytes, "integrity")
            total += len(data)
            require(
                len(data) <= MAX_FILE_BYTES and total <= MAX_TOTAL_BYTES and len(files) < MAX_FILES,
                "limit",
            )
            files[name] = data
            entries.append(
                {"path": name, "size_bytes": len(data), "sha256": sha(data), "category": category}
            )
            for code in findings(data):
                concerns.append({"path": name, "code": code})

        versions = {row["id"]: row for row in records["versions"]}
        originals = {row["id"]: row for row in records["originals"]}
        reader = DocumentContentReader(self.store)
        eligible_originals, eligible_assets, navigation = set(), {}, []

        def asset_name(asset):
            suffix = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
            }.get(asset["media_type"], ".bin")
            return "attachments/" + asset["id"] + suffix

        for document in sorted(documents, key=lambda row: row["id"]):
            if document["id"] not in chosen:
                continue
            version = versions[document["current_version_id"]]
            require(
                type(version["size_bytes"]) is int and version["size_bytes"] <= MAX_FILE_BYTES,
                "limit",
            )
            view = reader.get(
                document["id"], max_chars=MAX_VIEWER_MARKDOWN_CHARS, build_missing_bundle=False
            )
            require(view is not None and not view["markdown_truncated"], "content_incomplete")
            require(view["markdown"] is not None, "representation_required")
            # Fixed mirror-relative names; raw external locators and credential refs are omitted.
            markdown = view["markdown"]
            for asset in (view.get("bundle") or {}).get("manifest", {}).get("assets", []):
                require(
                    asset["id"] not in eligible_assets
                    or eligible_assets[asset["id"]]["sha256"] == asset["sha256"],
                    "integrity",
                )
                eligible_assets[asset["id"]] = asset
                reference = "assets/" + asset["filename"]
                if asset["id"] in rules["attachments"]:
                    markdown = markdown.replace(
                        "(" + reference + ")", "(../" + asset_name(asset) + ")"
                    )
                else:
                    markdown = markdown.replace("(" + reference + ")", "(attachment-excluded)")
            add("documents/" + document["id"] + ".md", markdown.encode(), "markdown")
            navigation.append(
                "- ["
                + _markdown_label(document["title"])
                + "](documents/"
                + document["id"]
                + ".md)"
            )
            add(
                "metadata/" + document["id"] + ".json",
                raw(
                    {
                        "document_id": document["id"],
                        "version_id": version["id"],
                        "source_id": document["source_id"],
                        "title": document["title"],
                        "media_type": version["media_type"],
                        "original_sha256": version["content_hash"],
                        "representation": view["source"],
                        "canonical": False,
                    }
                ),
                "metadata",
            )
            eligible_originals.add(version["original_id"])
        for obj in sorted(records["objects"], key=lambda row: row["id"]):
            if scope["kind"] != "instance":
                attributed = obj["origin"].get("document_id")
                evidence_docs = {
                    row["document_id"]
                    for row in records["object-evidence"]
                    if row["id"] in obj["evidence_ids"]
                }
                if attributed not in chosen and not evidence_docs.intersection(chosen):
                    continue
            add("objects/" + obj["id"] + ".json", raw(obj), "metadata")
        require(set(rules["originals"]) <= eligible_originals, "include_scope")

        def original_bytes(original_id):
            original = originals[original_id]
            require(original["size_bytes"] <= MAX_FILE_BYTES, "limit")
            data = read_bytes(self.store, original["storage_ref"], maximum=MAX_FILE_BYTES)
            require(
                data is not None
                and len(data) == original["size_bytes"]
                and sha(data) == original["sha256"],
                "integrity",
            )
            return data

        for original_id in rules["originals"]:
            add("originals/" + original_id + ".bin", original_bytes(original_id), "original")
        attachments = {row["id"]: row for row in records["email-attachments"]}
        for selected in rules["attachments"]:
            if selected in eligible_assets:
                asset = eligible_assets[selected]
                data = read_bytes(self.store, asset["storage_ref"], maximum=MAX_FILE_BYTES)
                require(
                    data is not None
                    and len(data) == asset["size_bytes"]
                    and sha(data) == asset["sha256"],
                    "integrity",
                )
                add(asset_name(asset), data, "attachment")
                continue
            attachment = attachments.get(selected)
            require(
                attachment is not None and attachment["parent_document_id"] in chosen,
                "include_scope",
            )
            add(
                "attachments/" + selected + ".bin",
                original_bytes(attachment["original_id"]),
                "attachment",
            )
        # Exact named terminal AI receipts only, with a matching selected document plan.
        if rules["ai_receipts"]:
            from .scheduler import SchedulerStore

            scheduler = SchedulerStore(self.store)
            for receipt_id in rules["ai_receipts"]:
                receipt = scheduler.get_receipt(receipt_id)
                require(
                    receipt is not None and receipt["job_kind"] == "ai.execute", "include_scope"
                )
                job = scheduler.get_job(receipt["job_id"])
                context = ((job or {}).get("ai") or {}).get("request", {}).get("context", {})
                selected_version = versions.get(context.get("version_id"))
                require(
                    job is not None
                    and job["job_kind"] == receipt["job_kind"]
                    and context.get("instance_id") == self.store.read_config()["instance"]["id"]
                    and context.get("document_id") in chosen
                    and selected_version is not None
                    and selected_version["document_id"] == context["document_id"],
                    "include_scope",
                )
                add("ai-receipts/" + receipt_id + ".json", raw(receipt), "ai_receipt")
        add(
            "readme.md",
            (
                "# Provelume mirror\n\nDerived readable snapshot; "
                "not canonical storage or a backup.\n"
                "Only the exact manifest is complete.\n"
                "Originals, attachments and AI receipts are opt-in.\n\n"
                + "\n".join(navigation)
                + "\n"
            ).encode(),
            "metadata",
        )
        entries.sort(key=lambda row: row["path"])
        inventory(entries)
        concerns.sort(key=lambda row: (row["path"], row["code"]))
        return files, entries, concerns

    def build_locked(self, scope, rules, *, deadline=None):
        selection(scope)
        includes(rules)
        deadline = min(deadline or float("inf"), time.monotonic() + MAX_SECONDS)
        root = self.root()
        root.mkdir(parents=True, exist_ok=True)
        existing = list(root.iterdir())
        require(len(existing) <= MAX_GENERATIONS, "generation_limit")
        for child in existing:
            checked_path(self.store, "state/mirrors/generations/" + child.name)
        before = self.source_fingerprint()
        files, entries, concerns = self._payload(scope, rules, deadline)
        manifest = {
            "schema": "provelume-mirror-generation/v1",
            "scope": scope,
            "include_rules": rules,
            "source_fingerprint": before,
            "inventory": entries,
            "findings": concerns,
            "total_bytes": sum(row["size_bytes"] for row in entries),
            "canonical": False,
            "complete": True,
        }
        generation = fingerprint(manifest)
        target = root / generation
        if target.exists():
            require(self.verify(generation) == manifest, "integrity")
            return generation, manifest
        require(len(existing) < MAX_GENERATIONS, "generation_limit")
        staging = root / (".building-" + uuid4().hex)
        staging.mkdir()
        try:
            for name, data in files.items():
                require(time.monotonic() <= deadline, "deadline")
                item = staging / name
                item.parent.mkdir(parents=True, exist_ok=True)
                InstanceStore._atomic_bytes(item, data)
            InstanceStore._atomic_bytes(staging / "manifest.json", raw(manifest))
            require(self.source_fingerprint() == before, "source_changed")
            require(time.monotonic() <= deadline, "deadline")
            self._verify_root(staging, generation)
            os.replace(staging, target)
            return generation, self.verify(generation)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def _verify_root(self, root: Path, generation):
        relative = root.relative_to(self.store.paths.root).as_posix()
        data = read_bytes(self.store, relative + "/manifest.json", maximum=MAX_MANIFEST_BYTES)
        require(data is not None, "incomplete")
        manifest = parse(data)
        require(
            set(manifest)
            == {
                "schema",
                "scope",
                "include_rules",
                "source_fingerprint",
                "inventory",
                "findings",
                "total_bytes",
                "canonical",
                "complete",
            }
        )
        require(
            manifest["schema"] == "provelume-mirror-generation/v1"
            and manifest["complete"] is True
            and manifest["canonical"] is False
            and fingerprint(manifest) == generation,
            "integrity",
        )
        selection(manifest["scope"])
        includes(manifest["include_rules"])
        inventory(manifest["inventory"])
        actual, actual_findings = [], []
        for item in root.rglob("*"):
            item_relative = item.relative_to(root).as_posix()
            checked_path(self.store, relative + "/" + item_relative)
            if item.is_dir():
                continue
            require(item.is_file(), "integrity")
            actual.append(item_relative)
            require(len(actual) <= MAX_FILES + 1, "limit")
        expected = sorted([row["path"] for row in manifest["inventory"]] + ["manifest.json"])
        require(sorted(actual) == expected, "incomplete")
        for row in manifest["inventory"]:
            data = read_bytes(self.store, relative + "/" + row["path"], maximum=MAX_FILE_BYTES)
            require(
                data is not None and len(data) == row["size_bytes"] and sha(data) == row["sha256"],
                "integrity",
            )
            actual_findings.extend({"path": row["path"], "code": code} for code in findings(data))
        require(
            sorted(actual_findings, key=lambda row: (row["path"], row["code"]))
            == manifest["findings"],
            "integrity",
        )
        require(
            sum(row["size_bytes"] for row in manifest["inventory"]) == manifest["total_bytes"],
            "integrity",
        )
        return manifest

    def verify(self, generation):
        from .mirror_contract import HASH

        require(type(generation) is str and HASH.fullmatch(generation))
        root = checked_path(self.store, "state/mirrors/generations/" + generation)
        require(root.is_dir(), "incomplete")
        return self._verify_root(root, generation)

    def drop_locked(self, generation):
        # Explicit local derived staging removal only; no destination cleanup exists.
        self.verify(generation)
        shutil.rmtree(self.root() / generation)
