from __future__ import annotations

from .catalog_registry import exported_catalogs

EMAIL_TRANSLATIONS = exported_catalogs('email_i18n.EMAIL_TRANSLATIONS')

__all__ = ["EMAIL_TRANSLATIONS"]
