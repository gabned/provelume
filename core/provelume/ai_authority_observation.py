"""Thread/context-local timing scope; no saved authority or execution decision."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_CURRENT = ContextVar("public_inventory_authority_observation", default=None)


@contextmanager
def observe_authority(progress):
    token = _CURRENT.set(progress)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def authority_value(part, read):
    """Evaluate the original current read once, inside an optional timing scope."""
    progress = _CURRENT.get()
    if progress is None:
        return read()
    with progress.measuring("authority_" + part):
        return read()
