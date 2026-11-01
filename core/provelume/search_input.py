"""Validation for the HTML search page; domain/API date semantics stay separate."""

from __future__ import annotations

import re
from datetime import date


def search_page_inputs(query: str, date_from: str | None, date_to: str | None) -> dict:
    """Keep rejected input available for escaped presentation, never execute it."""
    errors = {}
    dates = {"date_from": date_from or "", "date_to": date_to or ""}
    parsed = {}
    for field, value in dates.items():
        if not value:
            continue
        try:
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
                raise ValueError("not an ISO calendar day")
            parsed[field] = date.fromisoformat(value)
        except ValueError:
            errors[field] = "search.invalid_date"
    if not errors and len(parsed) == 2 and parsed["date_from"] > parsed["date_to"]:
        errors = dict.fromkeys(dates, "search.invalid_range")
    return {
        "q": query.strip(),
        "search_errors": errors,
        "first_search_error": next(iter(errors), None),
        "date_from": dates["date_from"],
        "date_to": dates["date_to"],
        "date_inputs": {
            field: value if errors.get(field) != "search.invalid_date" else ""
            for field, value in dates.items()
        },
    }
