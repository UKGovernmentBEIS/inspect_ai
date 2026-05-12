"""Unit tests for the ``aggregate`` metric factory."""

import math

import pytest

from inspect_ai.scorer import (
    Metric,
    Score,
    SampleScore,
    aggregate,
    mean,
    metric,
    std,
    stderr,
    value_to_float,
)


def _sample(value: object, sample_id: int = 0) -> SampleScore:
    return SampleScore(
        score=Score(value=value),  # type: ignore[arg-type]
        sample_id=sample_id,
    )


class TestAggregateBasics:
    def test_mean_of_key(self) -> None:
        scores = [
            _sample({"acc": 1.0, "other": 9.0}, 0),
            _sample({"acc": 0.0, "other": 8.0}, 1),
            _sample({"acc": 0.5, "other": 7.0}, 2),
        ]
        result = aggregate("acc", agg=mean())(scores)
        assert math.isclose(float(result), 0.5)

    def test_stderr_of_key(self) -> None:
        scores = [
            _sample({"acc": 1.0}, 0),
            _sample({"acc": 0.0}, 1),
            _sample({"acc": 1.0}, 2),
            _sample({"acc": 0.0}, 3),
        ]
        result = aggregate("acc", agg=stderr())(scores)
        assert float(result) > 0.0

    def test_std_of_key(self) -> None:
        scores = [
            _sample({"acc": 1.0}, 0),
            _sample({"acc": 3.0}, 1),
            _sample({"acc": 5.0}, 2),
        ]
        result = aggregate("acc", agg=std())(scores)
        assert float(result) > 1.0

    def test_passes_metadata_through(self) -> None:
        seen_metadata: list[dict] = []

        @metric
        def collect_metadata() -> Metric:
            def metric_fn(samples: list[SampleScore]) -> float:
                for s in samples:
                    seen_metadata.append(s.sample_metadata or {})
                return float(len(samples))

            return metric_fn

        scores = [
            SampleScore(
                score=Score(value={"acc": 1.0}),
                sample_id=i,
                sample_metadata={"group": grp},
            )
            for i, grp in enumerate(["a", "b", "a"])
        ]
        aggregate("acc", agg=collect_metadata())(scores)
        assert seen_metadata == [{"group": "a"}, {"group": "b"}, {"group": "a"}]


class TestOnMissing:
    def test_error_on_missing_key(self) -> None:
        scores = [
            _sample({"acc": 1.0}, 0),
            _sample({"other": 0.0}, 1),
        ]
        with pytest.raises(ValueError, match="key not found"):
            aggregate("acc", agg=mean())(scores)

    def test_error_on_none_value(self) -> None:
        scores = [
            _sample({"acc": 1.0}, 0),
            _sample({"acc": None}, 1),
        ]
        with pytest.raises(ValueError, match="value is None"):
            aggregate("acc", agg=mean())(scores)

    def test_skip_excludes_missing(self) -> None:
        scores = [
            _sample({"acc": 1.0}, 0),
            _sample({"other": 0.0}, 1),
            _sample({"acc": 0.0}, 2),
        ]
        result = aggregate("acc", agg=mean(), on_missing="skip")(scores)
        assert math.isclose(float(result), 0.5)

    def test_zero_treats_missing_as_zero(self) -> None:
        scores = [
            _sample({"acc": 1.0}, 0),
            _sample({"other": 0.0}, 1),
            _sample({"acc": 1.0}, 2),
        ]
        result = aggregate("acc", agg=mean(), on_missing="zero")(scores)
        assert math.isclose(float(result), 2.0 / 3.0)


class TestValueShapes:
    def test_rejects_non_dict_value(self) -> None:
        scores = [_sample(0.5, 0)]
        with pytest.raises(ValueError, match="requires Score.value to be a dict"):
            aggregate("acc", agg=mean())(scores)

    def test_to_float_converts_correctly(self) -> None:
        scores = [
            _sample({"label": "C"}, 0),
            _sample({"label": "I"}, 1),
            _sample({"label": "C"}, 2),
        ]
        result = aggregate("label", agg=mean(), to_float=value_to_float())(scores)
        assert math.isclose(float(result), 2.0 / 3.0)
