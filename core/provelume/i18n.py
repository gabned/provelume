from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

SUPPORTED_LANGUAGES = {"en", "it"}


@lru_cache(maxsize=4)
def catalog(language: str) -> dict[str, str]:
    selected = language if language in SUPPORTED_LANGUAGES else "en"
    path = files("provelume").joinpath("i18n", f"{selected}.json")
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid UI catalog: {selected}")
    return {str(key): str(text) for key, text in value.items()}


def translator(language: str):
    values = catalog(language)
    fallback = catalog("en")

    def translate(key: str) -> str:
        return values.get(key, fallback.get(key, key))

    return translate
