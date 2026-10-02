from __future__ import annotations

from .catalog_registry import exported_catalogs

_messages = exported_catalogs('google_connection_i18n.TEXT')
TEXT = {key: (_messages["en"][key], _messages["it"][key])
        for key in _messages["en"]}


def connection_translator(language):
    from .catalog_registry import namespace_catalog
    values = namespace_catalog(language, "google_connection")

    def translate(key):
        return values.get(key, values["google_connection_failed"])

    return translate
