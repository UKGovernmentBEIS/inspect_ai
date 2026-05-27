"""Tests for target_perplexity scorer."""

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.model._model_output import Logprob, Logprobs
from inspect_ai.scorer._target import Target
from inspect_ai.scorer._target_perplexity import target_perplexity
from inspect_ai.solver._task_state import TaskState


def _state_with_prompt_logprobs(
    prompt_logprobs: list[Logprob] | None,
    metadata: dict | None = None,
) -> TaskState:
    """Create a TaskState with prompt logprobs on the first choice."""
    state = simple_task_state(model_output="x")
    state.output.choices[0].prompt_logprobs = (
        Logprobs(content=prompt_logprobs) if prompt_logprobs is not None else None
    )
    if metadata:
        state.metadata.update(metadata)
    return state


def _mock_model_with_tokenize(token_ids: list[int]) -> MagicMock:
    """Create a mock model whose api.tokenize() returns given token IDs."""
    mock = MagicMock()
    mock.api.tokenize = AsyncMock(return_value=token_ids)
    return mock


# -- Behaves like target_perplexity when num_target_tokens is available --


@pytest.mark.anyio
async def test_uses_num_target_tokens_argument() -> None:
    """Explicit argument takes precedence, no tokenization needed."""
    lps = [
        Logprob(token="a", logprob=-1.0),
        Logprob(token="b", logprob=-3.0),
    ]
    state = _state_with_prompt_logprobs(lps)
    scorer = target_perplexity(num_target_tokens=1)

    result = await scorer(state, Target(["b"]))

    assert result is not None
    assert result.as_float() == pytest.approx(3.0)
    assert result.metadata is not None
    assert result.metadata["num_tokens"] == 1


@pytest.mark.anyio
async def test_uses_num_target_tokens_from_metadata() -> None:
    """num_target_tokens in metadata, no tokenization needed."""
    lps = [
        Logprob(token="prompt", logprob=-1.0),
        Logprob(token=" The", logprob=-0.8),
        Logprob(token=" answer", logprob=-1.2),
    ]
    state = _state_with_prompt_logprobs(
        lps,
        metadata={"num_target_tokens": 2},
    )
    scorer = target_perplexity()

    result = await scorer(state, Target(["The answer"]))

    assert result is not None
    expected_nll = -(-0.8 + -1.2) / 2
    assert result.as_float() == pytest.approx(expected_nll)
    assert result.metadata is not None
    assert result.metadata["num_tokens"] == 2


@pytest.mark.anyio
async def test_defaults_to_1_without_metadata() -> None:
    """No num_target_tokens, no target_text — defaults to 1."""
    lps = [
        Logprob(token="a", logprob=-1.0),
        Logprob(token="b", logprob=-2.0),
    ]
    state = _state_with_prompt_logprobs(lps)
    scorer = target_perplexity()

    result = await scorer(state, Target(["b"]))

    assert result is not None
    assert result.as_float() == pytest.approx(2.0)
    assert result.metadata is not None
    assert result.metadata["num_tokens"] == 1


# -- Auto-tokenization path (uses provider's api.tokenize()) --


@pytest.mark.anyio
async def test_auto_tokenizes_target_text() -> None:
    """Calls api.tokenize() when target_text is in metadata."""
    lps = [
        Logprob(token="prompt", logprob=-1.0),
        Logprob(token=" The", logprob=-0.8),
        Logprob(token=" answer", logprob=-1.2),
    ]
    state = _state_with_prompt_logprobs(
        lps,
        metadata={"target_text": "The answer"},
    )

    mock = _mock_model_with_tokenize([101, 202])

    with patch(
        "inspect_ai.scorer._target_perplexity.get_model",
        return_value=mock,
    ):
        scorer = target_perplexity()
        result = await scorer(state, Target(["The answer"]))

    assert result is not None
    expected_nll = -(-0.8 + -1.2) / 2
    assert result.as_float() == pytest.approx(expected_nll)
    assert result.metadata is not None
    assert result.metadata["num_tokens"] == 2

    # Verify tokenize was called with the target text
    mock.api.tokenize.assert_awaited_once_with("The answer")


@pytest.mark.anyio
async def test_auto_tokenize_raises_on_failure() -> None:
    """Raises when target_text is provided but tokenization fails."""
    lps = [
        Logprob(token="a", logprob=-1.0),
        Logprob(token="b", logprob=-2.0),
    ]
    state = _state_with_prompt_logprobs(
        lps,
        metadata={"target_text": "some text"},
    )

    mock = MagicMock()
    mock.api.tokenize = AsyncMock(side_effect=Exception("connection refused"))

    with patch(
        "inspect_ai.scorer._target_perplexity.get_model",
        return_value=mock,
    ):
        scorer = target_perplexity()
        with pytest.raises(Exception, match="connection refused"):
            await scorer(state, Target(["b"]))


@pytest.mark.anyio
async def test_raises_when_provider_lacks_tokenize() -> None:
    """Raises NotImplementedError when provider doesn't support tokenize()."""
    lps = [
        Logprob(token="a", logprob=-1.0),
        Logprob(token="b", logprob=-2.0),
    ]
    state = _state_with_prompt_logprobs(
        lps,
        metadata={"target_text": "some text"},
    )

    mock = MagicMock()
    mock.api.tokenize = AsyncMock(
        side_effect=NotImplementedError("does not support tokenize()")
    )

    with patch(
        "inspect_ai.scorer._target_perplexity.get_model",
        return_value=mock,
    ):
        scorer = target_perplexity()
        with pytest.raises(NotImplementedError, match="does not support tokenize"):
            await scorer(state, Target(["b"]))


@pytest.mark.anyio
async def test_num_target_tokens_metadata_skips_tokenization() -> None:
    """When num_target_tokens is in metadata, tokenize() is NOT called."""
    lps = [
        Logprob(token="a", logprob=-1.0),
        Logprob(token="b", logprob=-3.0),
    ]
    state = _state_with_prompt_logprobs(
        lps,
        metadata={"num_target_tokens": 1, "target_text": "b"},
    )

    scorer = target_perplexity()
    # No mocking needed — if it tried to call get_model()/tokenize it would fail
    result = await scorer(state, Target(["b"]))

    assert result is not None
    assert result.as_float() == pytest.approx(3.0)


# -- Edge cases --


@pytest.mark.anyio
async def test_no_choices() -> None:
    """Returns NaN when model output has no choices."""
    state = simple_task_state(model_output="")
    state.output.choices = []
    scorer = target_perplexity()

    result = await scorer(state, Target(["x"]))
    assert result is not None
    assert math.isnan(result.as_float())


@pytest.mark.anyio
async def test_no_prompt_logprobs() -> None:
    """Returns NaN when prompt_logprobs is None."""
    state = _state_with_prompt_logprobs(None)
    scorer = target_perplexity()

    result = await scorer(state, Target(["x"]))
    assert result is not None
    assert math.isnan(result.as_float())
    assert "No prompt logprobs" in (result.explanation or "")


@pytest.mark.anyio
async def test_not_enough_logprobs() -> None:
    """Returns NaN when fewer logprobs than num_target_tokens."""
    lps = [Logprob(token="a", logprob=-1.0)]
    state = _state_with_prompt_logprobs(
        lps,
        metadata={"num_target_tokens": 5},
    )
    scorer = target_perplexity()

    result = await scorer(state, Target(["x"]))
    assert result is not None
    assert math.isnan(result.as_float())
    assert "num_target_tokens=5" in (result.explanation or "")
