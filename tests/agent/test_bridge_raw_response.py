"""Tests for agent_bridge() support of `with_raw_response` callers.

Some OpenAI clients (notably langchain-openai) issue requests via
`client.chat.completions.with_raw_response.create(...)` so they can read
response headers, then call `.parse()` on the returned wrapper to obtain the
`ChatCompletion`. The bridge intercepts `AsyncAPIClient.request()`, so it must
return a response *wrapper* (not the parsed model) for these callers — otherwise
they crash with `'ChatCompletion' object has no attribute 'parse'` (issue #4341).
"""

from typing import cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.model._openai import messages_to_openai
from inspect_ai.scorer import includes

ANSWER = "the answer is 42"


@agent
def raw_response_agent() -> Agent:
    """Bridge agent that consumes the response via `with_raw_response` + `.parse()`."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            async with AsyncOpenAI() as client:
                raw = await client.chat.completions.with_raw_response.create(
                    model="inspect",
                    messages=await messages_to_openai(bridge.state.messages),
                )
                # langchain-openai reads headers off the raw wrapper...
                assert raw.headers is not None
                # ...then parses it into a ChatCompletion
                completion = cast(ChatCompletion, raw.parse())
                assert isinstance(completion, ChatCompletion)
                assert completion.choices[0].message.content == ANSWER
            return bridge.state

    return execute


def run_raw_response_agent() -> EvalLog:
    task = Task(
        dataset=[Sample(input="What is the answer?", target=ANSWER)],
        solver=raw_response_agent(),
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", ANSWER)],
    )
    return eval(task, model=model)[0]


@skip_if_no_openai
def test_bridge_with_raw_response_parses() -> None:
    """`with_raw_response.create().parse()` works through the bridge (issue #4341)."""
    log = run_raw_response_agent()
    assert log.status == "success", (
        log.error.message if log.error else "eval did not succeed"
    )


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
def test_bridge_plain_create_still_returns_model() -> None:
    """Plain `.create()` continues to return a parsed `ChatCompletion` (no regression)."""
    task = Task(
        dataset=[Sample(input="What is the answer?", target=ANSWER)],
        solver=plain_response_agent(),
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", ANSWER)],
    )
    log = eval(task, model=model)[0]
    assert log.status == "success", (
        log.error.message if log.error else "eval did not succeed"
    )


@agent
def raw_response_tool_call_agent() -> Agent:
    """Bridge agent that parses a tool-call completion via `with_raw_response`."""

    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            async with AsyncOpenAI() as client:
                raw = await client.chat.completions.with_raw_response.create(
                    model="inspect",
                    messages=await messages_to_openai(bridge.state.messages),
                )
                completion = cast(ChatCompletion, raw.parse())
                # the round-trip must preserve the tool call, not just text
                tool_calls = completion.choices[0].message.tool_calls
                assert tool_calls is not None and len(tool_calls) == 1
                assert tool_calls[0].function.name == "get_weather"
                assert "London" in tool_calls[0].function.arguments
            return bridge.state

    return execute


@skip_if_no_openai
def test_bridge_with_raw_response_preserves_tool_calls() -> None:
    """A tool-call completion survives the `model_dump_json()` → `.parse()` round-trip."""
    task = Task(
        dataset=[Sample(input="What is the weather?", target="done")],
        solver=raw_response_tool_call_agent(),
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="get_weather",
                tool_arguments={"city": "London"},
            )
        ],
    )
    log = eval(task, model=model)[0]
    assert log.status == "success", (
        log.error.message if log.error else "eval did not succeed"
    )
