"""Tests for agent_bridge() support of `with_raw_response` callers.

Some OpenAI clients (notably langchain-openai) issue requests via
`client.chat.completions.with_raw_response.create(...)` so they can read
response headers, then call `.parse()` on the returned wrapper to obtain the
`ChatCompletion`. The bridge intercepts `AsyncAPIClient.request()`, so it must
return a response *wrapper* (not the parsed model) for these callers — otherwise
they crash with `'ChatCompletion' object has no attribute 'parse'` (issue #4341).
"""

from collections.abc import Callable

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageFunctionToolCall,
)
from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.model._openai import messages_to_openai
from inspect_ai.scorer import includes

ANSWER = "the answer is 42"


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


async def consume_raw_response(
    bridge_state: AgentState, check: Callable[[ChatCompletion], None]
) -> None:
    """Drive the `with_raw_response` + `.parse()` path langchain-openai uses."""
    async with AsyncOpenAI() as client:
        raw = await client.chat.completions.with_raw_response.create(
            model="inspect",
            messages=await messages_to_openai(bridge_state.messages),
        )
        # langchain-openai reads headers off the raw wrapper, then parses it
        assert raw.headers is not None
        completion = raw.parse()
        assert isinstance(completion, ChatCompletion)
        check(completion)


@agent
def raw_response_agent() -> Agent:
    """Bridge agent that asserts a text completion survives the round-trip."""

    def check(completion: ChatCompletion) -> None:
        assert completion.choices[0].message.content == ANSWER

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            await consume_raw_response(bridge.state, check)
            return bridge.state

    return execute


@agent
def raw_response_tool_call_agent() -> Agent:
    """Bridge agent that asserts a tool-call completion survives the round-trip."""

    def check(completion: ChatCompletion) -> None:
        tool_calls = completion.choices[0].message.tool_calls
        assert tool_calls is not None and len(tool_calls) == 1
        tool_call = tool_calls[0]
        assert isinstance(tool_call, ChatCompletionMessageFunctionToolCall)
        assert tool_call.function.name == "get_weather"
        assert "London" in tool_call.function.arguments

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            await consume_raw_response(bridge.state, check)
            return bridge.state

    return execute


@agent
def plain_response_agent() -> Agent:
    """Bridge agent that uses a plain `.create()` (must still return the model)."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            async with AsyncOpenAI() as client:
                completion = await client.chat.completions.create(
                    model="inspect",
                    messages=await messages_to_openai(bridge.state.messages),
                )
                assert isinstance(completion, ChatCompletion)
                assert completion.choices[0].message.content == ANSWER
            return bridge.state

    return execute


@skip_if_no_openai
def test_bridge_with_raw_response_parses() -> None:
    """`with_raw_response.create().parse()` works through the bridge (issue #4341)."""
    run_bridge_test(
        raw_response_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )


@skip_if_no_openai
def test_bridge_plain_create_still_returns_model() -> None:
    """Plain `.create()` continues to return a parsed `ChatCompletion` (no regression)."""
    run_bridge_test(
        plain_response_agent(),
        ModelOutput.from_content("mockllm/model", ANSWER),
    )


@skip_if_no_openai
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
