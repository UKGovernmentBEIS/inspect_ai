"""End-to-end tests for server-side tool compaction.

These tests verify that clearing server-side tool results (web_search, web_fetch,
code_execution) doesn't cause 400 errors when sending compacted messages back to
the API.

The server-side tools create special block types that must be reconstructed
correctly after compaction to avoid API validation errors.
"""

from typing import Any

import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_openai,
)

from inspect_ai._util.content import ContentToolUse
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._compaction.edit import TOOL_RESULT_REMOVED, CompactionEdit
from inspect_ai.tool import Tool, ToolDef, ToolResult


def _create_web_search_tool(provider: str) -> Tool:
    """Create a web_search tool configured for the specified provider.

    Args:
        provider: Either "anthropic" or "openai"

    Returns:
        A web_search tool that will use the provider's native implementation.
    """

    async def execute(query: str) -> ToolResult:
        """Search the web for information.

        Args:
            query: The search query.
        """
        # This should never be called - the provider handles it natively
        return f"Search results for: {query}"

    options: dict[str, Any] = {}
    if provider == "anthropic":
        options["anthropic"] = {}  # Empty dict enables native web search
    elif provider == "openai":
        options["openai"] = {}  # Empty dict enables native web search

    return ToolDef(execute, name="web_search", options=options).as_tool()


def _count_server_tool_uses(messages: list[ChatMessage]) -> tuple[int, int]:
    """Count server-side tool uses and how many have cleared results.

    Args:
        messages: List of chat messages to check

    Returns:
        Tuple of (total_server_tool_uses, cleared_results_count)
    """
    total = 0
    cleared = 0
    for msg in messages:
        if isinstance(msg, ChatMessageAssistant) and isinstance(msg.content, list):
            for c in msg.content:
                if isinstance(c, ContentToolUse) and c.tool_type in (
                    "web_search",
                    "code_execution",
                ):
                    total += 1
                    if c.result == TOOL_RESULT_REMOVED:
                        cleared += 1
    return total, cleared


async def check_server_tool_compaction(
    model_name: str,
    tools: list[Tool],
    config: GenerateConfig | None = None,
    prompt: str = "Search the web for the current weather in Paris and tell me what you find.",
) -> None:
    """Test that server-side tool results can be compacted without causing API errors.

    Args:
        model_name: Model identifier
        tools: Tools to use (should include server-side tools like web_search)
        config: Optional GenerateConfig
        prompt: The prompt to send to the model
    """
    model = get_model(model_name)
    config = config or GenerateConfig()

    # Step 1: Initial request with server-side tools
    messages: list[ChatMessage] = [
        ChatMessageSystem(
            content="You are a helpful assistant. When asked about current information, "
            "use the web_search tool to find up-to-date information."
        ),
        ChatMessageUser(content=prompt),
    ]

    output1 = await model.generate(
        input=messages,
        tools=tools,
        config=config,
    )
    messages.append(output1.message)

    # Check if the model used server-side tools
    has_server_tool_use = False
    if isinstance(output1.message.content, list):
        has_server_tool_use = any(
            isinstance(c, ContentToolUse)
            and c.tool_type in ("web_search", "code_execution")
            for c in output1.message.content
        )

    if not has_server_tool_use:
        pytest.skip("Model did not use server-side tools - cannot test compaction")

    # Step 2: Follow-up to build more history
    messages.append(
        ChatMessageUser(
            content="Thanks! Can you also search for the weather in London?"
        )
    )

    output2 = await model.generate(
        input=messages,
        tools=tools,
        config=config,
    )
    messages.append(output2.message)

    # Step 3: Another follow-up
    messages.append(ChatMessageUser(content="Which city has better weather today?"))

    output3 = await model.generate(
        input=messages,
        tools=tools,
        config=config,
    )
    messages.append(output3.message)

    # Count server tool uses before compaction
    total_before, cleared_before = _count_server_tool_uses(messages)
    assert total_before > 0, "Expected at least one server tool use"
    assert cleared_before == 0, "No results should be cleared before compaction"

    # Step 4: Compact history - clear older tool results
    strategy = CompactionEdit(
        threshold=1.0,  # Always trigger
        keep_thinking_turns=10,  # Keep thinking (not what we're testing)
        keep_tool_uses=1,  # Clear older tool results, keep only most recent
    )
    compacted_messages, _ = await strategy.compact(messages, model)

    # Verify that tool results were actually cleared
    total_after, cleared_after = _count_server_tool_uses(compacted_messages)
    assert total_after == total_before, "Total tool uses should be unchanged"

    # If we had multiple tool uses, at least some should be cleared
    if total_before > 1:
        assert cleared_after > 0, (
            f"Expected some tool results to be cleared. "
            f"Total: {total_before}, Cleared: {cleared_after}"
        )
        # With keep_tool_uses=1, all but one should be cleared
        assert cleared_after >= total_before - 1, (
            f"Expected at least {total_before - 1} results cleared, got {cleared_after}"
        )

    # Step 5: Final request with compacted history - THIS SHOULD NOT CAUSE 400 ERROR
    compacted_messages.append(
        ChatMessageUser(
            content="One more question: what should I pack for this weather?"
        )
    )

    output_final = await model.generate(
        input=compacted_messages,
        tools=tools,
        config=config,
    )

    # Verify we got a valid response (no 400 error)
    assert output_final.message is not None
    assert output_final.stop_reason in ("stop", "tool_calls", "end_turn")


@skip_if_no_anthropic
@pytest.mark.slow
@pytest.mark.asyncio
async def test_server_tool_compaction_anthropic_web_search() -> None:
    """Test Anthropic native web_search tool compaction doesn't cause 400 errors."""
    tools = [_create_web_search_tool("anthropic")]
    await check_server_tool_compaction(
        "anthropic/claude-sonnet-4-20250514",
        tools=tools,
    )


@skip_if_no_openai
@pytest.mark.slow
@pytest.mark.asyncio
async def test_server_tool_compaction_openai_web_search() -> None:
    """Test OpenAI native web_search tool compaction doesn't cause 400 errors."""
    tools = [_create_web_search_tool("openai")]
    await check_server_tool_compaction(
        "openai/gpt-4.1",
        tools=tools,
    )


@skip_if_no_anthropic
@pytest.mark.slow
@pytest.mark.asyncio
async def test_server_tool_compaction_anthropic_with_thinking() -> None:
    """Test Anthropic server tool compaction combined with thinking compaction."""
    tools = [_create_web_search_tool("anthropic")]
    await check_server_tool_compaction(
        "anthropic/claude-sonnet-4-5",
        tools=tools,
        config=GenerateConfig(reasoning_tokens=2000),
    )
