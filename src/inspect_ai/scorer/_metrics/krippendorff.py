from collections import Counter
from collections.abc import Callable
from logging import getLogger
from typing import Literal

from .._metric import (
    Metric,
    SampleScore,
    ValueToFloat,
    metric,
)

logger = getLogger(__name__)

KrippendorffLevel = Literal["nominal", "ordinal", "interval"]

DeltaSq = Callable[[object, object], float]
"""Squared-difference function δ²(a, b) between two ratings."""


@metric
def krippendorff_alpha(
    level: KrippendorffLevel = "nominal",
    to_float: ValueToFloat | None = None,
) -> Metric:
    """Krippendorff's α coefficient of inter-rater agreement.

    Computes Krippendorff's α across multiple judges/raters for each
    sample. Each `SampleScore` passed to the metric must have a
    sequence-valued `Score.value`, where each element is one judge's
    rating of that sample. Samples whose `Score.value` is not a sequence
    (or contains fewer than two ratings) are skipped.

    α = 1 indicates perfect agreement; α = 0 indicates agreement equal
    to chance; α < 0 indicates systematic disagreement.

    For the 2-judge nominal case, α reduces to behaviour similar to
    Cohen's κ; this is expected and not a bug.

    Args:
       level: Measurement scale.
         `"nominal"` (default) treats ratings as unordered categories
         (any difference is a full disagreement). Use for
         correct/incorrect labels and unordered category IDs.
         `"ordinal"` treats ratings as ordered categories whose gaps
         are not assumed equal; δ² is weighted by the marginal
         frequency of intermediate ranks (Krippendorff 2007). Use for
         Likert-style ratings.
         `"interval"` treats ratings as numbers on an equal-interval
         scale; δ² is the squared numeric difference. Use for
         continuous scores.
       to_float: Optional `ValueToFloat` used to coerce non-numeric
         ratings to floats for `"ordinal"` and `"interval"` (e.g.,
         `value_to_float()` to map CORRECT/INCORRECT/PARTIAL/NOANSWER
         to 1/0/0.5/0). Numeric ratings need no coercion. Raises if
         `"ordinal"` or `"interval"` is selected with non-numeric
         ratings and no `to_float`. Ignored for `"nominal"`.

    Returns:
       Krippendorff's α as a float, or `nan` when α is undefined
       (no usable samples, or zero expected disagreement with non-zero
       observed disagreement).
    """
    if level not in ("nominal", "ordinal", "interval"):
        raise ValueError(
            f"krippendorff_alpha: unsupported level {level!r}; "
            "expected 'nominal', 'ordinal', or 'interval'"
        )

    def compute(scores: list[SampleScore]) -> float:
        units = _extract_units(scores, level, to_float)
        if not units:
            return float("nan")
        _maybe_warn_nominal_on_numeric(level, units)
        return _alpha(units, _delta_sq_for(level, units))

    return compute


def _extract_units(
    scores: list[SampleScore],
    level: KrippendorffLevel,
    to_float: ValueToFloat | None,
) -> list[list[object]]:
    """Filter scores to per-sample rating lists; coerce numerics for non-nominal levels."""
    units: list[list[object]] = []
    non_sequence = 0
    too_few = 0
    for sample_score in scores:
        value = sample_score.score.value
        if not isinstance(value, (list, tuple)):
            non_sequence += 1
            continue
        ratings: list[object] = (
            list(value)
            if level == "nominal"
            else [_coerce_numeric(v, to_float, level) for v in value]
        )
        if len(ratings) < 2:
            too_few += 1
            continue
        units.append(ratings)
    if non_sequence:
        logger.warning(
            "krippendorff_alpha: skipped %d sample(s) with a non-sequence "
            "Score.value (expected a list/tuple of per-judge ratings).",
            non_sequence,
        )
    if too_few:
        logger.warning(
            "krippendorff_alpha: skipped %d sample(s) with fewer than 2 ratings.",
            too_few,
        )
    return units


def _coerce_numeric(
    value: object, to_float: ValueToFloat | None, level: KrippendorffLevel
) -> float:
    if isinstance(value, (int, float)):  # bool is a subclass of int; treat as 0/1
        return float(value)
    if to_float is not None:
        return to_float(value)  # type: ignore[arg-type]
    raise ValueError(
        f"krippendorff_alpha(level={level!r}): non-numeric rating {value!r} "
        "requires a `to_float` mapping to establish ordering. Pre-encode your "
        "categories or pass `to_float=value_to_float()` for CORRECT/INCORRECT "
        "string ratings."
    )


def _delta_sq_for(level: KrippendorffLevel, units: list[list[object]]) -> DeltaSq:
    """Build a δ² appropriate to the measurement level.

    Closes over the data when needed; ordinal uses the global
    marginal-frequency distribution.
    """
    if level == "nominal":
        return lambda a, b: 0.0 if a == b else 1.0
    if level == "interval":
        return lambda a, b: (float(a) - float(b)) ** 2  # type: ignore[arg-type]
    return _ordinal_delta_sq([v for u in units for v in u])


def _ordinal_delta_sq(flat: list[object]) -> DeltaSq:
    """Krippendorff's ordinal δ²: ((Σ_{c=g..h} n_c) − (n_g + n_h) / 2)².

    `n_c` is the marginal count of category `c` across every rating; `g` and
    `h` are the two ratings being compared, treated as ranks in the sorted
    value domain.
    """
    counts = Counter(flat)
    domain = sorted(counts)  # type: ignore[type-var]
    n_v = [float(counts[v]) for v in domain]
    cumulative = [0.0]
    for c in n_v:
        cumulative.append(cumulative[-1] + c)
    rank = {v: i for i, v in enumerate(domain)}

    def delta_sq(a: object, b: object) -> float:
        ia, ib = rank[a], rank[b]
        if ia > ib:
            ia, ib = ib, ia
        between = cumulative[ib + 1] - cumulative[ia]
        return (between - (n_v[ia] + n_v[ib]) / 2) ** 2

    return delta_sq


def _alpha(units: list[list[object]], delta_sq: DeltaSq) -> float:
    """Compute α = 1 − D_o / D_e given precomputed units and a δ² function."""
    flat = [v for u in units for v in u]
    n = len(flat)
    if n < 2:
        return float("nan")

    d_o_num = 0.0
    for u in units:
        m = len(u)
        unit_sum = 0.0
        for i in range(m):
            for j in range(m):
                if i != j:
                    unit_sum += delta_sq(u[i], u[j])
        d_o_num += unit_sum / (m - 1)
    d_o = d_o_num / n

    d_e_num = 0.0
    for i in range(n):
        for j in range(n):
            if i != j:
                d_e_num += delta_sq(flat[i], flat[j])
    d_e = d_e_num / (n * (n - 1))

    if d_e == 0:
        return 1.0 if d_o == 0 else float("nan")
    return 1.0 - d_o / d_e


def _maybe_warn_nominal_on_numeric(
    level: KrippendorffLevel, units: list[list[object]]
) -> None:
    """Nudge users who picked nominal but appear to have ordered numeric data."""
    if level != "nominal":
        return
    distinct = {v for u in units for v in u}
    if len(distinct) <= 2:
        return
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in distinct):
        logger.warning(
            "krippendorff_alpha: nominal level applied to numeric data with %d "
            "distinct values; consider level='ordinal' (for ranked categories) "
            "or level='interval' (for true numeric distances).",
            len(distinct),
        )
