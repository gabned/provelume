from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from .activity_i18n import ACTIVITY_TRANSLATIONS
from .audio_i18n import AUDIO_TRANSLATIONS
from .connector_i18n import CONNECTOR_TRANSLATIONS
from .email_i18n import EMAIL_TRANSLATIONS
from .file_family_i18n import FILE_FAMILY_TRANSLATIONS
from .folder_settings_i18n import FOLDER_SETTINGS_TRANSLATIONS
from .folder_source_i18n import FOLDER_SOURCE_TRANSLATIONS
from .google_i18n import GOOGLE_TRANSLATIONS
from .maintenance_i18n import MAINTENANCE_TRANSLATIONS
from .ocr_i18n import OCR_TRANSLATIONS
from .photo_i18n import PHOTO_TRANSLATIONS
from .qualification_i18n import QUALIFICATION_TRANSLATIONS
from .rebuild_i18n import REBUILD_TRANSLATIONS
from .representation_i18n import REPRESENTATION_TRANSLATIONS
from .scheduler_i18n import SCHEDULER_TRANSLATIONS
from .shell_i18n import SHELL_TRANSLATIONS
from .transcript_i18n import TRANSCRIPT_TRANSLATIONS
from .video_i18n import VIDEO_TRANSLATIONS

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
    result.update(AUDIO_TRANSLATIONS.get(selected, {}))
    result.update(CONNECTOR_TRANSLATIONS.get(selected, {}))
    result.update(EMAIL_TRANSLATIONS.get(selected, {}))
    result.update(FILE_FAMILY_TRANSLATIONS.get(selected, {}))
    result.update(REBUILD_TRANSLATIONS.get(selected, {}))
    result.update(REPRESENTATION_TRANSLATIONS.get(selected, {}))
    result.update(FOLDER_SETTINGS_TRANSLATIONS.get(selected, {}))
    result.update(FOLDER_SOURCE_TRANSLATIONS.get(selected, {}))
    result.update(GOOGLE_TRANSLATIONS.get(selected, {}))
    result.update(MAINTENANCE_TRANSLATIONS.get(selected, {}))
    result.update(SCHEDULER_TRANSLATIONS.get(selected, {}))
    result.update(SHELL_TRANSLATIONS.get(selected, {}))
    result.update(OCR_TRANSLATIONS.get(selected, {}))
    result.update(PHOTO_TRANSLATIONS.get(selected, {}))
    result.update(QUALIFICATION_TRANSLATIONS.get(selected, {}))
    result.update(TRANSCRIPT_TRANSLATIONS.get(selected, {}))
    result.update(VIDEO_TRANSLATIONS.get(selected, {}))
    return result


def translator(language: str):
    values = catalog(language)
    fallback = catalog("en")

    def translate(key: str) -> str:
        return values.get(key, fallback.get(key, key))

    return translate
