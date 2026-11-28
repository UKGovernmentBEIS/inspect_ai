import random
from collections import defaultdict
from typing import Any, cast

from inspect_ai.scorer import Metric, SampleScore, Value, metric


def _iter_comparisons(scores: list[SampleScore]) -> list[dict[str, str]]:
    """Flatten the `comparisons` lists from each sample's metadata into one stream.

    `pairwise_scorer` stores the structured per-pair verdicts on
    `Score.metadata["comparisons"]` (not `value`, which only allows flat
    `Mapping[str, scalar]`). This helper hides the access path so metric
    implementations stay focused on the aggregation logic.
    """
    out: list[dict[str, str]] = []
    for sample in scores:
        metadata = sample.score.metadata
        if not metadata:
            continue
        comparisons = metadata.get("comparisons")
        if not isinstance(comparisons, list):
            continue
        for cmp in comparisons:
            if isinstance(cmp, dict) and {"a", "b", "winner"} <= cmp.keys():
                out.append(cast(dict[str, str], cmp))
    return out


@metric
def win_rate(include_ties: bool = True) -> Metric:
    """Average win rate per contestant across all pairwise comparisons.

    A win contributes 1.0; a loss contributes 0.0. Ties contribute 0.5 to each
    side when `include_ties=True` (the default), and are excluded from both
    numerator and denominator otherwise.

    Returns a `dict[contestant_name, rate]`. Contestants with zero
    comparisons are omitted.
    """

    def compute(scores: list[SampleScore]) -> Value:
        wins: dict[str, float] = defaultdict(float)
        total: dict[str, float] = defaultdict(float)

        for cmp in _iter_comparisons(scores):
            a, b, winner = cmp["a"], cmp["b"], cmp["winner"]
            if winner == "tie" and not include_ties:
                continue
            total[a] += 1
            total[b] += 1
            if winner == "a":
                wins[a] += 1
            elif winner == "b":
                wins[b] += 1
            else:
                wins[a] += 0.5
                wins[b] += 0.5

        return cast(Value, {name: wins[name] / total[name] for name in total})

    return compute


def _expected(rating_a: float, rating_b: float, base: float = 400.0) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / base))


def _run_elo(
    comparisons: list[dict[str, str]],
    contestants: list[str],
    k: float,
    initial: float,
    order: list[int],
) -> dict[str, float]:
    ratings = {c: initial for c in contestants}
    for idx in order:
        cmp = comparisons[idx]
        a, b, winner = cmp["a"], cmp["b"], cmp["winner"]
        ea = _expected(ratings[a], ratings[b])
        sa = 1.0 if winner == "a" else 0.0 if winner == "b" else 0.5
        delta = k * (sa - ea)
        ratings[a] += delta
        ratings[b] -= delta
    return ratings


@metric
def elo(
    k: float = 32.0,
    initial: float = 1000.0,
    n_bootstrap: int = 1000,
    seed: int | None = None,
) -> Metric:
    """Elo rating per contestant with bootstrap-based confidence intervals.

    Standard Elo update with scale `k` against `initial` rating. Because
    sequential Elo is order-dependent, the metric repeats the full update
    sweep over `n_bootstrap` random shuffles of the comparison list and
    reports the mean rating and 2.5th / 97.5th percentile bounds.

    Returns `{contestant_name: {"rating": float, "low": float, "high": float}}`.
    Contestants that never appeared in a comparison are omitted.
    """

    def compute(scores: list[SampleScore]) -> Value:
        comparisons = _iter_comparisons(scores)
        if not comparisons:
            return cast(Value, {})

        contestants = sorted(
            {cmp["a"] for cmp in comparisons} | {cmp["b"] for cmp in comparisons}
        )

        rng = random.Random(seed)
        samples: dict[str, list[float]] = {c: [] for c in contestants}
        indices = list(range(len(comparisons)))

        for _ in range(n_bootstrap):
            rng.shuffle(indices)
            run = _run_elo(comparisons, contestants, k, initial, indices)
            for c, r in run.items():
                samples[c].append(r)

        result: dict[str, dict[str, float]] = {}
        for c, ratings in samples.items():
            sorted_ratings = sorted(ratings)
            n = len(sorted_ratings)
            mean = sum(sorted_ratings) / n
            lo = sorted_ratings[max(0, int(0.025 * n))]
            hi = sorted_ratings[min(n - 1, int(0.975 * n))]
            result[c] = {"rating": mean, "low": lo, "high": hi}

        return cast(Value, _flatten_for_value(result))

    return compute


def _flatten_for_value(
    nested: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Flatten per-contestant stats into a single-level dict.

    Score `Value` is `Mapping[str, scalar]`, so nested per-contestant stats
    are encoded as flat keys (`{name}.rating`, `{name}.low`, `{name}.high`) —
    the result is valid `Value` while remaining round-trippable.
    """
    out: dict[str, Any] = {}
    for name, stats in nested.items():
        for k, v in stats.items():
            out[f"{name}.{k}"] = v
    return out
