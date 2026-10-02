"""Repository-owned offline message data. No network, code packs or global locale mutation."""

from __future__ import annotations

import json
import locale
import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from importlib.resources import files
from string import Formatter


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate catalog key: {key}")
        result[key] = value
    return result


def _data(name):
    return json.loads(files("provelume").joinpath("i18n", name).read_text(encoding="utf-8"),
                      object_pairs_hook=_unique)


@lru_cache(maxsize=1)
def registry():
    value = _data("registry.json")
    validate_registry(value)
    return value


def validate_registry(value):
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or not isinstance(value.get("languages"), list)
            or not 1 <= len(value["languages"]) <= 64):
        raise ValueError("Invalid language registry")
    codes = []
    for row in value["languages"]:
        if (not isinstance(row, dict)
                or not re.fullmatch(r"[a-z]{2,3}", str(row.get("id", "")))
                or not isinstance(row.get("label"), str) or not row["label"].strip()
                or re.search(r"[<>]", row["label"])
                or row.get("direction") not in {"ltr", "rtl"}
                or not re.fullmatch(row["id"] + r"(?:-[A-Za-z0-9]{2,8})*",
                                    str(row.get("locale", "")))):
            raise ValueError("Invalid language record")
        codes.append(row["id"])
    if (len(set(codes)) != len(codes) or value.get("fallback") not in codes
            or value.get("system_choice") != "system"):
        raise ValueError("Invalid language fallback")
    messages = value.get("messages")
    if not isinstance(messages, dict) or not messages:
        raise ValueError("Missing message contexts")
    for key, context in messages.items():
        if (not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9.-]{0,127}", key)
                or not isinstance(context, dict) or not context.get("context")
                or context.get("rendering") != "text"
                or type(context.get("sensitive_review_required")) is not bool):
            raise ValueError("Invalid message context")
    for binding in value.get("exports", {}).values():
        prefix = binding["namespace"] + "." if binding["namespace"] else ""
        keys = binding["keys"]
        if (len(keys) != len(set(keys))
                or any(prefix + key not in messages for key in keys)):
            raise ValueError("Invalid catalog export")
    glossary = value.get("glossary")
    if not isinstance(glossary, dict) or not glossary or any(
        not isinstance(description, str) or not description.strip()
        for description in glossary.values()
    ):
        raise ValueError("Missing glossary context")


SUPPORTED_LANGUAGES = frozenset(row["id"] for row in registry()["languages"])
LANGUAGE_CHOICES = SUPPORTED_LANGUAGES | {"system"}


def resolve_language(choice: str, host_locale: str | None = None) -> str:
    if choice in SUPPORTED_LANGUAGES:
        return choice
    if choice == "system":
        if host_locale is None:
            try:
                host_locale = locale.getlocale()[0] or ""
            except (ValueError, TypeError):
                host_locale = ""
        selected = str(host_locale).split(".", 1)[0].replace("_", "-").lower().split("-")[0]
        if selected in SUPPORTED_LANGUAGES:
            return selected
    return registry()["fallback"]


@lru_cache(maxsize=7)
def raw_catalog(language):
    value = _data(resolve_language(language) + ".json")
    if not isinstance(value, dict):
        raise ValueError("Invalid message catalog")
    return value


def message(language, key):
    selected = raw_catalog(resolve_language(language))
    return selected.get(key) or raw_catalog(registry()["fallback"]).get(key) or key


def exported_catalogs(identity):
    binding = registry()["exports"][identity]
    prefix = binding["namespace"] + "." if binding["namespace"] else ""
    return {language: {key: message(language, prefix + key) for key in binding["keys"]}
            for language in SUPPORTED_LANGUAGES}


def namespace_catalog(language, namespace):
    prefix = namespace + "."
    return {key[len(prefix):]: message(language, key) for key in registry()["messages"]
            if key.startswith(prefix)}


def placeholders(text):
    result = set()
    for _, field, spec, conversion in Formatter().parse(text):
        if field is not None:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", field) or spec or conversion:
                raise ValueError("Only named plain-text placeholders are supported")
            result.add(field)
    return result


def _variants(value):
    if isinstance(value, str):
        return [value]
    if (not isinstance(value, dict) or set(value) != {"type", "variable", "cases"}
            or value["type"] not in {"plural", "select"}
            or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", str(value["variable"]))
            or not isinstance(value["cases"], dict) or "other" not in value["cases"]
            or any(not isinstance(text, str) for text in value["cases"].values())):
        raise ValueError("Invalid data-only plural/select message")
    if value["type"] == "plural" and any(
        key not in {"zero", "one", "two", "few", "many", "other"}
        and not re.fullmatch(r"=\d+", key) for key in value["cases"]
    ):
        raise ValueError("Invalid plural case")
    return list(value["cases"].values())


