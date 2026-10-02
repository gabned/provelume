from __future__ import annotations

from collections.abc import Callable

from .catalog_registry import exported_catalogs

MESSAGES = exported_catalogs('installation_i18n.MESSAGES')


def installation_translator(language: str) -> Callable[[str], str]:
    catalog = MESSAGES.get(language, MESSAGES["en"])
    fallback = MESSAGES["en"]

    def translate(key: str) -> str:
        return catalog.get(key, fallback.get(key, key))

    return translate
