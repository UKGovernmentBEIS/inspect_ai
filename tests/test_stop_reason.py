import pytest
from utils import (
    addition,
    skip_if_no_anthropic,
    skip_if_no_mistral,
    skip_if_no_openai,
    skip_if_no_together,
)

from inspect_ai.model import GenerateConfig, ModelOutput, get_model
from inspect_ai.solver._tool.tool_def import tool_def


async def generate(model_name) -> ModelOutput:
    model = get_model(model_name)
    return await model.generate(input="Hello.")


async def generate_tool(model_name) -> ModelOutput:
    model = get_model(model_name)
    return await model.generate(input="What is 1 + 1?", tools=[tool_def(addition())])


async def generate_token_limit(model_name) -> ModelOutput:
    model = get_model(model_name)
    return await model.generate(
        input="Tell me a story.", config=GenerateConfig(max_tokens=10)
    )


async def check_stop_reason(model_name, tool_calls: bool = True):
    response = await generate(model_name)
    assert response.choices[0].stop_reason == "stop"

    response = await generate_token_limit(model_name)
    assert response.choices[0].stop_reason == "length"

    if tool_calls:
        response = await generate_tool(model_name)
        assert response.choices[0].stop_reason == "tool_calls"


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
    await check_stop_reason("mistral/mistral-medium-latest", tool_calls=False)


@pytest.mark.asyncio
@skip_if_no_together
async def test_together_stop_reason() -> None:
    await check_stop_reason("together/google/gemma-2b-it", tool_calls=False)


# @pytest.mark.asyncio
# @skip_if_no_azureai
# async def test_azureai_stop_reason() -> None:
#     await check_stop_reason(None, tool_calls=False)
