"""Tests for token counting APIs across different model providers."""

import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_grok,
    skip_if_no_mistral,
    skip_if_no_openai,
)

from inspect_ai.model import ChatMessageUser, get_model
from inspect_ai.tool import ToolInfo, ToolParam, ToolParams

# Test message for token counting - long enough to ensure meaningful token count
TEST_MESSAGE = ChatMessageUser(
    content="Hello, world! This is a test message for token counting. "
    "We want to make sure the token counting APIs are working correctly "
    "across all model providers including OpenAI, Anthropic, Google, and Grok."
)

# Test tool for count_tool_tokens
TEST_TOOL = ToolInfo(
    name="get_weather",
    description="Get the current weather for a location.",
    parameters=ToolParams(
        properties={
            "location": ToolParam(
                type="string",
                description="The city and state, e.g. San Francisco, CA",
            ),
            "unit": ToolParam(
                type="string",
                enum=["celsius", "fahrenheit"],
                description="The temperature unit to use.",
            ),
        },
        required=["location"],
    ),
)


@pytest.mark.asyncio
@skip_if_no_openai
async def test_openai_count_tokens():
    """Test OpenAI token counting using tiktoken."""
    model = get_model("openai/gpt-4o")

    token_count = await model.count_tokens(TEST_MESSAGE)

    # Message is ~40 tokens, so we expect a meaningful count (not just 1)
    assert token_count >= 10
    assert isinstance(token_count, int)


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_anthropic_count_tokens():
    """Test Anthropic token counting using native API."""
    model = get_model("anthropic/claude-sonnet-4-20250514")

    token_count = await model.count_tokens(TEST_MESSAGE)

    # Message is ~40 tokens, so we expect a meaningful count (not just 1)
    assert token_count >= 10
    assert isinstance(token_count, int)


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_anthropic_count_tool_tokens():
    """Test Anthropic tool token counting using native API."""
    model = get_model("anthropic/claude-sonnet-4-20250514")

    tool_token_count = await model.api.count_tool_tokens([TEST_TOOL])

    # Tool definition should be at least 20 tokens
    assert tool_token_count >= 20
    assert isinstance(tool_token_count, int)


@pytest.mark.asyncio
@skip_if_no_google
async def test_google_count_tokens():
    """Test Google token counting using native Gemini API."""
    model = get_model("google/gemini-2.5-flash")

    token_count = await model.count_tokens(TEST_MESSAGE)

    # Message is ~40 tokens, so we expect a meaningful count (not just 1)
    assert token_count >= 10
    assert isinstance(token_count, int)


@pytest.mark.asyncio
@skip_if_no_grok
async def test_grok_count_tokens():
    """Test Grok token counting using native xAI API."""
    model = get_model("grok/grok-3-mini")

    token_count = await model.count_tokens(TEST_MESSAGE)

    # Message is ~40 tokens, so we expect a meaningful count (not just 1)
    assert token_count >= 10
    assert isinstance(token_count, int)


@pytest.mark.asyncio
@skip_if_no_mistral
async def test_default_count_tokens():
    """Test default token counting using tiktoken o200k_base with 10% buffer.

    Mistral doesn't have a native tokenization API, so it uses the default
    implementation which is tiktoken o200k_base with a 10% buffer.
    """
    model = get_model("mistral/ministral-8b-latest")

    token_count = await model.count_tokens(TEST_MESSAGE)

    # Message is ~40 tokens, so we expect a meaningful count (not just 1)
    assert token_count >= 10
    assert isinstance(token_count, int)
