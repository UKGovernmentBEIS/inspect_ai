"""Tests for token counting APIs across different model providers."""

import base64
import os

import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_grok,
    skip_if_no_mistral,
    skip_if_no_openai,
)

from inspect_ai._util.content import (
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentVideo,
)
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    get_model,
)
from inspect_ai.model._tokens import (
    FALLBACK_AUDIO_TOKENS,
    FALLBACK_DOCUMENT_TOKENS,
    FALLBACK_VIDEO_TOKENS,
    count_media_tokens,
)
from inspect_ai.tool import ToolCall, ToolInfo, ToolParam, ToolParams

# Test message for token counting - long enough to ensure meaningful token count
TEST_MESSAGE = [
    ChatMessageUser(
        content="Hello, world! This is a test message for token counting. "
        "We want to make sure the token counting APIs are working correctly "
        "across all model providers including OpenAI, Anthropic, Google, and Grok."
    )
]

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

    tool_token_count = await model.count_tool_tokens([TEST_TOOL])

    # Tool definition should be at least 20 tokens
    assert tool_token_count >= 20
    assert isinstance(tool_token_count, int)


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_anthropic_count_tokens_consecutive_tool_messages():
    """Test Anthropic token counting with consecutive tool messages.

    This tests the fix for GitHub issue #3108 where token counting failed
    with "tool_use ids were found without tool_result blocks immediately after"
    when an assistant message had multiple tool_calls and each tool response
    was in a separate ChatMessageTool.
    """
    model = get_model("anthropic/claude-sonnet-4-20250514")

    # Create a conversation with an assistant message containing multiple tool calls
    # followed by separate tool response messages (as happens with CompactionTrim)
    messages = [
        ChatMessageUser(content="What's the weather in Paris and London?"),
        ChatMessageAssistant(
            content="I'll check the weather for both cities.",
            tool_calls=[
                ToolCall(
                    id="call_paris",
                    function="get_weather",
                    arguments={"location": "Paris, France"},
                ),
                ToolCall(
                    id="call_london",
                    function="get_weather",
                    arguments={"location": "London, UK"},
                ),
            ],
        ),
        # Two separate tool messages (this is what CompactionTrim produces)
        ChatMessageTool(
            content="Weather in Paris: 18°C, sunny",
            tool_call_id="call_paris",
            function="get_weather",
        ),
        ChatMessageTool(
            content="Weather in London: 15°C, cloudy",
            tool_call_id="call_london",
            function="get_weather",
        ),
    ]

    # Count tokens - this should succeed without raising an exception
    # Prior to the fix, this would fail with:
    # "tool_use ids were found without tool_result blocks immediately after"
    token_count = await model.count_tokens(messages)

    # Verify token count is reasonable
    assert token_count >= 20
    assert isinstance(token_count, int)


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


# --- Media token counting tests (no API keys required) ---

TEST_MEDIA_DIR = os.path.join("tests", "util", "test_media")


def _file_to_data_uri(filepath: str, mime_type: str) -> str:
    """Convert a file to a data URI."""
    with open(filepath, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime_type};base64,{data}"


def test_count_image_tokens_low_detail():
    """Test image token counting with low detail."""
    image = ContentImage(image="https://example.com/image.png", detail="low")
    tokens = count_media_tokens(image)
    assert tokens == 85


def test_count_image_tokens_high_detail():
    """Test image token counting with high detail."""
    image = ContentImage(image="https://example.com/image.png", detail="high")
    tokens = count_media_tokens(image)
    assert tokens == 765


def test_count_image_tokens_auto_detail():
    """Test image token counting with auto detail (defaults to high)."""
    image = ContentImage(image="https://example.com/image.png")
    tokens = count_media_tokens(image)
    assert tokens == 765  # auto defaults to high


def test_count_audio_tokens_file_path():
    """Test audio token counting with file path returns fallback."""
    audio = ContentAudio(audio="sample.mp3", format="mp3")
    tokens = count_media_tokens(audio)
    assert tokens == FALLBACK_AUDIO_TOKENS


def test_count_audio_tokens_data_uri_mp3():
    """Test audio token counting with MP3 data URI estimates based on size."""
    filepath = os.path.join(TEST_MEDIA_DIR, "sample.mp3")
    data_uri = _file_to_data_uri(filepath, "audio/mp3")
    audio = ContentAudio(audio=data_uri, format="mp3")

    tokens = count_media_tokens(audio)

    # MP3 is ~27KB, at 16KB/sec that's ~1.7 sec, at 50 tok/sec = ~85 tokens
    # Should be significantly less than fallback (2000)
    assert tokens < FALLBACK_AUDIO_TOKENS
    assert tokens >= 50  # minimum


def test_count_audio_tokens_data_uri_wav():
    """Test audio token counting with WAV data URI estimates based on size."""
    filepath = os.path.join(TEST_MEDIA_DIR, "sample.wav")
    data_uri = _file_to_data_uri(filepath, "audio/wav")
    audio = ContentAudio(audio=data_uri, format="wav")

    tokens = count_media_tokens(audio)

    # WAV is ~97KB, at 176KB/sec that's ~0.55 sec, at 50 tok/sec = ~28 tokens
    # minimum is 50, so should get 50
    assert tokens >= 50  # minimum
    assert tokens < FALLBACK_AUDIO_TOKENS


def test_count_video_tokens_file_path():
    """Test video token counting with file path returns fallback."""
    video = ContentVideo(video="video.mp4", format="mp4")
    tokens = count_media_tokens(video)
    assert tokens == FALLBACK_VIDEO_TOKENS


def test_count_video_tokens_data_uri():
    """Test video token counting with data URI estimates based on size."""
    filepath = os.path.join(TEST_MEDIA_DIR, "video.mp4")
    data_uri = _file_to_data_uri(filepath, "video/mp4")
    video = ContentVideo(video=data_uri, format="mp4")

    tokens = count_media_tokens(video)

    # Video is ~139KB, at 500KB/sec that's ~0.28 sec, at 400 tok/sec = ~112 tokens
    assert tokens >= 100  # minimum
    assert tokens < FALLBACK_VIDEO_TOKENS


def test_count_document_tokens_file_path():
    """Test document token counting with file path returns fallback."""
    document = ContentDocument(document="attention.pdf")
    tokens = count_media_tokens(document)
    assert tokens == FALLBACK_DOCUMENT_TOKENS


def test_count_document_tokens_data_uri():
    """Test document token counting with data URI estimates based on size."""
    filepath = os.path.join(TEST_MEDIA_DIR, "attention.pdf")
    data_uri = _file_to_data_uri(filepath, "application/pdf")
    document = ContentDocument(document=data_uri)

    tokens = count_media_tokens(document)

    # PDF is ~17KB, at 100KB/page that's ~0.17 pages, at 1000 tok/page = ~175 tokens
    assert tokens >= 100  # minimum
    assert tokens < FALLBACK_DOCUMENT_TOKENS
