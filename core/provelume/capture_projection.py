"""Capture locators identify occurrences; projection codecs use the accepted type."""

import re
from pathlib import Path

from .extractors import extractor_for


def capture_document_extractor(store, document):
    source = store.read_canonical("sources", document.get("source_id", ""))
    if (
        not source
        or source.get("kind") != "capture"
        or not re.fullmatch(r"capture_[0-9a-f]{64}", str(document.get("locator", "")))
    ):
        return None
    suffix = {
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/uri-list": ".txt",
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "audio/wav": ".wav",
    }.get(document.get("media_type"))
    return extractor_for(Path("capture" + suffix)) if suffix else None
