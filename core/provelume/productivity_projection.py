"""Rebuildable readable text from the exact attributed observation, never a raw token page."""

import hashlib
import json

from .extractors import MAX_EXTRACTED_CHARS, ExtractionError, ExtractionResult
from .productivity_connectors import ROOT
from .productivity_contract import ProductivityError, fingerprint, require, validate_item
from .review_decisions import read_json


def productivity_extraction(store, document, version, data):
    locator = document.get("locator", "")
    if not locator.startswith(("productivity:sha256:", "productivity-response:sha256:")):
        return None
    try:
        source = store.read_canonical("sources", document["source_id"])
        require(source is not None and source["kind"] == "connector", "integrity")
        require(version["document_id"] == document["id"], "integrity")
        digest = hashlib.sha256(data).hexdigest()
        require(digest == version["content_hash"], "integrity")
        record = read_json(
            store, f"{ROOT}/{source['id']}/observations/{document['id']}/{version['id']}.json"
        )
        require(record is not None and record["original_sha256"] == digest
                and record["item_sha256"] == fingerprint(record["item"]), "integrity")
        if locator.startswith("productivity-response:"):
            value = {"source_response_sha256": digest, "source_id": source["id"]}
        else:
            value = validate_item(record["item"])
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        require(len(text) <= MAX_EXTRACTED_CHARS, "limit")
        return ExtractionResult(text, "provelume.productivity-observation", "1")
    except (ProductivityError, KeyError, TypeError) as error:
        raise ExtractionError("Productivity observation cannot be projected safely") from error
