"""Tests for convert_errored_samples_to_incorrect functionality."""

import pytest

from inspect_ai._util.error import EvalError
from inspect_ai.log._convert_errors import convert_errored_samples_to_incorrect
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalScore,
    EvalSpec,
    EvalStats,
)
from inspect_ai.scorer._metric import INCORRECT, Score


@pytest.fixture(name="eval_log")
def fixture_eval_log(request: pytest.FixtureRequest) -> EvalLog:
    """Create a test EvalLog with configurable samples."""
    params = getattr(request, "param", {})
    num_samples = params.get("num_samples", 5)
    errored_indices = params.get("errored_indices", [])
    scored_indices = params.get("scored_indices", [])
    include_results = params.get("include_results", True)

    samples = []
    for idx in range(num_samples):
        sample_id = f"sample_{idx + 1}"

        # Create sample with error if specified
        error = None
        if idx in errored_indices:
            error = EvalError(
                message=f"Test error {idx}",
                traceback=f"Traceback for sample {idx}",
                traceback_ansi=f"Traceback for sample {idx}",
            )

        # Create sample with scores if specified
        scores = None
        if idx in scored_indices:
            scores = {
                "test_scorer": Score(
                    value=INCORRECT if idx % 2 else "C",
                    answer="test answer",
                    explanation="test explanation",
                )
            }

        sample = EvalSample(
            id=sample_id,
            epoch=1,
            input="test input",
            target="test target",
            error=error,
            scores=scores,
        )
        samples.append(sample)

    # Create results with scorer information
    results = None
    if include_results:
        results = EvalResults(
            scores=[
                EvalScore(
                    name="accuracy",
                    scorer="test_scorer",
                    params={},
                    metrics={"accuracy": {"name": "accuracy", "value": 0.5}},
                )
            ],
        )

    return EvalLog(
        version=2,
        status="success",
        eval=EvalSpec(
            eval_id="test_eval",
            run_id="test_run",
            created="2025-01-01T00:00:00Z",
            task="test_task",
            task_id="test_task_id",
            dataset=EvalDataset(),
            model="test_model",
            config=EvalConfig(),
        ),
        plan=EvalPlan(name="test_plan", steps=[]),
        samples=samples,
        results=results,
        stats=EvalStats(
            started_at="2025-01-01T00:00:00Z",
            completed_at="2025-01-01T00:01:00Z",
        ),
    )


class TestConvertErrorsBasicFunctionality:
    """Test basic convert_errored_samples_to_incorrect functionality."""

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 5, "errored_indices": [2]}],
        indirect=True,
    )
    def test_convert_single_errored_sample(self, eval_log: EvalLog):
        """Test converting a single errored sample creates score and removes error."""
        # Convert errors
        log = convert_errored_samples_to_incorrect(eval_log, recompute=False)

        # Check sample 2 (errored) was converted
        assert log.samples[2].error is None
        assert log.samples[2].scores is not None
        assert "test_scorer" in log.samples[2].scores
        score = log.samples[2].scores["test_scorer"]
        assert score.value == INCORRECT
        assert "Sample failed: Test error 2" in score.explanation
        assert score.metadata is not None
        assert score.metadata["conversion_source"] == "error"

        # Check other samples unchanged
        for idx in [0, 1, 3, 4]:
            assert log.samples[idx].error is None
            assert log.samples[idx].scores is None

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 5, "errored_indices": [0, 2, 4]}],
        indirect=True,
    )
    def test_convert_multiple_errored_samples(self, eval_log: EvalLog):
        """Test converting multiple errored samples."""
        log = convert_errored_samples_to_incorrect(eval_log, recompute=False)

        # Check all errored samples converted
        for idx in [0, 2, 4]:
            assert log.samples[idx].error is None
            assert log.samples[idx].scores is not None
            assert log.samples[idx].scores["test_scorer"].value == INCORRECT

        # Check non-errored samples unchanged
        for idx in [1, 3]:
            assert log.samples[idx].scores is None

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 5, "errored_indices": [1, 3], "scored_indices": [0, 2, 4]}],
        indirect=True,
    )
    def test_mixed_errored_and_scored_samples(self, eval_log: EvalLog):
        """Test converting errors in a log with both errored and scored samples."""
        log = convert_errored_samples_to_incorrect(eval_log, recompute=False)

        # Check errored samples converted
        for idx in [1, 3]:
            assert log.samples[idx].error is None
            assert log.samples[idx].scores is not None

        # Check scored samples unchanged
        for idx in [0, 2, 4]:
            assert log.samples[idx].error is None
            assert log.samples[idx].scores is not None
            # Should still have original score
            assert log.samples[idx].scores["test_scorer"].answer == "test answer"

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 5, "errored_indices": []}],
        indirect=True,
    )
    def test_no_errored_samples(self, eval_log: EvalLog):
        """Test that no changes occur when no samples have errors."""
        log = convert_errored_samples_to_incorrect(eval_log, recompute=False)

        # All samples should remain unchanged
        for sample in log.samples:
            assert sample.error is None
            assert sample.scores is None

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [0, 1], "scored_indices": [0]}],
        indirect=True,
    )
    def test_sample_with_error_and_partial_scores(self, eval_log: EvalLog):
        """Test that partial scores are replaced when sample has error."""
        log = convert_errored_samples_to_incorrect(eval_log, recompute=False)

        # Sample 0 had both error and score - score should be replaced
        assert log.samples[0].error is None
        assert log.samples[0].scores is not None
        score = log.samples[0].scores["test_scorer"]
        assert score.value == INCORRECT
        # Explanation should be from error, not original score
        assert "Sample failed" in score.explanation


