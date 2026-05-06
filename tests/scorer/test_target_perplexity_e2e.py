"""End-to-end test for target_perplexity scorer using vLLM."""

import math

import pytest
from test_helpers.utils import skip_if_github_action, skip_if_no_vllm

from inspect_ai import Task, eval_async
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import target_perplexity
from inspect_ai.solver import generate


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_with_num_target_tokens_metadata() -> None:
    """E2E: scores single-token targets with pre-computed num_target_tokens."""
    samples = [
        Sample(
            input="The capital of France is Paris",
            target="Paris",
            metadata={"num_target_tokens": 1},
        ),
        Sample(
            input="1 + 1 = 2",
            target="2",
            metadata={"num_target_tokens": 1},
        ),
    ]

    task = Task(
        dataset=MemoryDataset(samples=samples),
        solver=generate(max_tokens=1, prompt_logprobs=1),
        scorer=target_perplexity(),
    )

    log = await eval_async(
        task,
        model="vllm/EleutherAI/pythia-70m",
        model_args=dict(
            chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
            device=0,
        ),
    )

    result = log[0].results
    assert result is not None

    scores = result.scores
    assert len(scores) == 1
    metrics = scores[0].metrics
    assert "perplexity_per_token" in metrics
    assert "perplexity_per_seq" in metrics
    ppt = metrics["perplexity_per_token"].value
    pps = metrics["perplexity_per_seq"].value
    assert isinstance(ppt, float)
    assert isinstance(pps, float)
    assert ppt > 0
    assert pps > 0

    assert log[0].samples is not None
    for sample in log[0].samples:
        assert sample.scores is not None
        score = sample.scores["target_perplexity"]
        nll = score.as_float()
        assert math.isfinite(nll)
        assert nll > 0
        assert score.metadata is not None
        assert score.metadata["num_tokens"] == 1
        assert math.isfinite(score.metadata["sum_log_probs"])
        assert score.metadata["perplexity"] > 0


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_auto_tokenize_via_provider() -> None:
    """E2E: auto-tokenizes target_text using the provider's /tokenize endpoint."""
    samples = [
        Sample(
            input="Once upon a time there was a cat",
            target="a cat",
            metadata={"target_text": "a cat"},  # no num_target_tokens
        ),
    ]

    task = Task(
        dataset=MemoryDataset(samples=samples),
        solver=generate(max_tokens=1, prompt_logprobs=1),
        scorer=target_perplexity(),
    )

    log = await eval_async(
        task,
        model="vllm/EleutherAI/pythia-70m",
        model_args=dict(
            chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
            device=0,
        ),
    )

    assert log[0].samples is not None
    assert log[0].samples[0].scores is not None
    score = log[0].samples[0].scores["target_perplexity"]
    nll = score.as_float()
    assert math.isfinite(nll)
    assert nll > 0
    assert score.metadata is not None
    # /tokenize should count "a cat" as >= 1 tokens
    assert score.metadata["num_tokens"] >= 1
    assert math.isfinite(score.metadata["sum_log_probs"])
    assert score.metadata["perplexity"] > 0


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_default_fallback() -> None:
    """E2E: falls back to num_target_tokens=1 when no metadata provided."""
    samples = [
        Sample(
            input="The capital of France is Paris",
            target="Paris",
            # No num_target_tokens, no target_text — defaults to 1
        ),
    ]

    task = Task(
        dataset=MemoryDataset(samples=samples),
        solver=generate(max_tokens=1, prompt_logprobs=1),
        scorer=target_perplexity(),
    )

    log = await eval_async(
        task,
        model="vllm/EleutherAI/pythia-70m",
        model_args=dict(
            chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
            device=0,
        ),
    )

    assert log[0].samples is not None
    assert log[0].samples[0].scores is not None
    score = log[0].samples[0].scores["target_perplexity"]
    nll = score.as_float()
    assert math.isfinite(nll)
    assert nll > 0
    assert score.metadata is not None
    assert score.metadata["num_tokens"] == 1


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_multi_token_target() -> None:
    """E2E: scores multi-token targets with pre-computed num_target_tokens."""
    samples = [
        Sample(
            input="Once upon a time there was a cat",
            target="a cat",
            metadata={"num_target_tokens": 2},
        ),
    ]

    task = Task(
        dataset=MemoryDataset(samples=samples),
        solver=generate(max_tokens=1, prompt_logprobs=1),
        scorer=target_perplexity(),
    )

    log = await eval_async(
        task,
        model="vllm/EleutherAI/pythia-70m",
        model_args=dict(
            chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
            device=0,
        ),
    )

    assert log[0].samples is not None
    assert log[0].samples[0].scores is not None
    score = log[0].samples[0].scores["target_perplexity"]
    nll = score.as_float()
    assert math.isfinite(nll)
    assert nll > 0
    assert score.metadata is not None
    assert score.metadata["num_tokens"] == 2
