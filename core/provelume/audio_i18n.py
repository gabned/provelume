from __future__ import annotations

from .catalog_registry import exported_catalogs

AUDIO_TRANSLATIONS = exported_catalogs('audio_i18n.AUDIO_TRANSLATIONS')

__all__ = ["AUDIO_TRANSLATIONS"]
