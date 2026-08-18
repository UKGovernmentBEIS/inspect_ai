"""Tests for perplexity scorer and metrics."""

import math

import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.model._model_output import Logprob, Logprobs
from inspect_ai.scorer._metric import SampleScore, Score
from inspect_ai.scorer._metrics.perplexity import (
    perplexity_per_seq,
    perplexity_per_token,
)
from inspect_ai.scorer._perplexity import perplexity
from inspect_ai.scorer._target import Target
from inspect_ai.solver._task_state import TaskState


def _task_state_with_prompt_logprobs(
    prompt_logprobs: list[Logprob] | None,
) -> TaskState:
    """Create a TaskState with prompt logprobs on the first choice."""
    state = simple_task_state(model_output="test output")
    state.output.choices[0].prompt_logprobs = (
        Logprobs(content=prompt_logprobs) if prompt_logprobs is not None else None
    )
    return state


# -- Scorer tests --


@pytest.mark.anyio
async def test_perplexity_scorer_basic() -> None:
    """Scorer computes correct NLL from prompt logprobs."""
    prompt_lps = [
        Logprob(token="Hello", logprob=-1.0),
        Logprob(token="world", logprob=-2.0),
        Logprob(token="!", logprob=-0.5),
    ]
    state = _task_state_with_prompt_logprobs(prompt_lps)
    scorer = perplexity()

    result = await scorer(state, Target(["unused"]))
    assert result is not None

    expected_nll = -(-1.0 + -2.0 + -0.5) / 3
    assert result.as_float() == pytest.approx(expected_nll)
    assert result.metadata is not None
    assert result.metadata["num_tokens"] == 3
    assert result.metadata["sum_log_probs"] == pytest.approx(-3.5)
    assert result.metadata["perplexity"] == pytest.approx(math.exp(expected_nll))


@pytest.mark.anyio
async def test_perplexity_scorer_no_logprobs() -> None:
    """Scorer returns NaN when no prompt logprobs are available."""
    state = simple_task_state(model_output="test")
    scorer = perplexity()
    result = await scorer(state, Target(["unused"]))
    assert result is not None
    assert math.isnan(result.as_float())
    assert "No prompt logprobs" in (result.explanation or "")


@pytest.mark.anyio
async def test_perplexity_scorer_empty_prompt_logprobs() -> None:
    """Scorer returns NaN when prompt logprobs list is None."""
    state = _task_state_with_prompt_logprobs(None)
    scorer = perplexity()
    result = await scorer(state, Target(["unused"]))
    assert result is not None
    assert math.isnan(result.as_float())


@pytest.mark.anyio
async def test_perplexity_scorer_single_token() -> None:
    """Scorer works with a single prompt token."""
    prompt_lps = [Logprob(token="hi", logprob=-2.0)]
    state = _task_state_with_prompt_logprobs(prompt_lps)
    scorer = perplexity()
    result = await scorer(state, Target(["unused"]))
    assert result is not None
    assert result.as_float() == pytest.approx(2.0)
    assert result.metadata is not None
    assert result.metadata["perplexity"] == pytest.approx(math.exp(2.0))


@pytest.mark.anyio
async def test_perplexity_scorer_no_choices() -> None:
    """Scorer returns NaN when model output has no choices."""
    state = simple_task_state(model_output="")
    state.output.choices = []
    scorer = perplexity()
    result = await scorer(state, Target(["unused"]))
    assert result is not None
    assert math.isnan(result.as_float())


# -- Metric helpers --


def _make_sample_score(num_tokens: int, sum_log_probs: float) -> SampleScore:
    """Build a SampleScore with perplexity metadata.

    NLL is derived from sum_log_probs and num_tokens to avoid
    inconsistent test data.
    """
    nll = -sum_log_probs / num_tokens if num_tokens > 0 else 0.0
    return SampleScore(
        score=Score(
            value=nll,
            metadata={
                "num_tokens": num_tokens,
                "sum_log_probs": sum_log_probs,
            },
        ),
    )


# -- perplexity_per_token tests --


def test_per_token_single_sample() -> None:
    scores = [_make_sample_score(num_tokens=5, sum_log_probs=-10.0)]
    result = perplexity_per_token()(scores)  # type: ignore[arg-type]
    assert result == pytest.approx(math.exp(2.0))


def test_per_token_multiple_samples_weighted() -> None:
    """Longer sample dominates the per-token metric."""
    scores = [
        _make_sample_score(num_tokens=10, sum_log_probs=-10.0),
        _make_sample_score(num_tokens=2, sum_log_probs=-6.0),
    ]
    result = perplexity_per_token()(scores)  # type: ignore[arg-type]
    # corpus NLL = -(-10 + -6) / (10 + 2) = 16/12
    assert result == pytest.approx(math.exp(16.0 / 12.0))


def test_per_token_empty() -> None:
    result = perplexity_per_token()([])
    assert math.isnan(float(result))  # type: ignore[arg-type]


def test_per_token_zero_tokens() -> None:
    scores = [_make_sample_score(num_tokens=0, sum_log_probs=0.0)]
    result = perplexity_per_token()(scores)  # type: ignore[arg-type]
    assert math.isnan(float(result))  # type: ignore[arg-type]


# -- perplexity_per_seq tests --


def test_per_seq_single_sample() -> None:
    """Single sample: per_token and per_seq should be identical."""
    scores = [_make_sample_score(num_tokens=5, sum_log_probs=-10.0)]
    per_tok = perplexity_per_token()(scores)  # type: ignore[arg-type]
    per_seq = perplexity_per_seq()(scores)  # type: ignore[arg-type]
    assert per_tok == pytest.approx(per_seq)


def test_per_seq_multiple_samples_equal_weight() -> None:
    """Per-seq gives equal weight to each sample regardless of length."""
    scores = [
        # 10 tokens, NLL per token = 1.0
        _make_sample_score(num_tokens=10, sum_log_probs=-10.0),
        # 2 tokens, NLL per token = 3.0
        _make_sample_score(num_tokens=2, sum_log_probs=-6.0),
    ]
    result = perplexity_per_seq()(scores)  # type: ignore[arg-type]
    # mean NLL per seq = (1.0 + 3.0) / 2 = 2.0
    assert result == pytest.approx(math.exp(2.0))


def test_per_seq_differs_from_per_token() -> None:
    """With variable-length samples, per_seq != per_token."""
    scores = [
        _make_sample_score(num_tokens=10, sum_log_probs=-10.0),
        _make_sample_score(num_tokens=2, sum_log_probs=-6.0),
    ]
    per_tok = perplexity_per_token()(scores)  # type: ignore[arg-type]
    per_seq = perplexity_per_seq()(scores)  # type: ignore[arg-type]
    # per_token = exp(16/12) ≈ 3.79, per_seq = exp(2.0) ≈ 7.39
    assert per_tok != pytest.approx(per_seq)
    assert per_tok < per_seq  # type: ignore[operator]  # longer sample (lower NLL) pulls per_token down


def test_per_seq_empty() -> None:
    result = perplexity_per_seq()([])
    assert math.isnan(float(result))  # type: ignore[arg-type]


def test_per_seq_zero_tokens_skipped() -> None:
    """Samples with zero tokens are skipped in per_seq."""
    scores = [
        _make_sample_score(num_tokens=0, sum_log_probs=0.0),
        _make_sample_score(num_tokens=5, sum_log_probs=-10.0),
    ]
    result = perplexity_per_seq()(scores)  # type: ignore[arg-type]
    assert result == pytest.approx(math.exp(2.0))
