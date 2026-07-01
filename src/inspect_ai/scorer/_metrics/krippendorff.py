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

Disagreement = Callable[[list[object]], float]
"""Sum of δ²(a, b) over every ordered pair in a list of ratings."""


@metric
def krippendorff_alpha(
    level: KrippendorffLevel = "nominal",
    to_float: ValueToFloat | None = None,
) -> Metric:
    """Krippendorff's α coefficient of inter-rater agreement.

    Computes Krippendorff's α across multiple judges/raters for each
    sample. Each `SampleScore` passed to the metric must have a
    sequence-valued `Score.value`, where each element is one judge's
    rating of that sample; produce these per-judge lists by pairing
    `multi_scorer()` with the `collect` reducer. Samples whose
    `Score.value` is not a sequence (or contains fewer than two ratings)
    are skipped.

    α = 1 indicates perfect agreement; α = 0 indicates agreement equal
    to chance; α < 0 indicates systematic disagreement.

    For the 2-judge nominal case, α coincides with Scott's π (its
    many-judge analogue is Fleiss' κ); the two converge only as the
    number of units grows, since α applies a small-sample correction.

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
       Krippendorff's α as a float, or `nan` when there are no usable
       samples. When every rating is identical (zero expected
       disagreement), α is 1.0 by convention.
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
        prepared, disagreement = _prepare(level, units)
        return _alpha(prepared, disagreement)

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


def _prepare(
    level: KrippendorffLevel, units: list[list[object]]
) -> tuple[list[list[object]], Disagreement]:
    """Pick the disagreement numerator and, where needed, re-encode the ratings.

    Each level's δ² collapses to an O(n) closed form over a list of ratings, so
    both observed (per-unit) and expected (global) disagreement share one
    function. Ordinal ratings are re-encoded as cumulative-midpoint scores, which
    turns Krippendorff's ordinal δ² into the interval (squared-difference) form.
    """
    if level == "nominal":
        return units, _nominal_disagreement
    if level == "interval":
        return units, _squared_disagreement
    return _ordinal_scores(units), _squared_disagreement


def _nominal_disagreement(ratings: list[object]) -> float:
    """Σ_{i≠j} [a≠b] = n² − Σ_c n_c², the disagreement sum for unordered categories."""
    n = len(ratings)
    counts = Counter(ratings)
    return float(n * n - sum(c * c for c in counts.values()))


def _squared_disagreement(ratings: list[object]) -> float:
    """Σ_{i≠j} (a−b)² = 2n·Σ(x−x̄)², the disagreement sum for real-valued ratings."""
    xs = [float(x) for x in ratings]  # type: ignore[arg-type]
    n = len(xs)
    mean = sum(xs) / n
    return 2 * n * sum((x - mean) ** 2 for x in xs)


def _ordinal_scores(units: list[list[object]]) -> list[list[object]]:
    """Re-encode ordinal ratings as cumulative-midpoint scores.

    The midpoint of category `c` is `(Σ_{k<c} n_k) + n_c / 2` over the global
    marginal counts; with this encoding Krippendorff's ordinal δ²(a, b) equals
    the squared difference of the two scores.
    """
    counts = Counter(v for u in units for v in u)
    midpoint: dict[object, float] = {}
    cumulative = 0.0
    for v in sorted(counts):  # type: ignore[type-var]
        midpoint[v] = cumulative + counts[v] / 2
        cumulative += counts[v]
    return [[midpoint[v] for v in u] for u in units]


def _alpha(units: list[list[object]], disagreement: Disagreement) -> float:
    """Compute α = 1 − D_o / D_e given prepared units and a disagreement function."""
    flat = [v for u in units for v in u]
    n = len(flat)
    if n < 2:
        return float("nan")

    d_o = sum(disagreement(u) / (len(u) - 1) for u in units) / n
    d_e = disagreement(flat) / (n * (n - 1))

    if d_e == 0:
        return 1.0
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
