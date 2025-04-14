from pathlib import Path
from typing import Any

import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_mistral,
    skip_if_no_openai,
)

from inspect_ai.model import get_model

GATSBY = Path(__file__).parent / "gatsby.txt"
GATSBY_TOKENS = 69062

# model context window sizes
# from: https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json
GPT_4O = "openai/gpt-4o"
GPT_4O_AZURE = "openai/azure/gpt-4o"
CLAUDE_3_5_HAIKU = "anthropic/claude-3-5-haiku-latest"
GEMINI_1_5_FLASH = "google/gemini-1.5-flash"
MISTRAL_LARGE_2411 = "mistral/mistral-large-2411"

MODELS = {
    GPT_4O: 128000,
    GPT_4O_AZURE: 128000,
    CLAUDE_3_5_HAIKU: 200000,
    GEMINI_1_5_FLASH: 1000000,
    MISTRAL_LARGE_2411: 131000,
}


async def check_model_length(model: str, **model_args: Any) -> None:
    # context window for model
    model_tokens = MODELS.get(model, None)
    assert model_tokens

    # create message that exceeds context window
    with open(GATSBY, "r") as f:
        gatsby = f.read()
        message = gatsby
    for _ in range(0, (model_tokens // GATSBY_TOKENS) + 2):
        message = f"{message}\n\n{gatsby}"

    # run inference
    output = await get_model(model, **model_args).generate(
        f"Please summarize this:\n\n{message}"
    )
    assert output.stop_reason == "model_length"


@pytest.mark.asyncio
@skip_if_no_openai
async def test_model_length_openai():
    await check_model_length(GPT_4O)


@pytest.mark.asyncio
@skip_if_no_openai
async def test_model_length_openai_responses():
    await check_model_length(GPT_4O, responses_api=True)


# @pytest.mark.asyncio
# @skip_if_no_openai_azure
# async def test_model_length_openai_azure():
#     await check_model_length(GPT_4O_AZURE)


# @pytest.mark.asyncio
# @skip_if_no_openai_azure
# async def test_model_length_openai_responses_azure():
#     await check_model_length(GPT_4O_AZURE, responses_api=True)


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_model_length_anthropic():
    await check_model_length(CLAUDE_3_5_HAIKU)


# TODO: Anthropic Bedrock


@pytest.mark.asyncio
@skip_if_no_google
async def test_model_length_google():
    await check_model_length(GEMINI_1_5_FLASH)


@pytest.mark.asyncio
@skip_if_no_mistral
async def test_model_length_mistral():
    await check_model_length(MISTRAL_LARGE_2411)
