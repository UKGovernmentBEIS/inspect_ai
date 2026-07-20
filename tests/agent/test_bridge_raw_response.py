"""Tests for agent_bridge() support of `with_raw_response` callers.

Some OpenAI clients (notably langchain-openai) issue requests via
`client.chat.completions.with_raw_response.create(...)` so they can read
response headers, then call `.parse()` on the returned wrapper to obtain the
`ChatCompletion`. The bridge intercepts `AsyncAPIClient.request()`, so it must
return a response *wrapper* (not the parsed model) for these callers — otherwise
they crash with `'ChatCompletion' object has no attribute 'parse'` (issue #4341).

The Anthropic SDK shares the same generated client core, so its bridge patch has
the identical failure mode (`'Message' object has no attribute 'parse'`) and is
covered here too.
"""

from anthropic import AsyncAnthropic
from anthropic.types import Message as AnthropicMessage
from anthropic.types import TextBlock, ToolUseBlock
from anthropic.types.beta import BetaMessage, BetaTextBlock
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageFunctionToolCall,
)
from openai.types.responses import Response
from test_helpers.utils import skip_if_no_anthropic_package, skip_if_no_openai_package

from inspect_ai import Task, eval
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.model._openai import messages_to_openai
from inspect_ai.scorer import includes

ANSWER = "the answer is 42"


def bridge_client() -> AsyncOpenAI:
    """Client for bridge tests: requests are intercepted, so the key is unused."""
    return AsyncOpenAI(api_key="test")


def run_bridge_test(solver: Agent, model_output: ModelOutput) -> None:
    """Run a single-sample bridge agent over mockllm and assert it succeeded.

    Assertions in the agents below raise on failure, which surfaces as a
    non-success eval status.
    """
    task = Task(
        dataset=[Sample(input="hello", target="done")],
        solver=solver,
        scorer=includes(),
    )
    model = get_model("mockllm/model", custom_outputs=[model_output])
    log = eval(task, model=model)[0]
    assert log.status == "success", (
        log.error.message if log.error else "eval did not succeed"
    )


async def consume_raw_response(bridge_state: AgentState) -> ChatCompletion:
    """Drive the `with_raw_response` + `.parse()` path langchain-openai uses."""
    async with bridge_client() as client:
        raw = await client.chat.completions.with_raw_response.create(
            model="inspect",
            messages=await messages_to_openai(bridge_state.messages),
        )
        # langchain-openai reads headers off the raw wrapper, then parses it
        assert raw.headers is not None
        completion = raw.parse()
        assert isinstance(completion, ChatCompletion)
        return completion


@agent
def raw_response_agent() -> Agent:
    """Bridge agent that asserts a text completion survives the round-trip."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            completion = await consume_raw_response(bridge.state)
            assert completion.choices[0].message.content == ANSWER
            return bridge.state

    return execute


@agent
def raw_response_tool_call_agent() -> Agent:
    """Bridge agent that asserts a tool-call completion survives the round-trip."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            completion = await consume_raw_response(bridge.state)
            tool_calls = completion.choices[0].message.tool_calls
            assert tool_calls is not None and len(tool_calls) == 1
            tool_call = tool_calls[0]
            assert isinstance(tool_call, ChatCompletionMessageFunctionToolCall)
            assert tool_call.function.name == "get_weather"
            assert "London" in tool_call.function.arguments
            return bridge.state

    return execute


@agent
def raw_response_responses_api_agent() -> Agent:
    """Bridge agent that drives the `/responses` half of the bridge."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            async with bridge_client() as client:
                raw = await client.responses.with_raw_response.create(
                    model="inspect",
                    input="hello",
                )
                assert raw.headers is not None
                response = raw.parse()
                assert isinstance(response, Response)
                assert response.output_text == ANSWER
            return bridge.state

    return execute


@agent
def streaming_response_agent() -> Agent:
    """Bridge agent using `with_streaming_response`, which takes the other branch.

    `with_streaming_response` sends `X-Stainless-Raw-Response: stream` rather
    than `"true"`, which `_process_response()` handles differently from the
    `with_raw_response` case.
    """

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            async with bridge_client() as client:
                async with client.chat.completions.with_streaming_response.create(
                    model="inspect",
                    messages=await messages_to_openai(bridge.state.messages),
                ) as raw:
                    assert raw.headers is not None
                    # unlike the legacy raw wrapper, this one parses async
                    completion = await raw.parse()
                    assert isinstance(completion, ChatCompletion)
                    assert completion.choices[0].message.content == ANSWER
            return bridge.state

    return execute


@agent
def plain_response_agent() -> Agent:
    """Bridge agent that uses a plain `.create()` (must still return the model)."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            async with bridge_client() as client:
                completion = await client.chat.completions.create(
                    model="inspect",
                    messages=await messages_to_openai(bridge.state.messages),
                )
                assert isinstance(completion, ChatCompletion)
                assert completion.choices[0].message.content == ANSWER
            return bridge.state

    return execute


@skip_if_no_openai_package
def test_bridge_with_raw_response_parses() -> None:
    """`with_raw_response.create().parse()` works through the bridge (issue #4341)."""
    run_bridge_test(
        raw_response_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )


@skip_if_no_openai_package
def test_bridge_plain_create_still_returns_model() -> None:
    """Plain `.create()` continues to return a parsed `ChatCompletion` (no regression)."""
    run_bridge_test(
        plain_response_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )


