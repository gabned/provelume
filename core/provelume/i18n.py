from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from .activity_i18n import ACTIVITY_TRANSLATIONS
from .folder_settings_i18n import FOLDER_SETTINGS_TRANSLATIONS
from .rebuild_i18n import REBUILD_TRANSLATIONS

SUPPORTED_LANGUAGES = {"en", "it"}


@lru_cache(maxsize=4)
def catalog(language: str) -> dict[str, str]:
    selected = language if language in SUPPORTED_LANGUAGES else "en"
    path = files("provelume").joinpath("i18n", f"{selected}.json")
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid UI catalog: {selected}")
    result = {str(key): str(text) for key, text in value.items()}
    result.update(ACTIVITY_TRANSLATIONS.get(selected, {}))
    result.update(REBUILD_TRANSLATIONS.get(selected, {}))
    result.update(FOLDER_SETTINGS_TRANSLATIONS.get(selected, {}))
    return result


def translator(language: str):
    values = catalog(language)
    fallback = catalog("en")

    def translate(key: str) -> str:
        return values.get(key, fallback.get(key, key))

    return translate
