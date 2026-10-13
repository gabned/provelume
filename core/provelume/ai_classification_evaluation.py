"""Iudicium S01: pure assessment evidence; never inference or application authority."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Self

from .ai_context import (
    CLASSIFICATION_TEMPLATES,
    TaskTemplate,
    ValidatedClassification,
    _json,
    prepared_request,
    validate_candidate,
)
from .ai_contract import (
    Contract,
    Outcome,
    Profile,
    Reason,
    TemplateIdentity,
    closed,
    digest,
    fingerprint,
    identifier,
    require,
    sequence,
)
from .ai_gateway import receipt, revalidate

MAX_CASES = 4096
MIN_SUPPORT = 20  # Evidence sufficiency only; not a quality/automation threshold.
WILSON_Z = 1.959963984540054


def _target(value, count=64):
    require(value is None or (type(value) is int and 0 <= value < count))


@dataclass(frozen=True, slots=True, repr=False)
class EvaluationCase(Contract):
    id: str
    input_fingerprint: str
    expected_target: int | None

    def __post_init__(self):
        Contract.__post_init__(self)
        identifier(self.id)
        fingerprint(self.input_fingerprint)
        _target(self.expected_target)


@dataclass(frozen=True, slots=True, repr=False)
class EvaluationCorpus(Contract):
    """Host-established gold labels; fingerprints bind bytes, not gold-label authority."""

    id: str
    template: TemplateIdentity
    target_count: int
    cases: tuple[EvaluationCase, ...]

    def __post_init__(self):
        Contract.__post_init__(self)
        identifier(self.id)
        require(type(self.template) is TemplateIdentity)
        require(self.template.id in CLASSIFICATION_TEMPLATES)
        require(type(self.target_count) is int and 1 <= self.target_count <= 64)
        sequence(self.cases, MAX_CASES, empty=False)
        require(all(type(c) is EvaluationCase for c in self.cases))
        require(len({c.id for c in self.cases}) == len(self.cases))
        # Repeated inputs cannot inflate support under different case IDs.
        require(len({c.input_fingerprint for c in self.cases}) == len(self.cases))
        for case in self.cases:
            _target(case.expected_target, self.target_count)


@dataclass(frozen=True, slots=True, repr=False)
class EvaluationObservation(Contract):
    case_id: str
    input_fingerprint: str
    corpus_fingerprint: str
    template: TemplateIdentity
    profile_fingerprint: str
    output_fingerprint: str
    status: str
    target: int | None

    def __post_init__(self):
        Contract.__post_init__(self)
        identifier(self.case_id)
        for value in (
            self.input_fingerprint,
            self.corpus_fingerprint,
            self.profile_fingerprint,
            self.output_fingerprint,
        ):
            fingerprint(value)
        require(type(self.template) is TemplateIdentity)
        require(self.template.id in CLASSIFICATION_TEMPLATES)
        require(self.status in ("selected", "abstained", "invalid"))
        _target(self.target)
        require(self.target is not None if self.status == "selected" else self.target is None)

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        row = closed(_json(raw, 4096), cls)
        row["template"] = TemplateIdentity(**closed(row["template"], TemplateIdentity))
        return cls(**row)


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _confidence(correct, support):
    lower = None
    if support:
        rate = correct / support
        z2 = WILSON_Z**2
        lower = max(
            0.0,
            (
                rate
                + z2 / (2 * support)
                - WILSON_Z * math.sqrt(rate * (1 - rate) / support + z2 / (4 * support**2))
            )
            / (1 + z2 / support),
        )
    return {
        "support": support,
        "correct": correct,
        "empirical_precision": _ratio(correct, support),
        "wilson_lower_95": lower,
        "state": "insufficient_support" if support < MIN_SUPPORT else "evaluated_unqualified",
        "minimum_support": MIN_SUPPORT,
        "semantics": "corpus_per_target_precision_not_per_item_probability",
        "automation_authorized": False,
    }


@dataclass(frozen=True, slots=True, repr=False)
class EvaluationBatch(Contract):
    corpus: EvaluationCorpus
    profile_fingerprint: str
    observations: tuple[EvaluationObservation, ...]

    def __post_init__(self):
        Contract.__post_init__(self)
        require(type(self.corpus) is EvaluationCorpus)
        fingerprint(self.profile_fingerprint)
        sequence(self.observations, MAX_CASES, empty=False)
        require(all(type(o) is EvaluationObservation for o in self.observations))
        cases = {case.id: case for case in self.corpus.cases}
        require(len(self.observations) == len(cases))
        require({o.case_id for o in self.observations} == set(cases))
        corpus_fingerprint = self.corpus.fingerprint
        for observation in self.observations:
            require(
                observation.corpus_fingerprint == corpus_fingerprint
                and observation.profile_fingerprint == self.profile_fingerprint
                and observation.template == self.corpus.template
                and observation.input_fingerprint == cases[observation.case_id].input_fingerprint,
                Reason.STALE,
            )
            _target(observation.target, self.corpus.target_count)
        # Input order must not change a report or its fingerprint.
        object.__setattr__(
            self, "observations", tuple(sorted(self.observations, key=lambda o: o.case_id))
        )

    def report(self) -> dict[str, Any]:
        cases = {case.id: case for case in self.corpus.cases}
        selected = [o for o in self.observations if o.status == "selected"]
        correct = sum(o.target == cases[o.case_id].expected_target for o in selected)
        required = [o for o in self.observations if cases[o.case_id].expected_target is None]
        abstentions = sum(o.status == "abstained" for o in required)
        false_positives = sum(o.status == "selected" for o in required)
        return {
            "schema": "classification-evaluation/v1",
            "corpus_fingerprint": self.corpus.fingerprint,
            "template": self.corpus.template.as_record(),
            "profile_fingerprint": self.profile_fingerprint,
            "observations_fingerprint": digest([o.as_record() for o in self.observations]),
            "case_count": len(cases),
            "invalid_count": sum(o.status == "invalid" for o in self.observations),
            "classified_count": len(selected),
            "correct_classifications": correct,
            "accuracy_including_required_abstentions": (correct + abstentions) / len(cases),
            "classification_coverage": len(selected) / len(cases),
            "classification_precision": _ratio(correct, len(selected)),
            "required_abstentions": len(required),
            "correct_required_abstentions": abstentions,
            "required_abstention_failures": len(required) - abstentions,
            "false_positives": false_positives,
            "false_positive_rate": _ratio(false_positives, len(required)),
            "targets": [
                _confidence(
                    sum(
                        o.target == target and cases[o.case_id].expected_target == target
                        for o in selected
                    ),
                    sum(o.target == target for o in selected),
                )
                for target in range(self.corpus.target_count)
            ],
            "qualification": "NOT_EVALUATED",
            "automation_authorized": False,
        }


def assessment_receipt(
    raw, plan, preview, source, selections, *, profile, gateway, evaluation=None, **current
):
    """Revalidate supplied output through existing context/policy; no adapter is called.

    Gold fixtures and profile provenance are established independently by the host.
    A supplied assessment, report or hash never proves model execution/qualification.
    """
    require(type(current["template"]) is TaskTemplate)
    require(current["template"].id in CLASSIFICATION_TEMPLATES)
    require(type(profile) is Profile)
    request, snapshot = prepared_request(preview, source, selections, **current)
    fresh = revalidate(
        plan,
        request,
        **{
            **gateway,
            "snapshot": snapshot,
            "rules": current["rules"],
        },
    )
    result = {
        "schema": "classification-assessment-receipt/v1",
        "base_receipt": receipt(fresh).as_record(),
        "request_fingerprint": request.fingerprint,
        "source": source.version.as_record(),
        "template": request.template.as_record(),
        "policy_fingerprint": fresh.policy_fingerprint,
        "profile_fingerprint": None,
        "output_fingerprint": None,
        "assessment": None,
        "evaluation_fingerprint": None,
        "confidence": None,
        "result_origin": "supplied_for_validation",
        "execution_authorized": False,
        "automation_authorized": False,
        "canonical_mutation": False,
    }
    if fresh.outcome != Outcome.PLANNED:
        return result
    require(fresh.routes[0].profile_fingerprint == profile.fingerprint, Reason.STALE)
    assessed = validate_candidate(raw, preview, source, selections, **current)
    require(type(assessed) is ValidatedClassification)
    result.update(profile_fingerprint=profile.fingerprint, output_fingerprint=assessed.fingerprint)
    result["assessment"] = {
        "status": assessed.status,
        "target_index": assessed.target,
        "references": assessed.references,
        "authority": assessed.authority,
    }
    if evaluation is not None:
        require(type(evaluation) is EvaluationBatch)
        require(
            evaluation.profile_fingerprint == profile.fingerprint
            and evaluation.corpus.template == request.template
            and evaluation.corpus.target_count == len(current["template"].targets),
            Reason.STALE,
        )
        report = evaluation.report()
        result["evaluation_fingerprint"] = digest(report)
        if assessed.target is not None:
            result["confidence"] = report["targets"][assessed.target]
    return result
