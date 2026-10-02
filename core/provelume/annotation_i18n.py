
from .catalog_registry import exported_catalogs

"Editor interface labels; generated product translations are not human review."

LABELS = exported_catalogs('annotation_i18n.LABELS')


def annotation_labels(language: str) -> dict[str, str]:
    return dict(LABELS.get(language, LABELS["en"]))
