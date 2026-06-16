from collections import Counter
from typing import Mapping, Sequence

from inspect_ai._util.strenum import StrEnum

from .._metric import Metric, SampleScore, Value, metric

Categories = type[StrEnum] | Sequence[str] | None


def _category_names(categories: Categories) -> list[str] | None:
    if categories is None:
        return None
    if isinstance(categories, type) and issubclass(categories, StrEnum):
        return [str(member.value) for member in categories]
    if isinstance(categories, str):
        raise TypeError(
            "categories must be a StrEnum type or a sequence of category "
            f"labels, not a single string ({categories!r} would be iterated "
            "as characters)."
        )
    return [str(c) for c in categories]


def _require_scalar(values: Sequence[Value], metric_name: str) -> None:
    for v in values:
        if isinstance(v, Mapping) or (
            isinstance(v, Sequence) and not isinstance(v, str)
        ):
            raise TypeError(
                f"{metric_name} received {'dict' if isinstance(v, Mapping) else 'list'}-valued "
                f"scores. For dict-valued scorers, declare per-key metrics "
                f'instead, e.g. @scorer(metrics={{"*": [{metric_name}]}}).'
            )


def _frequencies(
    values: Sequence[Value],
    categories: list[str] | None,
    normalize: bool,
) -> dict[str, float]:
    counts: Counter[str] = Counter(str(v) for v in values)
    keys = list(dict.fromkeys((*(categories or ()), *counts)))
    total = sum(counts.values())
    denom = float(total) if (normalize and total > 0) else 1.0
    return {k: counts.get(k, 0) / denom for k in keys}


@metric(name="frequency", scores="unreduced")
def _frequency(
    categories: Sequence[str] | None = None,
    normalize: bool = True,
) -> Metric:
    """Registry-backed implementation with JSON-safe category labels."""

    def compute(scores: list[SampleScore]) -> dict[str, float]:
        values = [s.score.value for s in scores]
        _require_scalar(values, "frequency()")
        return _frequencies(
            values,
            list(categories) if categories is not None else None,
            normalize,
        )

    return compute


def frequency(
    categories: Categories = None,
    normalize: bool = True,
) -> Metric:
    r"""Frequency of each distinct categorical score value.

    Returns a mapping from category label to its proportion (or count) among
    scored samples. Intended for scorers that emit string-valued (categorical)
    scores, e.g. ``Score(value="sandbagging")``.

    For dict-valued scores, use the per-key metrics form so that each key gets
    its own scorer block in the results::

        @scorer(metrics={"*": [frequency()]})
        def my_scorer() -> Scorer: ...

    Args:
       categories: The full set of possible categories, as a ``StrEnum`` type
          or a sequence of labels. Declare this so that categories with zero
          observations are still reported as ``0.0`` and the metric round-trips
          identically through ``recompute_metrics()``. If ``None``, only
          observed categories are reported.
       normalize: If ``True`` (default) report proportions in ``[0, 1]``;
          if ``False`` report raw counts.

    Returns:
       Frequency metric
    """
    return _frequency(categories=_category_names(categories), normalize=normalize)


def categorical(categories: Categories = None) -> list[Metric]:
    r"""Default metrics for a categorical scorer.

    Convenience helper that returns ``[frequency(categories)]`` for use as the
    ``metrics=`` argument of :func:`~inspect_ai.scorer.scorer`. Pass a
    ``StrEnum`` to declare the full category set::

        class Verdict(StrEnum):
            YES = "yes"
            NO = "no"
            UNSURE = "unsure"

        @scorer(metrics=categorical(Verdict))
        def my_grader() -> Scorer: ...

    For dict-valued scores, use the per-key form::

        @scorer(metrics={"*": categorical(Verdict)})
        def my_grader() -> Scorer: ...

    When no epoch reducer is explicitly configured, epochs are not reduced
    for a scorer with ``frequency()`` metrics: each epoch's score is treated
    as an independent observation. An explicitly configured reducer
    (e.g. ``Epochs(n, "mode")``) is honoured.

    Args:
       categories: The full set of possible categories (typically a
          ``StrEnum``). Resolved to its member values so the category list is
          recorded in the metric params and survives ``recompute_metrics()``.
          If ``None``, only observed categories are reported.

    Returns:
       List of metrics suitable for ``@scorer(metrics=...)``.
    """
    return [frequency(categories=categories)]
