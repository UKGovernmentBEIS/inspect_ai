import os

import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_grok,
    skip_if_no_groq,
    skip_if_no_mistral,
    skip_if_no_openai,
    skip_if_no_together,
)

from inspect_ai.model import get_model


@pytest.mark.asyncio
async def check_explicit_api_key(model_name, env_var):
    api_key = os.environ[env_var]
    del os.environ[env_var]
    try:
        model = get_model(model_name, api_key=api_key)
        await model.generate("What color is your parachute?")
    finally:
        os.environ[env_var] = api_key


@pytest.mark.asyncio
@skip_if_no_groq
async def test_groq_api_key():
    await check_explicit_api_key("groq/llama3-70b-8192", "GROQ_API_KEY")


@pytest.mark.asyncio
@skip_if_no_openai
async def test_openai_api_key():
    await check_explicit_api_key("openai/gpt-4", "OPENAI_API_KEY")


@pytest.mark.asyncio
@skip_if_no_grok
async def test_grok_api_key():
    await check_explicit_api_key("grok/grok-beta", "GROK_API_KEY")


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_anthropic_api_key():
    await check_explicit_api_key(
        "anthropic/claude-3-sonnet-20240229", "ANTHROPIC_API_KEY"
    )


@pytest.mark.asyncio
@skip_if_no_google
async def test_google_api_key():
    await check_explicit_api_key("google/gemini-1.0-pro", "GOOGLE_API_KEY")


@pytest.mark.asyncio
@skip_if_no_mistral
async def test_mistral_api_key():
    await check_explicit_api_key("mistral/mistral-large-latest", "MISTRAL_API_KEY")


@pytest.mark.asyncio
@skip_if_no_together
async def test_together_api_key():
    await check_explicit_api_key("together/google/gemma-2b-it", "TOGETHER_API_KEY")
