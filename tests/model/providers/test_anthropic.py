import pytest
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai import Task, eval
from inspect_ai.dataset._dataset import Sample
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    GenerateConfig,
    get_model,
)
from inspect_ai.tool import ToolCall


@pytest.mark.anyio
@skip_if_no_anthropic
async def test_anthropic_api() -> None:
    model = get_model(
        "anthropic/claude-3-7-sonnet-latest",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = "This is a test string. What are you?"
    response = await model.generate(input=message)
    assert len(response.completion) >= 1


@skip_if_no_anthropic
def test_anthropic_effort() -> None:
    log = eval(
        Task(dataset=[Sample(input="Please tell a story about toys.")]),
        model="anthropic/claude-opus-4-5",
        effort="low",
    )[0]
    assert log.status == "success"


@skip_if_no_anthropic
def test_anthropic_should_retry():
    import httpx
    from anthropic import APIStatusError

    # scaffold for should_retry
    model = get_model("anthropic/claude-3-7-sonnet-latest")
    response = httpx.Response(
        status_code=405, request=httpx.Request("GET", "https://example.com")
    )

    # check whether we handle overloaded_error correctly
    ex = APIStatusError(
        "error", response=response, body={"error": {"type": "overloaded_error"}}
    )
    assert model.api.should_retry(ex)

    # check whether we handle body not being a dict (will raise if we don't)
    ex = APIStatusError("error", response=response, body="error")
    model.api.should_retry(ex)

    # check whether we handle error not being a dict (will raise if we don't)
    ex = APIStatusError("error", response=response, body={"error": "error"})
    model.api.should_retry(ex)


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_anthropic_count_tokens_single_tool_call() -> None:
    """Test counting tokens for a single assistant message with one tool call."""
    model = get_model("anthropic/claude-3-7-sonnet-latest")

    # Create an assistant message with a single tool call (no tool result)
    assistant_msg = ChatMessageAssistant(
        content="I'll help you with that.",
        tool_calls=[
            ToolCall(
                id="toolu_test_123",
                function="test_function",
                arguments={"arg1": "value1"},
            )
        ],
    )

    # This should not raise - we're testing token counting for individual messages
    token_count = await model.api.count_tokens([assistant_msg])
    assert token_count > 0


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_anthropic_count_tokens_multiple_tool_calls() -> None:
    """Test counting tokens for a single assistant message with multiple tool calls."""
    model = get_model("anthropic/claude-3-7-sonnet-latest")

    # Create an assistant message with multiple tool calls (no tool results)
    assistant_msg = ChatMessageAssistant(
        content="I'll run multiple tools.",
        tool_calls=[
            ToolCall(
                id="toolu_test_abc",
                function="function_a",
                arguments={"x": 1},
            ),
            ToolCall(
                id="toolu_test_def",
                function="function_b",
                arguments={"y": 2},
            ),
            ToolCall(
                id="toolu_test_ghi",
                function="function_c",
                arguments={"z": 3},
            ),
        ],
    )

    # This should not raise - we're testing token counting for individual messages
    token_count = await model.api.count_tokens([assistant_msg])
    assert token_count > 0


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_anthropic_count_tokens_single_tool_result() -> None:
    """Test counting tokens for a single tool result message (no preceding tool use)."""
    model = get_model("anthropic/claude-3-7-sonnet-latest")

    # Create a tool result message without a preceding assistant message
    tool_msg = ChatMessageTool(
        content="Tool result content here",
        tool_call_id="toolu_test_xyz",
        function="some_function",
    )

    # This should not raise - we're testing token counting for individual messages
    token_count = await model.api.count_tokens([tool_msg])
    assert token_count > 0
