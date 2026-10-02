from __future__ import annotations

from .catalog_registry import (
    message,
    registry,
    render_message,
    resolve_language,
)


def catalog(language: str) -> dict[str, str]:
    selected = resolve_language(language)
    return {key: message(selected, key) for key in registry()["messages"]
            if not key.startswith(("installation.", "annotation.",
                                   "google_connection.", "capture."))}


def translator(language: str):
    selected = resolve_language(language)

    def translate(key: str, **parameters) -> str:
        value = message(selected, key)
        return render_message(selected, value, **parameters) if parameters or isinstance(
            value, dict) else value

    return translate
