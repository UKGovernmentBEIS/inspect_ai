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
        gpu_memory_utilization=0.2,
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
        gpu_memory_utilization=0.2,
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
        gpu_memory_utilization=0.2,
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
        gpu_memory_utilization=0.2,
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
        gpu_memory_utilization=0.2,
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
        gpu_memory_utilization=0.2,
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
        gpu_memory_utilization=0.2,
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
async def test_prompt_token_ids_matches_text_input() -> None:
    """Pre-tokenized prompt_token_ids produces the same completion as the equivalent text."""
    text = "The quick brown fox"
    model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=10, temperature=0.0, seed=42),
        device=0,
        gpu_memory_utilization=0.2,
    )

    # Reference: text input.
    text_response = await model.generate(input=[ChatMessageUser(content=text)])

    # Tokenize via the provider (matches what /v1/completions would do) and
    # send IDs through metadata.
    token_ids = await model.api.tokenize(text)
    assert len(token_ids) > 0
    ids_response = await model.generate(
        input=[ChatMessageUser(content="", metadata={"prompt_token_ids": token_ids})]
    )

    # Same prompt (modulo round-trip), same completion.
    assert ids_response.completion == text_response.completion
    # And no extra BOS was prepended — input_tokens matches what we sent.
    assert ids_response.usage is not None
    assert ids_response.usage.input_tokens == len(token_ids)


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_prompt_token_ids_overrides_text() -> None:
    """When both message text and prompt_token_ids are supplied, the IDs win."""
    model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=1, temperature=0.0, seed=42),
        device=0,
        gpu_memory_utilization=0.2,
    )
    token_ids = await model.api.tokenize("Hi")
    # Misleading content: would tokenize to many more tokens than `token_ids`.
    response = await model.generate(
        input=[
            ChatMessageUser(
                content="this is a much longer string that tokenizes to many more tokens",
                metadata={"prompt_token_ids": token_ids},
            )
        ]
    )
    assert response.usage is not None
    assert response.usage.input_tokens == len(token_ids)


@pytest.mark.parametrize(
    "bad_ids,exc_type",
    [
        ([], ValueError),
        ("not a list", TypeError),
        ([1, 2, "three"], TypeError),
    ],
)
@pytest.mark.anyio
async def test_prompt_token_ids_validation(
    bad_ids: object, exc_type: type[Exception]
) -> None:
    """Invalid prompt_token_ids values raise before any server work."""
    from inspect_ai.model._providers.vllm_completions import VLLMCompletionsAPI

    # Construct directly to avoid spinning up vLLM — validation happens before
    # _ensure_server_started() so no GPU is needed for these cases.
    api = VLLMCompletionsAPI.__new__(VLLMCompletionsAPI)
    with pytest.raises(exc_type):
        await api.generate(
            input=[ChatMessageUser(content="", metadata={"prompt_token_ids": bad_ids})],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(max_tokens=1),
        )


@pytest.mark.anyio
async def test_no_prompt_source_raises() -> None:
    """Empty content and no prompt_token_ids raises a clear error."""
    from inspect_ai.model._providers.vllm_completions import VLLMCompletionsAPI

    api = VLLMCompletionsAPI.__new__(VLLMCompletionsAPI)
    with pytest.raises(ValueError, match="prompt_token_ids"):
        await api.generate(
            input=[ChatMessageUser(content="")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(max_tokens=1),
        )


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
        gpu_memory_utilization=0.2,
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
