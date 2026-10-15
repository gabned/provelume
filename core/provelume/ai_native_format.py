"""Closed task dispatch for the existing native worker; model and limits unchanged."""

from . import ai_classification_format, ai_synthesis_profile


def _module(value):
    return (ai_classification_format if type(value) is dict
            and value.get("profile") == ai_classification_format.PROFILE
            else ai_synthesis_profile)


def chat_parts(payload, value):
    return _module(value).chat_parts(payload, value)


def native_prompt(payload, value):
    return _module(value).native_prompt(payload, value)


def native_prefix(value):
    module = _module(value)
    if module is ai_classification_format:
        return module.native_prefix(value)
    module.validate_format(value)
    return module.native_prefix(value["maximum"], value["language"])


def grammar(value):
    return _module(value).grammar(value)


def candidate(text, value):
    return _module(value).candidate(text, value)