@skip_if_no_openai_package
def test_bridge_with_raw_response_preserves_tool_calls() -> None:
    """A tool-call completion survives the `model_dump_json()` → `.parse()` round-trip."""
    run_bridge_test(
        raw_response_tool_call_agent(),
        ModelOutput.for_tool_call(
            "mockllm/model",
            tool_name="get_weather",
            tool_arguments={"city": "London"},
        ),
    )


@skip_if_no_openai_package
def test_bridge_with_raw_response_responses_api() -> None:
    """The `/responses` branch also returns a wrapper for `with_raw_response`."""
    run_bridge_test(
        raw_response_responses_api_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )


@skip_if_no_openai_package
def test_bridge_with_streaming_response_parses() -> None:
    """`with_streaming_response` takes the other `_process_response()` branch."""
    run_bridge_test(
        streaming_response_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )


def anthropic_bridge_client() -> AsyncAnthropic:
    """Client for bridge tests: requests are intercepted, so the key is unused."""
    return AsyncAnthropic(api_key="test")


ANTHROPIC_MESSAGES = [{"role": "user", "content": "hello"}]


async def consume_anthropic_raw_response(bridge_state: AgentState) -> AnthropicMessage:
    """Drive the `with_raw_response` + `.parse()` path through the Anthropic patch."""
    async with anthropic_bridge_client() as client:
        raw = await client.messages.with_raw_response.create(
            model="inspect",
            max_tokens=1024,
            messages=ANTHROPIC_MESSAGES,  # type: ignore[arg-type]
        )
        assert raw.headers is not None
        message = raw.parse()
        assert isinstance(message, AnthropicMessage)
        return message


@agent
def anthropic_raw_response_agent() -> Agent:
    """Bridge agent that asserts a text message survives the round-trip."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            message = await consume_anthropic_raw_response(bridge.state)
            block = message.content[0]
            assert isinstance(block, TextBlock)
            assert block.text == ANSWER
            return bridge.state

    return execute


@agent
def anthropic_raw_response_tool_use_agent() -> Agent:
    """Bridge agent that asserts a tool-use message survives the round-trip."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            message = await consume_anthropic_raw_response(bridge.state)
            tool_use = [b for b in message.content if isinstance(b, ToolUseBlock)]
            assert len(tool_use) == 1
            assert tool_use[0].name == "get_weather"
            tool_input = tool_use[0].input
            assert isinstance(tool_input, dict)
            assert tool_input["city"] == "London"
            return bridge.state

    return execute


@agent
def anthropic_raw_response_beta_agent() -> Agent:
    """Bridge agent that drives the beta endpoint half of the Anthropic patch."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            async with anthropic_bridge_client() as client:
                raw = await client.beta.messages.with_raw_response.create(
                    model="inspect",
                    max_tokens=1024,
                    messages=ANTHROPIC_MESSAGES,  # type: ignore[arg-type]
                )
                assert raw.headers is not None
                message = raw.parse()
                assert isinstance(message, BetaMessage)
                block = message.content[0]
                assert isinstance(block, BetaTextBlock)
                assert block.text == ANSWER
            return bridge.state

    return execute


@agent
def anthropic_streaming_response_agent() -> Agent:
    """Bridge agent using `with_streaming_response`, which takes the other branch."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            async with anthropic_bridge_client() as client:
                async with client.messages.with_streaming_response.create(
                    model="inspect",
                    max_tokens=1024,
                    messages=ANTHROPIC_MESSAGES,  # type: ignore[arg-type]
                ) as raw:
                    assert raw.headers is not None
                    # unlike the legacy raw wrapper, this one parses async
                    message = await raw.parse()
                    assert isinstance(message, AnthropicMessage)
                    block = message.content[0]
                    assert isinstance(block, TextBlock)
                    assert block.text == ANSWER
            return bridge.state

    return execute


@agent
def anthropic_plain_response_agent() -> Agent:
    """Bridge agent that uses a plain `.create()` (must still return the model)."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            async with anthropic_bridge_client() as client:
                message = await client.messages.create(
                    model="inspect",
                    max_tokens=1024,
                    messages=ANTHROPIC_MESSAGES,  # type: ignore[arg-type]
                )
                assert isinstance(message, AnthropicMessage)
                block = message.content[0]
                assert isinstance(block, TextBlock)
                assert block.text == ANSWER
            return bridge.state

    return execute


@skip_if_no_anthropic_package
def test_anthropic_bridge_with_raw_response_parses() -> None:
    """`with_raw_response.create().parse()` works through the Anthropic patch."""
    run_bridge_test(
        anthropic_raw_response_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )


@skip_if_no_anthropic_package
def test_anthropic_bridge_plain_create_still_returns_model() -> None:
    """Plain `.create()` continues to return a parsed `Message` (no regression)."""
    run_bridge_test(
        anthropic_plain_response_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )


@skip_if_no_anthropic_package
def test_anthropic_bridge_with_raw_response_preserves_tool_use() -> None:
    """A tool-use message survives the `model_dump_json()` → `.parse()` round-trip."""
    run_bridge_test(
        anthropic_raw_response_tool_use_agent(),
        ModelOutput.for_tool_call(
            "mockllm/model",
            tool_name="get_weather",
            tool_arguments={"city": "London"},
        ),
    )


@skip_if_no_anthropic_package
def test_anthropic_bridge_with_raw_response_beta_endpoint() -> None:
    """The beta endpoint branch also returns a wrapper for `with_raw_response`."""
    run_bridge_test(
        anthropic_raw_response_beta_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )


@skip_if_no_anthropic_package
def test_anthropic_bridge_with_streaming_response_parses() -> None:
    """`with_streaming_response` takes the other `_process_response()` branch."""
    run_bridge_test(
        anthropic_streaming_response_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )
