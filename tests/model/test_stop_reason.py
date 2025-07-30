from typing import Any

import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_grok,
    skip_if_no_groq,
    skip_if_no_mistral,
    skip_if_no_openai,
    skip_if_no_together,
    skip_if_trio,
)

from inspect_ai.model import GenerateConfig, ModelOutput, get_model


async def generate(model_name, **model_args: Any) -> ModelOutput:
    model = get_model(model_name, **model_args)
    return await model.generate(input="Hello.")


async def generate_token_limit(model_name, **model_args: Any) -> ModelOutput:
    model = get_model(model_name, **model_args)
    return await model.generate(
        input="Tell me a story.", config=GenerateConfig(max_tokens=16)
    )


async def check_stop_reason(model_name, **model_args: Any):
    response = await generate(model_name, **model_args)
    assert response.choices[0].stop_reason == "stop"

    response = await generate_token_limit(model_name, **model_args)
    assert response.choices[0].stop_reason == "max_tokens"


@pytest.mark.asyncio
@skip_if_no_groq
@skip_if_trio
async def test_groq_stop_reason() -> None:
    await check_stop_reason("groq/llama3-70b-8192")


@pytest.mark.asyncio
@skip_if_no_openai
@skip_if_trio
async def test_openai_stop_reason() -> None:
    await check_stop_reason("openai/gpt-3.5-turbo")


@pytest.mark.asyncio
@skip_if_no_openai
@skip_if_trio
async def test_openai_responses_stop_reason() -> None:
    await check_stop_reason("openai/gpt-4o-mini", responses_api=True)


@pytest.mark.asyncio
@skip_if_no_anthropic
@skip_if_trio
async def test_anthropic_stop_reason() -> None:
    await check_stop_reason("anthropic/claude-3-haiku-20240307")


@pytest.mark.asyncio
@skip_if_no_mistral
@skip_if_trio
async def test_mistral_stop_reason() -> None:
    await check_stop_reason("mistral/mistral-medium-latest")


@pytest.mark.asyncio
@skip_if_no_grok
@skip_if_trio
async def test_grok_stop_reason() -> None:
    await check_stop_reason("grok/grok-3-mini")


@pytest.mark.asyncio
@skip_if_no_together
@skip_if_trio
async def test_together_stop_reason() -> None:
    await check_stop_reason("together/meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo")
