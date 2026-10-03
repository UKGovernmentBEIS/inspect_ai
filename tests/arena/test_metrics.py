from typing import Any, cast

from inspect_ai.arena import elo, win_rate
from inspect_ai.scorer import MetricProtocol, SampleScore, Score


def _sample(comparisons: list[dict[str, str]]) -> SampleScore:
    return SampleScore(
        score=Score(value={}, metadata={"comparisons": comparisons, "failed": []}),
        sample_id="s",
    )


def _wr(*args: Any, **kwargs: Any) -> MetricProtocol:
    # `Metric` is a union of new/deprecated protocols — the deprecated arm wins
    # mypy's resolution and rejects `list[SampleScore]`. Cast to the modern
    # protocol so test call sites stay clean and well-typed.
    return cast(MetricProtocol, win_rate(*args, **kwargs))


def _elo(*args: Any, **kwargs: Any) -> MetricProtocol:
    return cast(MetricProtocol, elo(*args, **kwargs))


def test_win_rate_basic() -> None:
    # A beats B, A ties C, B loses to C → A=0.75, B=0.0, C=0.75
    samples = [
        _sample(
            [
                {"a": "A", "b": "B", "winner": "a"},
                {"a": "A", "b": "C", "winner": "tie"},
                {"a": "B", "b": "C", "winner": "b"},
            ]
        )
    ]
    result = cast(dict[str, Any], _wr()(samples))
    assert result == {"A": 0.75, "B": 0.0, "C": 0.75}


def test_win_rate_excludes_ties() -> None:
    samples = [
        _sample(
            [
                {"a": "A", "b": "B", "winner": "a"},
                {"a": "A", "b": "C", "winner": "tie"},
            ]
        )
    ]
    result = cast(dict[str, Any], _wr(include_ties=False)(samples))
    # A's tie excluded; only one decisive comparison: A vs B → A=1.0, B=0.0
    assert result == {"A": 1.0, "B": 0.0}


def test_win_rate_empty() -> None:
    assert _wr()([]) == {}


def test_elo_orders_contestants_correctly() -> None:
    # Lopsided: A wins every comparison vs B across many samples
    cmp = [{"a": "A", "b": "B", "winner": "a"}]
    samples = [_sample(cmp) for _ in range(50)]
    result = cast(dict[str, Any], _elo(n_bootstrap=100, seed=42)(samples))
    assert result["A.rating"] > result["B.rating"]
    # CIs span the mean
    assert result["A.low"] <= result["A.rating"] <= result["A.high"]
    assert result["B.low"] <= result["B.rating"] <= result["B.high"]


def test_elo_is_deterministic_with_seed() -> None:
    cmp = [
        {"a": "A", "b": "B", "winner": "a"},
        {"a": "A", "b": "C", "winner": "tie"},
        {"a": "B", "b": "C", "winner": "b"},
    ]
    samples = [_sample(cmp)] * 5
    r1 = cast(dict[str, Any], _elo(n_bootstrap=200, seed=7)(samples))
    r2 = cast(dict[str, Any], _elo(n_bootstrap=200, seed=7)(samples))
    assert r1 == r2


def test_elo_empty() -> None:
    assert _elo()([]) == {}


def test_metrics_ignore_malformed_metadata() -> None:
    # Empty metadata, missing comparisons, wrong types — should be skipped silently
    bad_samples = [
        SampleScore(score=Score(value={}), sample_id="s1"),
        SampleScore(
            score=Score(value={}, metadata={"comparisons": "not a list"}),
            sample_id="s2",
        ),
        SampleScore(
            score=Score(value={}, metadata={"comparisons": [{"missing": "keys"}]}),
            sample_id="s3",
        ),
    ]
    assert _wr()(bad_samples) == {}
    assert _elo()(bad_samples) == {}
