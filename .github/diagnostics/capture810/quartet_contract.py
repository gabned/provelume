"""Evidence binding for addressed idle and cold Capture frames."""
from __future__ import annotations

from statistics import median


SAMPLES = (800, 801, 802, 810)
FRAME = (9, 10)
HISTORICAL_EXCESS_NS = (612_790, 2_147_224)


def bind_quartet(kernel_markers, brackets, sample_order, tid):
    """Accept exact, ordered raw markers with per-marker BOOTTIME brackets."""
    if tuple(sample_order) != SAMPLES:
        raise ValueError("Original idle series and cold Capture have different identities")
    if len(kernel_markers) != len(FRAME) * len(SAMPLES) or len(brackets) != len(kernel_markers):
        raise ValueError("Missing or extra markers")
    stamped = []
    last = -1
    for row, bracket, expected in zip(kernel_markers, brackets, FRAME * len(SAMPLES), strict=True):
        tag, stamp, actual_tid, code = row
        before, after = bracket
        if (
            tag != "M" or actual_tid != tid or code != expected
            or not before <= stamp <= after or not last < stamp
        ):
            raise ValueError("Marker identity, order or clock mismatch")
        stamped.append(stamp)
        last = stamp
    return {
        sample: {code: stamp for code, stamp in zip(
            FRAME, stamped[index * len(FRAME):(index + 1) * len(FRAME)], strict=True,
        )}
        for index, sample in enumerate(SAMPLES)
    }


def compare(totals_ns, component_ns, max_perturbation_per_probe_ns):
    """Evaluate excess and one independently matched component's contribution.

    Attribute only the contribution to the relative margin, not a historic
    counterfactual. Take the same median-selected idle observation for both
    the original metric and its component contribution.
    """
    if set(totals_ns) != set(SAMPLES) or set(component_ns) != set(SAMPLES):
        raise ValueError("Capture contrast does not bind all original samples")
    for sample in SAMPLES:
        if not 0 <= component_ns[sample] <= totals_ns[sample]:
            raise ValueError("A component exceeds its enclosing Capture")
    if max_perturbation_per_probe_ns < 0:
        raise ValueError("Independent perturbation bound must be nonnegative")

    idle = SAMPLES[:3]
    middle = sorted(idle, key=totals_ns.__getitem__)[1]
    limit = min(1_000_000_000, 2 * median([totals_ns[sample] for sample in idle]) + 100_000_000)
    margin = totals_ns[810] - limit
    uncertainty = 3 * max_perturbation_per_probe_ns
    ties = [sample for sample in idle if totals_ns[sample] == totals_ns[middle]]
    without = None
    status = "CAP_ACTIVE_OR_MEDIAN_AMBIGUOUS"
    if limit < 1_000_000_000 and len(ties) == 1:
        others = [abs(totals_ns[sample] - totals_ns[middle]) for sample in idle if sample != middle]
        if min(others) <= 2 * max_perturbation_per_probe_ns:
            status = "MEDIAN_IDENTITY_UNSTABLE_AT_BOUND"
        else:
            contribution = component_ns[810] - 2 * component_ns[middle]
            without = margin - contribution
            if margin <= 0:
                status = "NO_EXCEEDANCE"
            elif margin <= uncertainty:
                status = "EXCEEDANCE_WITHIN_MEASUREMENT_UNCERTAINTY"
            elif without < -2 * uncertainty:
                status = "POSITIVE_COMPONENT_LARGE_ENOUGH_FOR_RELATIVE_MARGIN"
            else:
                status = "NO_DISTINCT_COMPONENT_CONTRIBUTION"
    return {
        "original_limit_ns": limit, "margin_ns": margin,
        "idle_median_sample": middle, "margin_uncertainty_upper_ns": uncertainty,
        "conditional_margin_without_component_ns": without, "outcome": status,
    }
