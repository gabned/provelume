
from .catalog_registry import exported_catalogs

"""English and Italian labels for retained domain review flows."""

REVIEW_TRANSLATIONS = exported_catalogs('review_i18n.REVIEW_TRANSLATIONS')


def review_labels(language: str) -> dict[str, str]:
    selected = REVIEW_TRANSLATIONS.get(language, REVIEW_TRANSLATIONS["en"])
    return {key.removeprefix("review."): value for key, value in selected.items()}
