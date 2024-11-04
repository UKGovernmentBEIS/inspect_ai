import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_grok,
    skip_if_no_groq,
    skip_if_no_mistral,
    skip_if_no_openai,
    skip_if_no_together,
)

from inspect_ai.model import GenerateConfig, ModelOutput, get_model


async def generate(model_name) -> ModelOutput:
    model = get_model(model_name)
    return await model.generate(input="Hello.")


async def generate_token_limit(model_name) -> ModelOutput:
    model = get_model(model_name)
    return await model.generate(
        input="Tell me a story.", config=GenerateConfig(max_tokens=2)
    )


async def check_stop_reason(model_name):
    response = await generate(model_name)
    assert response.choices[0].stop_reason == "stop"

    response = await generate_token_limit(model_name)
    assert response.choices[0].stop_reason == "max_tokens"


@pytest.mark.asyncio
@skip_if_no_groq
async def test_groq_stop_reason() -> None:
    await check_stop_reason("groq/llama3-70b-8192")


@pytest.mark.asyncio
@skip_if_no_openai
async def test_openai_stop_reason() -> None:
    await check_stop_reason("openai/gpt-3.5-turbo")


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_anthropic_stop_reason() -> None:
    await check_stop_reason("anthropic/claude-3-haiku-20240307")


@pytest.mark.asyncio
@skip_if_no_mistral
async def test_mistral_stop_reason() -> None:
    await check_stop_reason("mistral/mistral-medium-latest")


@pytest.mark.asyncio
@skip_if_no_grok
async def test_grok_stop_reason() -> None:
    await check_stop_reason("grok/grok-beta")


@pytest.mark.asyncio
@skip_if_no_together
async def test_together_stop_reason() -> None:
    await check_stop_reason("together/google/gemma-2b-it")
