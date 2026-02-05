"""Integration tests for OpenAI token counting with padding.

These tests verify:
1. pad_tool_messages_for_token_counting() handles edge cases correctly
2. Per-message token counting works via the native API
3. count_tokens(list) produces similar results to summing individual counts
"""

import os

import pytest

from inspect_ai.model._openai_responses import (
    is_function_call_output,
    is_response_function_tool_call,
    pad_tool_messages_for_token_counting,
)

# Skip integration tests if no API key is available
requires_openai_api_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


@pytest.fixture
def openai_model():
    """Get an OpenAI model for testing."""
    from inspect_ai.model import get_model

    return get_model("openai/gpt-5.2-codex")


class TestPadToolMessagesForTokenCounting:
    """Unit tests for pad_tool_messages_for_token_counting()."""

    def test_empty_input_returns_empty(self):
        """Empty input should return empty output."""
        result = pad_tool_messages_for_token_counting([])
        assert result == []

    def test_user_message_passes_through(self):
        """User messages should pass through unchanged."""
        messages = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello"}],
            }
        ]
        result = pad_tool_messages_for_token_counting(messages)
        assert len(result) == 1
        assert result[0] == messages[0]

    def test_orphaned_function_call_output_gets_fake_call(self):
        """function_call_output without preceding function_call should get a fake call added."""
        messages = [
            {
                "type": "function_call_output",
                "call_id": "call_123",
                "output": "result",
            }
        ]
        result = pad_tool_messages_for_token_counting(messages)

        # Should have 2 items: fake function_call + original output
        assert len(result) == 2

        # First should be the fake function_call
        assert is_response_function_tool_call(result[0])
        assert result[0]["call_id"] == "call_123"
        assert result[0]["name"] == "placeholder"

        # Second should be the original output
        assert is_function_call_output(result[1])
        assert result[1]["call_id"] == "call_123"

    def test_orphaned_function_call_gets_fake_output(self):
        """function_call without following function_call_output should get a fake output added."""
        messages = [
            {
                "type": "function_call",
                "call_id": "call_456",
                "name": "my_tool",
                "arguments": "{}",
            }
        ]
        result = pad_tool_messages_for_token_counting(messages)

        # Should have 2 items: original call + fake output
        assert len(result) == 2

        # First should be the original function_call
        assert is_response_function_tool_call(result[0])
        assert result[0]["call_id"] == "call_456"
        assert result[0]["name"] == "my_tool"

        # Second should be the fake function_call_output
        assert is_function_call_output(result[1])
        assert result[1]["call_id"] == "call_456"
        assert result[1]["output"] == ""

    def test_properly_paired_calls_pass_through(self):
        """Properly paired function_call + function_call_output should pass through unchanged."""
        messages = [
            {
                "type": "function_call",
                "call_id": "call_789",
                "name": "my_tool",
                "arguments": '{"arg": "value"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_789",
                "output": "tool result",
            },
        ]
        result = pad_tool_messages_for_token_counting(messages)

        # Should pass through unchanged (2 items)
        assert len(result) == 2
        assert result[0] == messages[0]
        assert result[1] == messages[1]

    def test_multiple_orphaned_outputs(self):
        """Multiple orphaned function_call_outputs should each get a fake call."""
        messages = [
            {"type": "function_call_output", "call_id": "call_1", "output": "result1"},
            {"type": "function_call_output", "call_id": "call_2", "output": "result2"},
        ]
        result = pad_tool_messages_for_token_counting(messages)

        # Should have 4 items: fake_call_1, output_1, fake_call_2, output_2
        assert len(result) == 4

        # First pair
        assert is_response_function_tool_call(result[0])
        assert result[0]["call_id"] == "call_1"
        assert is_function_call_output(result[1])
        assert result[1]["call_id"] == "call_1"

        # Second pair
        assert is_response_function_tool_call(result[2])
        assert result[2]["call_id"] == "call_2"
        assert is_function_call_output(result[3])
        assert result[3]["call_id"] == "call_2"

    def test_multiple_orphaned_calls(self):
        """Multiple orphaned function_calls should each get a fake output."""
        messages = [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "tool1",
                "arguments": "{}",
            },
            {
                "type": "function_call",
                "call_id": "call_2",
                "name": "tool2",
                "arguments": "{}",
            },
        ]
        result = pad_tool_messages_for_token_counting(messages)

        # Should have 4 items: call_1, fake_output_1, call_2, fake_output_2
        assert len(result) == 4

        # First pair
        assert is_response_function_tool_call(result[0])
        assert result[0]["call_id"] == "call_1"
        assert is_function_call_output(result[1])
        assert result[1]["call_id"] == "call_1"

        # Second pair
        assert is_response_function_tool_call(result[2])
        assert result[2]["call_id"] == "call_2"
        assert is_function_call_output(result[3])
        assert result[3]["call_id"] == "call_2"

    def test_mixed_paired_and_orphaned(self):
        """Mixed paired and orphaned tool calls should be handled correctly."""
        messages = [
            # Orphaned output
            {
                "type": "function_call_output",
                "call_id": "orphan_out",
                "output": "orphan",
            },
            # Paired call and output
            {
                "type": "function_call",
                "call_id": "paired",
                "name": "tool",
                "arguments": "{}",
            },
            {"type": "function_call_output", "call_id": "paired", "output": "result"},
            # Orphaned call
            {
                "type": "function_call",
                "call_id": "orphan_call",
                "name": "tool2",
                "arguments": "{}",
            },
        ]
        result = pad_tool_messages_for_token_counting(messages)

        # Expected: fake_call, orphan_out, paired_call, paired_out, orphan_call, fake_out
        assert len(result) == 6

        # Fake call for orphan output
        assert is_response_function_tool_call(result[0])
        assert result[0]["call_id"] == "orphan_out"

        # Orphan output
        assert is_function_call_output(result[1])
        assert result[1]["call_id"] == "orphan_out"

        # Paired call
        assert is_response_function_tool_call(result[2])
        assert result[2]["call_id"] == "paired"

        # Paired output
        assert is_function_call_output(result[3])
        assert result[3]["call_id"] == "paired"

        # Orphan call
        assert is_response_function_tool_call(result[4])
        assert result[4]["call_id"] == "orphan_call"

        # Fake output for orphan call
        assert is_function_call_output(result[5])
        assert result[5]["call_id"] == "orphan_call"


