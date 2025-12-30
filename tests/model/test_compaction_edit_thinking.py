"""Integration tests for thinking compaction across multiple providers.

These tests verify that stripping thinking blocks from message history
doesn't cause runtime errors across OpenAI, Anthropic, Google, Mistral, and Grok.
"""

from typing import Any

import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_grok,
    skip_if_no_mistral,
    skip_if_no_openai,
)

from inspect_ai._util.content import ContentReasoning
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    execute_tools,
    get_model,
)
from inspect_ai.model._compaction.edit import CompactionEdit
from inspect_ai.tool import tool


@tool
def get_weather():
    """Get the current weather for a location."""

    async def run(location: str) -> str:
        """Get the current weather for a location.

        Args:
            location: Location to get the whether for (e.g. 'Boston')
        """
        return f"The weather in {location} is sunny and 22°C."

    return run


async def check_thinking_compaction(
    model_name: str, config: GenerateConfig, **model_args: Any
) -> None:
    """Test that thinking blocks can be safely removed from history without errors.

    Args:
        model_name: Model identifier (e.g., "openai/o1", "anthropic/claude-sonnet-4-5")
        config: GenerateConfig with reasoning parameters
        model_args: Additional model args.
    """
    model = get_model(model_name, **model_args)
    tools = [get_weather()]

    # Step 1: System prompt that STRONGLY requires tool use + user prompt
    messages: list[ChatMessage] = [
        ChatMessageSystem(
            content="You are a helpful assistant. You MUST use the get_weather tool "
            "to answer any questions about weather. ALWAYS call the tool first, "
            "never guess or make up weather information."
        ),
        ChatMessageUser(
            content="What's the weather like in Paris? After you check, suggest some activities."
        ),
    ]

    output1 = await model.generate(
        input=messages,
        tools=tools,
        config=config,
    )
    messages.append(output1.message)

    # Verify we got thinking content
    has_reasoning = False
    if isinstance(output1.message.content, list):
        has_reasoning = any(
            isinstance(c, ContentReasoning) for c in output1.message.content
        )
    assert (
        has_reasoning or (output1.usage and output1.usage.reasoning_tokens or 0) > 0
    ), "Model did not produce thinking"

    # Step 2: Execute tool calls if present
    if output1.message.tool_calls:
        result = await execute_tools(messages, tools)
        messages.extend(result.messages)

        # Step 3: Ask follow-up question
        messages.append(
            ChatMessageUser(content="What other activities would you suggest?")
        )

        output2 = await model.generate(
            input=messages,
            tools=tools,
            config=config,
        )
        messages.append(output2.message)

    # Step 4: Add thank you message
    messages.append(ChatMessageUser(content="Thank you for the suggestions!"))

    # Step 5: Compact history - remove ALL thinking blocks
    strategy = CompactionEdit(
        threshold=1.0,  # Always trigger
        keep_thinking_turns=1,  # Remove all but last thinking
        keep_tool_uses=10,  # Keep tool uses
    )
    # Set the model so CompactionEdit can check compact_reasoning_history()
    compacted_messages, _ = await strategy.compact(messages, model)

    # Verify thinking was removed (only if provider supports it)
    thinking_turns = 0
    if model.api.compact_reasoning_history():
        for msg in compacted_messages:
            if isinstance(msg, ChatMessageAssistant) and isinstance(msg.content, list):
                if any([isinstance(c, ContentReasoning) for c in msg.content]):
                    thinking_turns += 1
    assert thinking_turns == 1, "Thinking blocks should have been removed"

    # Step 6: Call model with compacted history
    compacted_messages.append(
        ChatMessageUser(
            content="One more question: what should I pack for this weather?"
        )
    )

    # Step 7: This should NOT raise an error
    output_final = await model.generate(
        input=compacted_messages,
        tools=tools,
        config=config,
    )

    # Verify we got a valid response
    assert output_final.message is not None
    assert output_final.stop_reason in ("stop", "tool_calls")


@skip_if_no_openai
@pytest.mark.slow
@pytest.mark.asyncio
async def test_thinking_compaction_openai() -> None:
    await check_thinking_compaction(
        "openai/gpt-5-mini",
        GenerateConfig(reasoning_effort="low"),
    )


@skip_if_no_anthropic
@pytest.mark.slow
@pytest.mark.asyncio
async def test_thinking_compaction_anthropic() -> None:
    await check_thinking_compaction(
        "anthropic/claude-sonnet-4-5",
        GenerateConfig(reasoning_tokens=2000),
    )


@skip_if_no_google
@pytest.mark.slow
@pytest.mark.asyncio
async def test_thinking_compaction_google() -> None:
    # Note: Google doesn't support thinking compaction (compact_reasoning_history returns False)
    # This test verifies the behavior is handled gracefully
    await check_thinking_compaction(
        "google/gemini-3-pro-preview",
        GenerateConfig(reasoning_effort="low"),
    )


@skip_if_no_mistral
@pytest.mark.slow
@pytest.mark.asyncio
async def test_thinking_compaction_mistral() -> None:
    await check_thinking_compaction(
        "mistral/magistral-small-2506",
        GenerateConfig(reasoning_effort="low"),
        conversation_api=False,
    )


@skip_if_no_grok
@pytest.mark.slow
@pytest.mark.asyncio
async def test_thinking_compaction_grok() -> None:
    await check_thinking_compaction(
        "grok/grok-3-mini",
        GenerateConfig(reasoning_effort="low"),
    )
