from pathlib import Path
from typing import Any

import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_bedrock,
    skip_if_no_cloudflare,
    skip_if_no_google,
    skip_if_no_grok,
    skip_if_no_groq,
    skip_if_no_mistral,
    skip_if_no_openai,
    skip_if_no_openai_azure,
    skip_if_no_together,
)

from inspect_ai.model import get_model

GATSBY = Path(__file__).parent / "gatsby.txt"
GATSBY_TOKENS = 69062

# model context window sizes
# from: https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json
GPT_4O = "openai/gpt-4o"
GPT_4O_MINI_AZURE = "openai/azure/gpt-4o-mini"
CLAUDE_3_5_HAIKU = "anthropic/claude-3-5-haiku-latest"
GEMINI_1_5_FLASH = "google/gemini-1.5-flash"
MISTRAL_LARGE_2411 = "mistral/mistral-large-2411"
GROK_3_MINI = "grok/grok-3-mini"
GROQ_LLAMA_3_70B = "groq/llama3-70b-8192"
CLOUDFLARE_LLAMA_3_1_8B = "cf/meta/llama-3.1-8b-instruct-awq"
TOGETHER_LLAMA_3_3_70B = "together/meta-llama/Llama-3.3-70B-Instruct-Turbo"
BEDROCK_NOVA_LITE_1_0 = "bedrock/amazon.nova-lite-v1:0"

MODELS = {
    GPT_4O: 128000,
    GPT_4O_MINI_AZURE: 128000,
    CLAUDE_3_5_HAIKU: 200000,
    GEMINI_1_5_FLASH: 1000000,
    MISTRAL_LARGE_2411: 131000,
    GROK_3_MINI: 131072,
    GROQ_LLAMA_3_70B: 8192,
    CLOUDFLARE_LLAMA_3_1_8B: 128000,
    TOGETHER_LLAMA_3_3_70B: 128000,
    BEDROCK_NOVA_LITE_1_0: 128000,
}


async def check_model_length(
    model: str, max_chars: int | None = None, **model_args: Any
) -> None:
    # context window for model
    model_tokens = MODELS.get(model, None)
    assert model_tokens

    # create message that exceeds context window
    with open(GATSBY, "r") as f:
        gatsby = f.read()
        message = gatsby
    for _ in range(0, (model_tokens // GATSBY_TOKENS) + 2):
        message = f"{message}\n\n{gatsby}"

    # apply max_chars
    if max_chars is not None:
        message = message[0:max_chars]

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


@pytest.mark.asyncio
@skip_if_no_openai_azure
async def test_model_length_openai_azure():
    await check_model_length(GPT_4O_MINI_AZURE)


@pytest.mark.asyncio
@skip_if_no_openai_azure
async def test_model_length_openai_responses_azure():
    await check_model_length(GPT_4O_MINI_AZURE, responses_api=True)


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


@pytest.mark.asyncio
@skip_if_no_grok
async def test_model_length_grok():
    await check_model_length(GROK_3_MINI)


@pytest.mark.asyncio
@skip_if_no_groq
async def test_model_length_groq():
    await check_model_length(GROQ_LLAMA_3_70B, max_chars=50000)


@pytest.mark.asyncio
@skip_if_no_cloudflare
async def test_model_length_cloudflare():
    await check_model_length(CLOUDFLARE_LLAMA_3_1_8B)


@pytest.mark.asyncio
@skip_if_no_together
async def test_model_length_together():
    await check_model_length(TOGETHER_LLAMA_3_3_70B)


@pytest.mark.asyncio
@skip_if_no_bedrock
async def test_model_length_bedrock():
    await check_model_length(BEDROCK_NOVA_LITE_1_0)