@requires_openai_api_key
@pytest.mark.slow
@pytest.mark.calls_llm
class TestPerMessageTokenCounting:
    """Integration tests for per-message token counting with OpenAI."""

    @pytest.mark.asyncio
    async def test_user_message_counts_correctly(self, openai_model):
        """User message should count tokens correctly."""
        from inspect_ai.model._chat_message import ChatMessageUser

        message = ChatMessageUser(content="Hello, how are you today?")
        count = await openai_model.count_tokens([message])

        # Should be a reasonable positive number
        assert count > 0
        assert count < 100  # Simple message shouldn't be too long

    @pytest.mark.asyncio
    async def test_assistant_message_with_tool_call_counts(self, openai_model):
        """Assistant message with tool call should count via padding."""
        from inspect_ai.model._chat_message import ChatMessageAssistant
        from inspect_ai.tool._tool_call import ToolCall

        message = ChatMessageAssistant(
            content="I'll help you with that.",
            tool_calls=[
                ToolCall(
                    id="call_test123",
                    function="get_weather",
                    arguments={"location": "San Francisco"},
                    type="function",
                )
            ],
        )
        count = await openai_model.count_tokens([message])

        # Should be a reasonable positive number
        assert count > 0
        assert count < 500

    @pytest.mark.asyncio
    async def test_tool_result_message_counts(self, openai_model):
        """Tool result message should count via padding."""
        from inspect_ai.model._chat_message import ChatMessageTool

        message = ChatMessageTool(
            content="The weather in San Francisco is 72°F and sunny.",
            tool_call_id="call_test123",
            function="get_weather",
        )
        count = await openai_model.count_tokens([message])

        # Should be a reasonable positive number
        assert count > 0
        assert count < 500

    @pytest.mark.asyncio
    async def test_string_input_uses_text_counting(self, openai_model):
        """String input should use text token counting."""
        text = "This is a simple text string for token counting."
        count = await openai_model.count_tokens(text)

        # Should be a reasonable positive number
        assert count > 0
        assert count < 50


