"""Closed scheduler extension and integer admission accounting (ADR 0032)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from .ai_contract import RequestDescriptor, digest
from .scheduler_model import SchedulerError, instant_text, utc_instant

AI_JOB_KIND = "ai.execute"
MAX_AMOUNT = 2**53 - 1
PHASES = {"reserved", "possible", "settled", "released", "uncertain"}


def check(value, code="ai_job_invalid"):
    if not value:
        raise SchedulerError(code)


def integer(value, minimum=0, maximum=MAX_AMOUNT):
    check(type(value) is int and minimum <= value <= maximum)
    return value


def fingerprint(value):
    check(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None)
    return value


def ceil_price(units, micro_per_million):
    """No binary floating point or downward monetary rounding."""
    integer(units)
    integer(micro_per_million)
    return integer((units * micro_per_million + 999_999) // 1_000_000)


@dataclass(frozen=True)
class Budget:
    job_units: int
    period_units: int
    concurrency: int = 1
    queue: int = 100
    job_micros: int | None = None
    period_micros: int | None = None
    currency: str = "USD"

    def __post_init__(self):
        integer(self.job_units, 1)
        integer(self.period_units, 1)
        integer(self.concurrency, 1, 16)
        integer(self.queue, 1, 1000)
        for value in (self.job_micros, self.period_micros):
            if value is not None:
                integer(value)
        check(type(self.currency) is str and re.fullmatch("[A-Z]{3}", self.currency) is not None)


@dataclass(frozen=True)
class Quote:
    """Host-established contractual maximum, not a remotely discovered estimate."""

    route: str
    currency: str
    valid_from: str
    valid_until: str
    maximum_micros: int
    maximum_units: int
    evidence: str
    defensible: bool = False
    estimate_micros: int | None = None

    def bound(self, route, currency, units, now):
        fingerprint(self.route)
        fingerprint(self.evidence)
        integer(self.maximum_micros)
        integer(self.maximum_units, 1)
        if self.estimate_micros is not None:
            integer(self.estimate_micros)
        check(
            self.defensible is True and self.route == route and self.currency == currency,
            "ai_price_unknown",
        )
        check(
            utc_instant(self.valid_from) <= now < utc_instant(self.valid_until), "ai_price_expired"
        )
        check(units <= self.maximum_units, "ai_price_invalid_bound")
        return self.maximum_micros


def validate_ai(value, job):
    check(
        type(value) is dict
        and set(value)
        == {
            "schema_version",
            "request_ref",
            "binding",
            "request",
            "routes",
            "route",
            "budget",
            "generation",
            "deadline",
            "blocked",
            "cancel",
            "attempts",
            "result",
            "result_fingerprint",
            "terminal",
            "restored",
            "resume_not_before",
            "duplicate_risk_acknowledged",
        }
    )
    check(value["schema_version"] == 1 and job["job_kind"] == AI_JOB_KIND)
    for key in ("request_ref", "binding"):
        fingerprint(value[key])
    request = RequestDescriptor.from_mapping(value["request"])
    check(request.context.instance_id == job["scope"]["id"], "ai_wrong_instance")
    Budget(**value["budget"])
    integer(value["generation"])
    instant_text(value["deadline"])
    if value["resume_not_before"] is not None:
        instant_text(value["resume_not_before"])
    check(type(value["routes"]) is list and 1 <= len(value["routes"]) <= 4)
    for route in value["routes"]:
        fingerprint(route)
    integer(value["route"], 0, len(value["routes"]) - 1)
    check(value["cancel"] in (None, "pause", "cancel", "disable"))
    check(type(value["restored"]) is bool)
    check(type(value["duplicate_risk_acknowledged"]) is bool)
    check(
        value["blocked"] is None
        or (type(value["blocked"]) is str and re.fullmatch(r"ai_[a-z_]{1,70}", value["blocked"]))
    )
    check(type(value["attempts"]) is list and len(value["attempts"]) == job["attempt"])
    for index, row in enumerate(value["attempts"], 1):
        check(
            type(row) is dict
            and set(row)
            == {
                "number",
                "route",
                "period",
                "reserved_units",
                "reserved_micros",
                "quote",
                "pricing",
                "phase",
                "quiescent",
                "units",
                "micros",
                "usage_source",
                "elapsed_ms",
                "reconciliations",
            }
        )
        check(row["number"] == index and row["phase"] in PHASES)
        check(type(row["quiescent"]) is bool)
        check(row["usage_source"] in {"UNKNOWN", "LOCAL", "PROVIDER", "NOT_SENT"})
        fingerprint(row["route"])
        check(row["route"] in value["routes"])
        check(type(row["period"]) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["period"]))
        integer(row["reserved_units"], 1)
        integer(row["elapsed_ms"])
        check(type(row["reconciliations"]) is list and len(row["reconciliations"]) <= 32)
        seen = set()
        for entry in row["reconciliations"]:
            check(
                type(entry) is dict
                and set(entry) == {"evidence", "units", "micros", "usage_source", "at"}
            )
            check(entry["usage_source"] in {"UNKNOWN", "LOCAL", "PROVIDER"})
            check(
                (entry["units"] is None and entry["micros"] is None)
                or entry["usage_source"] != "UNKNOWN"
            )
            fingerprint(entry["evidence"])
            check(entry["evidence"] not in seen)
            seen.add(entry["evidence"])
            instant_text(entry["at"])
            for key in ("units", "micros"):
                if entry[key] is not None:
                    integer(entry[key])
        for key in ("reserved_micros", "units", "micros"):
            if row[key] is not None:
                integer(row[key])
        if row["quote"] is not None:
            fingerprint(row["quote"])
            quote = Quote(**row["pricing"])
            check(digest(row["pricing"]) == row["quote"])
            check(
                quote.bound(
                    row["route"],
                    value["budget"]["currency"],
                    row["reserved_units"],
                    utc_instant(quote.valid_from),
                )
                == row["reserved_micros"]
            )
        else:
            check(row["pricing"] is None)
        if row["phase"] == "released":
            check(row["units"] == row["micros"] == 0 and row["quiescent"])
        if row["phase"] in {"reserved", "possible", "uncertain"}:
            check(not row["quiescent"])
    result = value["result"]
    if result is None:
        check(value["result_fingerprint"] is None)
    else:
        check(type(result) is dict and set(result) == {"kind", "value"})
        check(result["kind"] in {"context_check", "untrusted_text"})
        check(len(json.dumps(result).encode()) <= 32768)
        check(value["result_fingerprint"] == digest(result))
    terminal = value["terminal"]
    check(terminal is None or terminal in {"succeeded", "failed", "cancelled", "uncertain"})
    return value


def charged(row, key):
    if row["phase"] == "released":
        return 0
    actual = row[key]
    bound = row["reserved_" + key]
    return actual if actual is not None else bound


def totals(jobs, *, period, job_id=None):
    result = {"units": 0, "micros": 0, "unknown_money": False, "active": 0}
    for job in jobs:
        if job.get("job_kind") != AI_JOB_KIND or (job_id and job["id"] != job_id):
            continue
        for row in job["ai"]["attempts"]:
            result["active"] += int(not row["quiescent"])
            for key in ("units", "micros"):
                amount = charged(row, key)
                if amount is None:
                    result["unknown_money"] = True
                    continue
                unknown = row[key] is None
                same_period = job_id is not None or row["period"] == period
                # Unknown liabilities and old overrun debt do not disappear at midnight.
                result[key] += (
                    amount
                    if same_period or unknown or not row["quiescent"]
                    else max(0, amount - (row["reserved_" + key] or 0))
                )
    return result


def budget_record(budget):
    check(type(budget) is Budget)
    return asdict(budget)


def receipt_snapshot(ai):
    return {
        "request_ref": ai["request_ref"],
        "binding": ai["binding"],
        "result_fingerprint": ai["result_fingerprint"],
        "accounting_fingerprint": digest(ai["attempts"]),
        "outcome": ai["terminal"],
    }


def validate_receipt_snapshot(value):
    check(
        type(value) is dict
        and set(value)
        == {"request_ref", "binding", "result_fingerprint", "accounting_fingerprint", "outcome"}
    )
    for key in ("request_ref", "binding", "accounting_fingerprint"):
        fingerprint(value[key])
    if value["result_fingerprint"] is not None:
        fingerprint(value["result_fingerprint"])
    check(value["outcome"] in {"succeeded", "failed", "cancelled", "uncertain"})
    return dict(value)