class TestConvertErrorsCustomization:
    """Test customization options for convert_errored_samples_to_incorrect."""

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [1]}],
        indirect=True,
    )
    def test_custom_score_value(self, eval_log: EvalLog):
        """Test using custom score value instead of INCORRECT."""
        log = convert_errored_samples_to_incorrect(
            eval_log, score_value=0.0, recompute=False
        )

        assert log.samples[1].scores["test_scorer"].value == 0.0

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [1]}],
        indirect=True,
    )
    def test_custom_explanation(self, eval_log: EvalLog):
        """Test using custom explanation text."""
        custom_explanation = "Custom error explanation"
        log = convert_errored_samples_to_incorrect(
            eval_log, explanation=custom_explanation, recompute=False
        )

        assert log.samples[1].scores["test_scorer"].explanation == custom_explanation

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [1]}],
        indirect=True,
    )
    def test_preserve_error_true(self, eval_log: EvalLog):
        """Test that error is preserved in metadata when preserve_error=True."""
        log = convert_errored_samples_to_incorrect(
            eval_log, preserve_error=True, recompute=False
        )

        score = log.samples[1].scores["test_scorer"]
        assert score.metadata is not None
        assert "original_error" in score.metadata
        assert score.metadata["original_error"]["message"] == "Test error 1"
        assert "Traceback for sample 1" in score.metadata["original_error"]["traceback"]

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [1]}],
        indirect=True,
    )
    def test_preserve_error_false(self, eval_log: EvalLog):
        """Test that error is not preserved when preserve_error=False."""
        log = convert_errored_samples_to_incorrect(
            eval_log, preserve_error=False, recompute=False
        )

        score = log.samples[1].scores["test_scorer"]
        assert score.metadata is not None
        assert "original_error" not in score.metadata
        assert score.metadata["conversion_source"] == "error"


class TestConvertErrorsScorerNameResolution:
    """Test scorer name resolution logic."""

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [1]}],
        indirect=True,
    )
    def test_default_scorer_name(self, eval_log: EvalLog):
        """Test that default scorer name is used from results."""
        log = convert_errored_samples_to_incorrect(eval_log, recompute=False)

        # Should use "test_scorer" from results
        assert "test_scorer" in log.samples[1].scores

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [1]}],
        indirect=True,
    )
    def test_explicit_scorer_name(self, eval_log: EvalLog):
        """Test that explicit scorer_name parameter is respected."""
        log = convert_errored_samples_to_incorrect(
            eval_log, scorer_name="custom_scorer", recompute=False
        )

        assert "custom_scorer" in log.samples[1].scores

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [1], "include_results": False}],
        indirect=True,
    )
    def test_no_scorers_in_results(self, eval_log: EvalLog):
        """Test that ValueError is raised when log has no scorers."""
        with pytest.raises(ValueError, match="no scorers defined"):
            convert_errored_samples_to_incorrect(eval_log)


class TestConvertErrorsEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_samples_list(self):
        """Test that ValueError is raised for empty samples."""
        log = EvalLog(
            version=2,
            status="success",
            eval=EvalSpec(
                eval_id="test",
                run_id="test",
                created="2025-01-01T00:00:00Z",
                task="test",
                task_id="test",
                dataset=EvalDataset(),
                model="test",
                config=EvalConfig(),
            ),
            plan=EvalPlan(name="test", steps=[]),
            samples=[],
            results=EvalResults(scores=[]),
            stats=EvalStats(
                started_at="2025-01-01T00:00:00Z",
                completed_at="2025-01-01T00:01:00Z",
            ),
        )

        with pytest.raises(ValueError, match="no samples"):
            convert_errored_samples_to_incorrect(log)

    def test_none_samples(self):
        """Test that ValueError is raised when samples is None."""
        log = EvalLog(
            version=2,
            status="success",
            eval=EvalSpec(
                eval_id="test",
                run_id="test",
                created="2025-01-01T00:00:00Z",
                task="test",
                task_id="test",
                dataset=EvalDataset(),
                model="test",
                config=EvalConfig(),
            ),
            plan=EvalPlan(name="test", steps=[]),
            samples=None,
            results=EvalResults(scores=[]),
            stats=EvalStats(
                started_at="2025-01-01T00:00:00Z",
                completed_at="2025-01-01T00:01:00Z",
            ),
        )

        with pytest.raises(ValueError, match="no samples"):
            convert_errored_samples_to_incorrect(log)

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [1]}],
        indirect=True,
    )
    def test_boolean_score_value(self, eval_log: EvalLog):
        """Test using boolean False as score value."""
        log = convert_errored_samples_to_incorrect(
            eval_log, score_value=False, recompute=False
        )

        assert log.samples[1].scores["test_scorer"].value is False

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 1, "errored_indices": [0]}],
        indirect=True,
    )
    def test_large_error_message(self, eval_log: EvalLog):
        """Test handling of large error messages."""
        # Create a large error message
        large_message = "Error: " + ("x" * 10000)
        eval_log.samples[0].error.message = large_message

        log = convert_errored_samples_to_incorrect(eval_log, recompute=False)

        # Should handle large message correctly
        assert log.samples[0].scores is not None
        assert large_message in log.samples[0].scores["test_scorer"].explanation

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 1, "errored_indices": [0]}],
        indirect=True,
    )
    def test_unicode_in_error_message(self, eval_log: EvalLog):
        """Test handling of unicode characters in error messages."""
        unicode_message = "Error: 测试错误 🔥"
        eval_log.samples[0].error.message = unicode_message

        log = convert_errored_samples_to_incorrect(eval_log, recompute=False)

        assert log.samples[0].scores is not None
        assert unicode_message in log.samples[0].scores["test_scorer"].explanation


class TestConvertErrorsRecompute:
    """Test metrics recomputation parameter."""

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 5, "errored_indices": [1, 3]}],
        indirect=True,
    )
    def test_recompute_false(self, eval_log: EvalLog):
        """Test that recompute=False completes successfully."""
        log = convert_errored_samples_to_incorrect(eval_log, recompute=False)

        # Should complete without error and convert samples
        assert log.samples[1].error is None
        assert log.samples[3].error is None
        assert log.samples[1].scores is not None
        assert log.samples[3].scores is not None

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 5, "errored_indices": []}],
        indirect=True,
    )
    def test_recompute_with_no_conversions(self, eval_log: EvalLog):
        """Test that recompute is skipped when no samples are converted."""
        # This tests the converted_count > 0 condition
        # When no samples are converted, recompute should not be called
        # (which avoids registry lookup errors in tests)
        log = convert_errored_samples_to_incorrect(eval_log, recompute=True)

        # Should complete without error
        for sample in log.samples:
            assert sample.error is None
            assert sample.scores is None  # No conversions happened


class TestConvertErrorsReturnValue:
    """Test that the function returns the modified log."""

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [1]}],
        indirect=True,
    )
    def test_returns_eval_log(self, eval_log: EvalLog):
        """Test that function returns an EvalLog object."""
        log = convert_errored_samples_to_incorrect(eval_log, recompute=False)

        assert isinstance(log, EvalLog)
        assert log is eval_log  # Should be same object (modified in-place)

    @pytest.mark.parametrize(
        "eval_log",
        [{"num_samples": 3, "errored_indices": [1]}],
        indirect=True,
    )
    def test_chainable(self, eval_log: EvalLog):
        """Test that function can be chained."""
        # This should work without error
        log = convert_errored_samples_to_incorrect(
            convert_errored_samples_to_incorrect(eval_log, recompute=False),
            recompute=False,
        )

        # Second call should be a no-op (no errors left)
        assert log.samples[1].error is None
