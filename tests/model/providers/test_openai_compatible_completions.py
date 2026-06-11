"""Tests for the openai-api-completions provider.

Validation and construction tests run without any server. The E2E tests
point the provider at a real ``/v1/completions`` server (vLLM-backed, so
they require a GPU like the vllm-completions tests).
"""

import pytest
from test_helpers.utils import skip_if_github_action, skip_if_no_vllm

from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model
from inspect_ai.model._providers.openai_compatible_completions import (
    OpenAICompatibleCompletionsAPI,
)


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
    """Invalid prompt_token_ids values raise before any network work."""
    # Construct directly to avoid needing credentials — validation happens
    # before any request so no client is needed for these cases.
    api = OpenAICompatibleCompletionsAPI.__new__(OpenAICompatibleCompletionsAPI)
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
    api = OpenAICompatibleCompletionsAPI.__new__(OpenAICompatibleCompletionsAPI)
    with pytest.raises(ValueError, match="prompt_token_ids"):
        await api.generate(
            input=[ChatMessageUser(content="")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(max_tokens=1),
        )


@pytest.mark.anyio
async def test_multi_message_input_raises() -> None:
    """The completions endpoint takes a single prompt — multi-message input raises."""
    api = OpenAICompatibleCompletionsAPI.__new__(OpenAICompatibleCompletionsAPI)
    with pytest.raises(TypeError, match="single user message"):
        await api.generate(
            input=[ChatMessageUser(content="one"), ChatMessageUser(content="two")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(max_tokens=1),
        )


def test_service_env_var_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Credentials resolve from <SERVICE>_API_KEY / <SERVICE>_BASE_URL."""
    monkeypatch.setenv("MYSVC_API_KEY", "test-key")
    monkeypatch.setenv("MYSVC_BASE_URL", "http://localhost:1/v1")
    model = get_model("openai-api-completions/mysvc/some-model")
    assert isinstance(model.api, OpenAICompatibleCompletionsAPI)
    assert model.api.base_url == "http://localhost:1/v1"
    assert model.api.service_model_name() == "some-model"


def test_missing_service_prefix_raises() -> None:
    """Model names must include a service prefix."""
    with pytest.raises(ValueError, match="service prefix"):
        get_model(
            "openai-api-completions/some-model",
            api_key="test-key",
            base_url="http://localhost:1/v1",
        )


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_against_real_completions_server() -> None:
    """E2E: text and pre-tokenized prompts against a real /v1/completions server.

    Boots a vLLM server via the vllm-completions provider (which also gives a
    reference completion), then drives it through openai-api-completions as a
    plain OpenAI-compatible server.
    """
    from inspect_ai.model._providers.vllm_completions import VLLMCompletionsAPI

    prompt = "The quick brown fox"
    config = GenerateConfig(max_tokens=10, temperature=0.0, seed=42)

    vllm_model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=config,
        device=0,
        gpu_memory_utilization=0.2,
    )
    vllm_response = await vllm_model.generate(input=[ChatMessageUser(content=prompt)])

    vllm_api = vllm_model.api
    assert isinstance(vllm_api, VLLMCompletionsAPI)
    model = get_model(
        "openai-api-completions/local/EleutherAI/pythia-70m",
        config=config,
        base_url=vllm_api.base_url,
        api_key=vllm_api.api_key,
    )

    # text prompt: same server, temperature 0 — same completion
    response = await model.generate(input=[ChatMessageUser(content=prompt)])
    assert response.completion == vllm_response.completion
    assert response.choices[0].stop_reason is not None
    assert response.usage is not None and response.usage.input_tokens > 0

    # pre-tokenized prompt: IDs pass through verbatim
    token_ids = await vllm_api.tokenize(prompt)
    assert len(token_ids) > 0
    ids_response = await model.generate(
        input=[ChatMessageUser(content="", metadata={"prompt_token_ids": token_ids})]
    )
    assert ids_response.completion == vllm_response.completion
    assert ids_response.usage is not None
    assert ids_response.usage.input_tokens == len(token_ids)


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_completion_logprobs_real_server() -> None:
    """E2E: completions-format logprobs parse correctly through the generic provider."""
    from inspect_ai.model._providers.vllm_completions import VLLMCompletionsAPI

    vllm_model = get_model(
        "vllm-completions/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=5),
        device=0,
        gpu_memory_utilization=0.2,
    )
    # boot the server (tokenize triggers deferred startup)
    vllm_api = vllm_model.api
    assert isinstance(vllm_api, VLLMCompletionsAPI)
    await vllm_api.tokenize("hi")

    model = get_model(
        "openai-api-completions/local/EleutherAI/pythia-70m",
        config=GenerateConfig(max_tokens=5, logprobs=True, top_logprobs=3),
        base_url=vllm_api.base_url,
        api_key=vllm_api.api_key,
    )
    response = await model.generate(input=[ChatMessageUser(content="Once upon a time")])
    logprobs = response.choices[0].logprobs
    assert logprobs is not None
    assert len(logprobs.content) > 0
    for lp in logprobs.content:
        assert lp.logprob <= 0.0
        assert lp.top_logprobs is not None
        assert len(lp.top_logprobs) >= 1
