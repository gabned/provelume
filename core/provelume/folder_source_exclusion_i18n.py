from __future__ import annotations

from .catalog_registry import exported_catalogs, namespace_catalog

EXCLUSION_TRANSLATIONS = exported_catalogs('folder_source_exclusion_i18n.EXCLUSION_TRANSLATIONS')
_errors = {language: namespace_catalog(language, "exclusion_error")
           for language in ("en", "it")}
# Preserve the accepted EN/IT tuple-shaped export; catalogs remain the sole owner.
ERROR_TEXT = {key: (_errors["en"][key], _errors["it"][key]) for key in _errors["en"]}


def exclusion_message(code: str, language: str = "en") -> str:
    values = namespace_catalog(language, "exclusion_error")
    return values.get(code, values["invalid_rules"])
