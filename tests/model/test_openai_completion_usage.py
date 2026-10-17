"""Regression tests for https://github.com/UKGovernmentBEIS/inspect_ai/issues/5815."""

from inspect_ai.model._model_output import ModelUsage
from inspect_ai.model._openai import openai_completion_usage


def test_openai_completion_usage_carries_reasoning_tokens() -> None:
    """Test outbound Chat Completions usage keeps reasoning tokens."""
    usage = ModelUsage(
        input_tokens=10,
        output_tokens=120,
        total_tokens=130,
        reasoning_tokens=80,
    )

    result = openai_completion_usage(usage)

    assert result.completion_tokens_details is not None
    assert result.completion_tokens_details.reasoning_tokens == 80


def test_openai_completion_usage_omits_reasoning_tokens_when_none() -> None:
    """Test no completion_tokens_details field when there are no reasoning tokens."""
    usage = ModelUsage(input_tokens=10, output_tokens=120, total_tokens=130)
    result = openai_completion_usage(usage)
    assert result.completion_tokens_details is None