def cardinal(language, count):
    """Bounded integer counts, CLDR 48 cardinal rules; pt is explicitly pt-PT."""
    if type(count) is not int or not 0 <= count <= 2**53 - 1:
        raise ValueError("Plural counts must be bounded nonnegative integers")
    language = resolve_language(language)
    if language == "fr" and count in {0, 1}:
        return "one"
    if count == 1:
        return "one"
    if language == "ro" and (count == 0 or 1 <= count % 100 <= 19):
        return "few"
    if language in {"fr", "it", "es", "pt"} and count and count % 1000000 == 0:
        return "many"
    return "other"


def render_message(language, message_value, **parameters):
    _variants(message_value)
    value = message_value
    if isinstance(value, dict):
        variable = value["variable"]
        if variable not in parameters:
            raise ValueError("Missing selector parameter")
        selector = parameters[variable]
        if value["type"] == "plural":
            cardinal(language, selector)  # Also validate exact-match selectors.
            case = f"={selector}"
            if case not in value["cases"]:
                case = cardinal(language, selector)
        else:
            case = str(selector)
        value = value["cases"].get(case, value["cases"]["other"])
    required = placeholders(value)
    if not required <= parameters.keys():
        raise ValueError("Missing message parameter")
    return value.format_map(parameters)


def format_number(value, language, *, decimals=0):
    if type(decimals) is not int or not 0 <= decimals <= 6:
        raise ValueError("Unsupported number precision")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Nonfinite number")
    selected = resolve_language(language)
    text = f"{number:,.{decimals}f}"
    group = "\u202f" if selected == "fr" else "\u00a0" if selected == "pt" else "."
    return text if selected == "en" else text.replace(",", "\0").replace(".", ",").replace(
        "\0", group)


def format_date(value: datetime, language):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Date presentation requires an explicit timezone")
    selected = resolve_language(language)
    separator = "." if selected in {"de", "ro"} else "/"
    return value.strftime(f"%d{separator}%m{separator}%Y %H:%M %z")


def sort_key(value):
    """Stable NFC/casefold ordering, with exact spelling as the deterministic tie-break."""
    normalized = unicodedata.normalize("NFC", str(value))
    return normalized.casefold(), normalized


def validate_catalogs(*, require_complete=True):
    specification = registry()
    expected = set(specification["messages"])
    reference = raw_catalog(specification["fallback"])
    findings = []
    completeness = {}
    for language in sorted(SUPPORTED_LANGUAGES):
        values = raw_catalog(language)
        if set(values) != expected:
            findings.append({"language": language, "kind": "KEY_PARITY"})
        missing = 0
        for key in sorted(expected):
            value = values.get(key)
            if not value:
                missing += 1
                continue
            try:
                variants = _variants(value)
                baseline = _variants(reference[key])
                if isinstance(value, dict) != isinstance(reference[key], dict):
                    raise ValueError("Message variant type mismatch")
                if isinstance(value, dict):
                    original = reference[key]
                    if (value["type"] != original["type"]
                            or value["variable"] != original["variable"]):
                        raise ValueError("Message selector mismatch")
                    if value["type"] == "select" and set(value["cases"]) != set(original["cases"]):
                        raise ValueError("Select case mismatch")
                expected_fields = {frozenset(placeholders(text)) for text in baseline}
                if any(frozenset(placeholders(text)) not in expected_fields for text in variants):
                    raise ValueError("Placeholder mismatch")
                if any(re.search(r"<(?:script|iframe|style)\b|\son\w+\s*=", text, re.I)
                       for text in variants):
                    raise ValueError("Active markup prohibited")
                context = specification["messages"][key]
                if not context["context"] or context["rendering"] != "text":
                    raise ValueError("Missing text-rendering context")
            except (ValueError, KeyError, TypeError) as exc:
                findings.append({"language": language, "key": key,
                                 "kind": "MESSAGE_CONTRACT", "detail": str(exc)})
        completeness[language] = {"keys": len(expected), "missing": missing,
                                  "complete": missing == 0 and set(values) == expected}
        if require_complete and missing:
            findings.append({"language": language, "kind": "INCOMPLETE", "missing": missing})
    return {"catalogs": completeness, "automatic_contract": "FAIL" if findings else "PASS",
            "linguistic_review": "UNVERIFIED", "findings": findings}
