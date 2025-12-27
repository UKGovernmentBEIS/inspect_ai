import shutil

import pytest

from inspect_ai.model import GenerateConfig, get_model


def skip_if_no_claude_code(func):
    """Skip test if Claude Code CLI is not available."""
    return pytest.mark.skipif(
        shutil.which("claude") is None,
        reason="Claude Code CLI not installed",
    )(func)


@pytest.mark.anyio
@skip_if_no_claude_code
async def test_claude_code_api() -> None:
    """Test basic Claude Code API functionality."""
    model = get_model(
        "claude-code/sonnet",
        config=GenerateConfig(
            max_tokens=50,
            temperature=0.0,
        ),
    )

    message = "What is 2 + 2? Answer with just the number."
    response = await model.generate(input=message)
    assert len(response.completion) >= 1
    assert "4" in response.completion


@skip_if_no_claude_code
def test_claude_code_max_connections() -> None:
    """Test that max_connections defaults to 1 and can be configured."""
    # Default is 1
    model = get_model("claude-code/sonnet")
    assert model.api.max_connections() == 1

    # Can be configured via model args
    model_parallel = get_model("claude-code/sonnet", max_connections=10)
    assert model_parallel.api.max_connections() == 10


def test_claude_code_model_aliases() -> None:
    """Test that model aliases are resolved correctly."""
    from inspect_ai.model._providers.claude_code import MODEL_ALIASES

    assert MODEL_ALIASES["sonnet"] == "claude-sonnet-4-5-20250929"
    assert MODEL_ALIASES["opus"] == "claude-opus-4-5-20251101"
    assert MODEL_ALIASES["haiku"] == "claude-haiku-4-5-20251001"
    assert MODEL_ALIASES["default"] is None


def test_claude_code_messages_to_prompt() -> None:
    """Test message conversion to prompt string."""
    from inspect_ai.model._chat_message import (
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageUser,
    )
    from inspect_ai.model._providers.claude_code import messages_to_prompt

    messages = [
        ChatMessageSystem(content="You are a helpful assistant."),
        ChatMessageUser(content="Hello"),
        ChatMessageAssistant(content="Hi there!", model="test", source="generate"),
    ]

    prompt = messages_to_prompt(messages)
    assert "[System]: You are a helpful assistant." in prompt
    assert "[User]: Hello" in prompt
    assert "[Assistant]: Hi there!" in prompt
