"""Resolution of a task's declared headline metric against eval results."""

from logging import getLogger
from typing import Callable, NamedTuple, Sequence

from inspect_ai._util.logger import warn_once

from ._log import EvalLog, EvalMetric, EvalResults, EvalScore, HeadlineMetric

logger = getLogger(__name__)


class ResolvedHeadlineMetric(NamedTuple):
    """The score and metric that a headline declaration resolves to."""

    score: EvalScore
    """Score the metric was read from."""

    name: str
    """Key of the metric within `score.metrics`."""

    metric: EvalMetric
    """The metric itself."""


def resolve_headline_metric(
    results: EvalResults | None, declared: HeadlineMetric | None
) -> ResolvedHeadlineMetric | None:
    """Resolve a headline metric declaration against eval results.

    Each set field of `declared` narrows the candidate scores in turn (reducer,
    scorer, score), then `metric` picks within them. A declaration that matches
    nothing is abandoned whole: it warns and falls back to the convention of
    taking the first metric of the first score, rather than raising or letting
    its remaining fields select against the un-narrowed set. So a stale
    declaration (e.g. the task's scorer was replaced at eval time) never fails
    an eval and never silently resolves to a partially-honored selection.

    Args:
        results: Results to resolve against.
        declared: Declaration to apply, or `None` to use the convention.

    Returns:
        The resolved score and metric, or `None` if there is nothing to report.
    """
    if results is None or not results.scores:
        return None

    if declared is not None:
        resolved = _resolve_declared(results.scores, declared)
        if resolved is not None:
            return resolved

    return _first_metric(results.scores[0])


def _resolve_declared(
    scores: Sequence[EvalScore], declared: HeadlineMetric
) -> ResolvedHeadlineMetric | None:
    candidates: Sequence[EvalScore] = scores
    selectors: tuple[tuple[str | None, Callable[[EvalScore], str | None], str], ...] = (
        (declared.reducer, lambda score: score.reducer, "reducer"),
        (declared.scorer, lambda score: score.scorer, "scorer"),
        (declared.score, lambda score: score.name, "score"),
    )
    for value, field, label in selectors:
        if value is None:
            continue
        matched = [score for score in candidates if field(score) == value]
        if not matched:
            _abandon(label, value)
            return None
        candidates = matched

    if declared.metric is not None:
        for score in candidates:
            metric = score.metrics.get(declared.metric)
            if metric is not None:
                return ResolvedHeadlineMetric(score, declared.metric, metric)
        _abandon("metric", declared.metric)
        return None

    return _first_metric(candidates[0])


def _abandon(label: str, value: str) -> None:
    warn_once(
        logger,
        f"Headline {label} '{value}' not found in eval results (using the "
        "first metric of the first score instead).",
    )
    return None


def _first_metric(score: EvalScore) -> ResolvedHeadlineMetric | None:
    # a mapping-valued metric contributes its keys verbatim, and "" is a legal
    # key — so test for absence, not truthiness
    name = next(iter(score.metrics), None)
    return (
        ResolvedHeadlineMetric(score, name, score.metrics[name])
        if name is not None
        else None
    )


def headline_metric(log: EvalLog) -> ResolvedHeadlineMetric | None:
    """Headline metric for an eval log.

    Uses the headline resolved at scoring time when present, otherwise resolves
    the task's declaration (so logs written before headline metrics existed
    still report their first score's first metric).

    Args:
        log: Log to read the headline metric of.

    Returns:
        The resolved score and metric, or `None` if there is nothing to report.
    """
    if log.results is None:
        return None
    return resolve_headline_metric(
        log.results, log.results.headline or log.eval.headline_metric
    )


def headline_metric_ref(resolved: ResolvedHeadlineMetric) -> HeadlineMetric:
    """Fully qualified reference to an already-resolved headline metric.

    Records `scorer` as well as `score`: a dict-valued scorer names its scores
    for its value keys, so two such scorers sharing a key produce scores that
    `score` alone cannot tell apart.
    """
    return HeadlineMetric(
        scorer=resolved.score.scorer,
        score=resolved.score.name,
        metric=resolved.name,
        reducer=resolved.score.reducer,
    )