@requires_openai_api_key
@pytest.mark.slow
@pytest.mark.calls_llm
class TestBatchCountingSumsPerMessage:
    """Tests verifying count_tokens(list) produces similar results to summing individual counts."""

    @pytest.mark.asyncio
    async def test_batch_count_approximately_matches_sum(self, openai_model):
        """Batch count should approximately match sum of individual counts."""
        from inspect_ai.model._chat_message import (
            ChatMessageAssistant,
            ChatMessageUser,
        )

        messages = [
            ChatMessageUser(content="What's the weather like?"),
            ChatMessageAssistant(content="I'll check that for you."),
            ChatMessageUser(content="Thanks! Also, what time is it?"),
            ChatMessageAssistant(content="Let me find out."),
        ]

        # Count individually
        individual_counts = []
        for msg in messages:
            count = await openai_model.count_tokens([msg])
            individual_counts.append(count)

        sum_of_individual = sum(individual_counts)

        # Count as batch (count_tokens accepts list[ChatMessage])
        batch_count = await openai_model.count_tokens(messages)

        # They should be approximately equal
        # Allow some variance due to message boundary tokens
        assert abs(batch_count - sum_of_individual) <= sum_of_individual * 0.1

    @pytest.mark.asyncio
    async def test_batch_count_with_tool_calls(self, openai_model):
        """Batch count with tool calls should work correctly."""
        from inspect_ai.model._chat_message import (
            ChatMessageAssistant,
            ChatMessageTool,
            ChatMessageUser,
        )
        from inspect_ai.tool._tool_call import ToolCall

        messages = [
            ChatMessageUser(content="What's the weather in Paris?"),
            ChatMessageAssistant(
                content="I'll check that.",
                tool_calls=[
                    ToolCall(
                        id="call_weather",
                        function="get_weather",
                        arguments={"location": "Paris"},
                        type="function",
                    )
                ],
            ),
            ChatMessageTool(
                content="Paris: 18°C, partly cloudy",
                tool_call_id="call_weather",
                function="get_weather",
            ),
            ChatMessageAssistant(
                content="The weather in Paris is 18°C and partly cloudy."
            ),
        ]

        # This should not raise an error - padding handles orphaned tool calls
        batch_count = await openai_model.count_tokens(messages)

        # Should return a reasonable count
        assert batch_count > 0
        assert batch_count < 1000


@requires_openai_api_key
@pytest.mark.slow
@pytest.mark.calls_llm
class TestNativeTokenCountingFallback:
    """Tests for native token counting with fallback behavior."""

    @pytest.mark.asyncio
    async def test_native_counting_returns_reasonable_values(self, openai_model):
        """Native token counting should return reasonable values."""
        from inspect_ai.model._chat_message import ChatMessageUser

        # Short message
        short_msg = ChatMessageUser(content="Hi")
        short_count = await openai_model.count_tokens([short_msg])

        # Longer message
        long_msg = ChatMessageUser(
            content="This is a much longer message that contains many more words and should therefore have a significantly higher token count than the short message above."
        )
        long_count = await openai_model.count_tokens([long_msg])

        # Long message should have more tokens
        assert long_count > short_count

        # Both should be positive
        assert short_count > 0
        assert long_count > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
