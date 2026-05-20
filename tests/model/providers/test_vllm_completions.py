"""E2E tests for the vllm-completions provider.

Uses vllm-completions/EleutherAI/pythia-70m loaded in-process.
These tests verify the provider works as a general /v1/completions client,
not just for perplexity.
"""

import math

import pytest
from test_helpers.utils import skip_if_github_action, skip_if_no_vllm

from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_basic_completion() -> None:
    """Provider generates text via /v1/completions."""
    model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=10, temperature=0.0),
        device=0,
    )
    message = ChatMessageUser(content="The quick brown fox")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
    assert response.choices[0].stop_reason is not None


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_prompt_logprobs() -> None:
    """Provider returns prompt_logprobs when requested."""
    model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=1, prompt_logprobs=1),
        device=0,
    )
    message = ChatMessageUser(content="The quick brown fox")
    response = await model.generate(input=[message])

    choice = response.choices[0]
    assert choice.prompt_logprobs is not None
    assert len(choice.prompt_logprobs.content) > 0
    for lp in choice.prompt_logprobs.content:
        assert isinstance(lp.token, str)
        assert math.isfinite(lp.logprob)
        assert lp.logprob <= 0.0


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_completion_logprobs() -> None:
    """Provider returns completion token logprobs (standard logprobs field)."""
    model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=5, logprobs=True, top_logprobs=3),
        device=0,
    )
    message = ChatMessageUser(content="Once upon a time")
    response = await model.generate(input=[message])

    choice = response.choices[0]
    assert choice.logprobs is not None
    assert len(choice.logprobs.content) > 0
    for lp in choice.logprobs.content:
        assert isinstance(lp.token, str)
        assert math.isfinite(lp.logprob)
        assert lp.top_logprobs is not None
        assert len(lp.top_logprobs) <= 3


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_echo_mode() -> None:
    """Echo mode returns the prompt prepended to the completion."""
    model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=5, extra_body={"echo": True}),
        device=0,
    )
    prompt = "The capital of France"
    message = ChatMessageUser(content=prompt)
    response = await model.generate(input=[message])

    # With echo=True, the completion should start with the prompt text
    assert response.completion.startswith(prompt)


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_echo_with_logprobs() -> None:
    """Echo mode with logprobs returns logprobs for prompt + completion tokens."""
    model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=3,
            logprobs=True,
            top_logprobs=1,
            extra_body={"echo": True},
        ),
        device=0,
    )
    prompt = "Hello world"
    message = ChatMessageUser(content=prompt)
    response = await model.generate(input=[message])

    choice = response.choices[0]
    assert choice.logprobs is not None
    # With echo, logprobs cover prompt + completion tokens
    # "Hello world" is at least 2 tokens, plus 3 generated
    assert len(choice.logprobs.content) >= 4


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_no_chat_template_applied() -> None:
    """Verify no chat template is applied — raw prompt is sent directly."""
    model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=5, temperature=0.0, seed=42),
        device=0,
    )
    prompt = "2 + 2 ="
    message = ChatMessageUser(content=prompt)
    response = await model.generate(input=[message])

    # The completion should be a direct continuation of "2 + 2 =",
    # not a response to a chat-formatted message
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_usage_populated() -> None:
    """Provider populates usage statistics."""
    model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=5),
        device=0,
    )
    message = ChatMessageUser(content="Hello")
    response = await model.generate(input=[message])

    assert response.usage is not None
    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0
    assert response.usage.total_tokens > 0


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_extra_body_passthrough() -> None:
    """Extra body parameters are passed through to /v1/completions."""
    model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            extra_body={"prompt_logprobs": 3},
        ),
        device=0,
    )
    message = ChatMessageUser(content="The quick brown")
    response = await model.generate(input=[message])

    # prompt_logprobs=3 should return top-3 alternatives
    choice = response.choices[0]
    assert choice.prompt_logprobs is not None
    # At least one position should have top_logprobs alternatives
    has_alternatives = any(
        lp.top_logprobs is not None and len(lp.top_logprobs) > 0
        for lp in choice.prompt_logprobs.content
    )
    assert has_alternatives
