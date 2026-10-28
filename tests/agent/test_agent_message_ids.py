"""Message ids stay the same through an agent run and the log.

A react agent, and a scaffold in each bridge dialect, run against mockllm: the
model calls a tool, the agent runs it, and the model answers twice. The ids in
the final messages, in each `ModelEvent`'s input and output, in each
`ToolEvent`, and in the log read back (`.eval` and `.json`) must agree.
"""

import json
from pathlib import Path
from typing import Any, Callable, Literal, cast

import pytest
from anthropic import AsyncAnthropic
from google import genai
from openai import AsyncOpenAI
from shortuuid import uuid

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge, react
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import apply_message_ids
from inspect_ai.dataset import Sample
from inspect_ai.event import ModelEvent, ToolEvent
from inspect_ai.log import EvalLog, read_eval_log
from inspect_ai.log._condense import condense_sample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ModelOutput,
    get_model,
)
from inspect_ai.tool import Tool, ToolCall, ToolResult, tool
from inspect_ai.util import store

Dialect = Literal["completions", "responses", "anthropic", "google"]
DIALECTS: list[Dialect] = ["completions", "responses", "anthropic", "google"]

PROMPT = "Please echo the word hello."
FOLLOW_UP = "Thanks, that is all."


def _mock_model() -> Any:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                "echo",
                {"text": "hello", "count": 1},
                content="I will  echo it.",
            ),
            ModelOutput.from_content("mockllm/model", "Done:  hello."),
            ModelOutput.from_content("mockllm/model", "Bye."),
        ],
    )


ECHO_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "count": {"type": "integer"}},
    "required": ["text", "count"],
}


def _mangle(value: Any) -> Any:
    """Reverse key order and double the spaces in text, as a careless scaffold might."""
    if isinstance(value, dict):
        return {
            key: _mangle(item)
            for key, item in reversed(list(value.items()))
            if item is not None
        }
    if isinstance(value, list):
        return [_mangle(item) for item in value]
    if isinstance(value, str) and " " in value and not value.startswith("{"):
        return value.replace(" ", "  ")
    return value


def _mangle_arguments(arguments: str) -> str:
    return json.dumps(dict(reversed(list(json.loads(arguments).items()))), indent=1)


async def _completions(mangle: bool) -> None:
    async with AsyncOpenAI(api_key="inspect") as client:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": PROMPT},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo text.",
                    "parameters": ECHO_TOOL_PARAMETERS,
                },
            }
        ]
        while True:
            completion = await client.chat.completions.create(
                model="inspect",
                messages=cast(Any, messages),
                tools=cast(Any, tools),
            )
            message = completion.choices[0].message
            assistant = message.model_dump(exclude_none=True)
            if mangle:
                for call in assistant.get("tool_calls", []):
                    call["function"]["arguments"] = _mangle_arguments(
                        call["function"]["arguments"]
                    )
                assistant = _mangle(assistant)
            messages.append(assistant)
            if not message.tool_calls:
                if messages[-2]["content"] == FOLLOW_UP:
                    return
                messages.append({"role": "user", "content": FOLLOW_UP})
                continue
            for call in message.tool_calls:
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": "hello"}
                )


async def _responses(mangle: bool) -> None:
    async with AsyncOpenAI(api_key="inspect") as client:
        input: list[dict[str, Any]] = [{"role": "user", "content": PROMPT}]
        tools = [
            {
                "type": "function",
                "name": "echo",
                "description": "Echo text.",
                "parameters": ECHO_TOOL_PARAMETERS,
            }
        ]
        while True:
            response = await client.responses.create(
                model="inspect",
                instructions="You are a helpful assistant.",
                input=cast(Any, input),
                tools=cast(Any, tools),
            )
            calls = []
            for item in response.output:
                param = item.model_dump(exclude_none=True)
                if mangle:
                    if param["type"] == "function_call":
                        param["arguments"] = _mangle_arguments(param["arguments"])
                    param = _mangle(param)
                input.append(param)
                if item.type == "function_call":
                    calls.append(item.call_id)
            if not calls:
                if input[-2].get("content") == FOLLOW_UP:
                    return
                input.append({"role": "user", "content": FOLLOW_UP})
                continue
            for call_id in calls:
                input.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": "hello",
                    }
                )


async def _anthropic(mangle: bool) -> None:
    async with AsyncAnthropic(api_key="inspect") as client:
        messages: list[dict[str, Any]] = [{"role": "user", "content": PROMPT}]
        tools = [
            {
                "name": "echo",
                "description": "Echo text.",
                "input_schema": ECHO_TOOL_PARAMETERS,
            }
        ]
        while True:
            message = await client.messages.create(
                model="inspect",
                max_tokens=1024,
                system="You are a helpful assistant.",
                messages=cast(Any, messages),
                tools=cast(Any, tools),
            )
            content = [block.model_dump(exclude_none=True) for block in message.content]
            if mangle:
                content = _mangle(content)
            messages.append({"role": "assistant", "content": content})
            calls = [block.id for block in message.content if block.type == "tool_use"]
            if not calls:
                if messages[-2]["content"] == FOLLOW_UP:
                    return
                messages.append({"role": "user", "content": FOLLOW_UP})
                continue
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": id, "content": "hello"}
                        for id in calls
                    ],
                }
            )


async def _google(mangle: bool) -> None:
    from google.genai import types

    client = genai.Client(api_key="inspect")
    contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": PROMPT}]}]
    config = types.GenerateContentConfig(
        system_instruction="You are a helpful assistant.",
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="echo",
                        description="Echo text.",
                        parameters_json_schema=ECHO_TOOL_PARAMETERS,
                    )
                ]
            )
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    while True:
        response = await client.aio.models.generate_content(
            model="inspect", contents=contents, config=config
        )
        assert response.candidates and response.candidates[0].content
        content = response.candidates[0].content.model_dump(
            exclude_none=True, by_alias=True
        )
        if mangle:
            content = _mangle(content)
        contents.append(content)
        calls = [
            part.function_call.name
            for part in response.candidates[0].content.parts or []
            if part.function_call is not None
        ]
        if not calls:
            if contents[-2]["parts"] == [{"text": FOLLOW_UP}]:
                return
            contents.append({"role": "user", "parts": [{"text": FOLLOW_UP}]})
            continue
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": name,
                            "response": {"output": "hello"},
                        }
                    }
                    for name in calls
                ],
            }
        )


SCAFFOLDS: dict[Dialect, Callable[[bool], Any]] = {
    "completions": _completions,
    "responses": _responses,
    "anthropic": _anthropic,
    "google": _google,
}


@agent
def scaffold_agent(dialect: Dialect, mangle: bool) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        store().set("input_id", state.messages[0].id)
        async with agent_bridge(state) as bridge:
            await SCAFFOLDS[dialect](mangle)
            return bridge.state

    return execute


def _run(solver: Agent, log_dir: Path, log_format: Literal["eval", "json"]) -> EvalLog:
    log = eval(
        Task(dataset=[Sample(input=PROMPT)], solver=solver),
        model=_mock_model(),
        log_dir=str(log_dir),
        log_format=log_format,
    )[0]
    assert log.status == "success", log.error
    return log


def assert_ids_agree(log: EvalLog, model_calls: int) -> None:
    """The final conversation extends every model call, and tool events point into it."""
    assert log.samples
    sample = log.samples[0]
    final_ids = [m.id for m in sample.messages]
    assert len(set(final_ids)) == len(final_ids)
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == model_calls
    for event in model_events:
        call_ids = [m.id for m in event.input] + [event.output.message.id]
        assert call_ids == final_ids[: len(call_ids)]
    prompt = next(m for m in sample.messages if m.text == PROMPT)
    assert prompt.id == sample.store["input_id"]
    for tool_event in [e for e in sample.events if isinstance(e, ToolEvent)]:
        [proposing] = [
            m
            for m in sample.messages
            if isinstance(m, ChatMessageAssistant)
            and tool_event.id in [call.id for call in m.tool_calls or []]
        ]
        [result] = [
            m
            for m in sample.messages
            if isinstance(m, ChatMessageTool) and m.tool_call_id == tool_event.id
        ]
        assert tool_event.call_message_id == proposing.id
        assert tool_event.message_id == result.id


@pytest.mark.parametrize("log_format", ["eval", "json"])
@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("mangle", [False, True])
def test_bridge_keeps_message_ids(
    dialect: Dialect,
    mangle: bool,
    log_format: Literal["eval", "json"],
    tmp_path: Path,
) -> None:
    log = _run(scaffold_agent(dialect, mangle), tmp_path, log_format)
    assert_ids_agree(log, model_calls=3)
    assert_ids_agree(read_eval_log(log.location), model_calls=3)


@tool
def echo() -> Tool:
    async def execute(text: str, count: int) -> str:
        """Echo text.

        Args:
          text: The text.
          count: How many times.
        """
        return text * count

    return execute


@agent
def react_agent() -> Agent:
    agent = react(tools=[echo()], submit=False)

    async def execute(state: AgentState) -> AgentState:
        store().set("input_id", state.messages[0].id)
        return await agent(state)

    return execute


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_react_keeps_message_ids(
    log_format: Literal["eval", "json"], tmp_path: Path
) -> None:
    log = _run(react_agent(), tmp_path, log_format)
    assert log.samples
    assert any(isinstance(e, ToolEvent) for e in log.samples[0].events)
    assert_ids_agree(log, model_calls=2)
    assert_ids_agree(read_eval_log(log.location), model_calls=2)


@tool
def snapshot() -> Tool:
    async def execute() -> ToolResult:
        """Take a snapshot."""
        return [ContentText(text="snapshot"), ContentImage(image=IMAGE)]

    return execute


IMAGE = "data:image/png;base64,iVBORw0KGgo="


def test_messages_rebuilt_every_call_keep_one_id(tmp_path: Path) -> None:
    """Media moved out of tool results (mockllm takes none) is one message per sample."""
    calls = 4
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call("mockllm/model", "snapshot", {})
            for _ in range(calls)
        ]
        + [ModelOutput.from_content("mockllm/model", "done")],
    )
    log = eval(
        Task(
            dataset=[Sample(input=PROMPT)],
            solver=react(tools=[snapshot()], submit=False),
        ),
        model=model,
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = read.samples[0]

    derived: dict[str, set[str]] = {}
    inputs: dict[str, set[str]] = {}
    for event in [e for e in sample.events if isinstance(e, ModelEvent)]:
        for message in event.input:
            assert message.id is not None
            inputs.setdefault(message.id, set()).add(message.model_dump_json())
            if message.metadata and "derived_from" in message.metadata:
                derived.setdefault(message.id, set()).add(message.model_dump_json())
    assert len(derived) == calls
    assert all(len(contents) == 1 for contents in derived.values())

    condensed = condense_sample(sample)
    assert condensed.events_data is not None
    assert len(condensed.events_data["messages"]) == sum(
        len(contents) for contents in inputs.values()
    )


def _rebuilt(*messages: ChatMessage) -> list[ChatMessage]:
    """Messages as a scaffold sends them back: copies with ids made up on the way."""
    return [
        m.model_copy(update={"id": f"wire-{uuid()}", "metadata": None})
        for m in messages
    ]


def _list_files() -> ChatMessageAssistant:
    # the Google bridge rebuilds equal calls with equal ids
    return ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(id="call_bash_1", function="bash", arguments={"cmd": "ls"})
        ],
    )


async def test_repeated_message_keeps_the_main_threads_id() -> None:
    """A side call that repeats a main-thread message can't lend it its id."""
    task = ChatMessageUser(content="List the files twice.")
    result = ChatMessageTool(
        content="a.txt", tool_call_id="call_bash_1", function="bash"
    )
    bridge = AgentBridge(AgentState(messages=[task]))

    async def request(messages: list[ChatMessage], output: ChatMessage) -> list[str]:
        apply_message_ids(bridge, messages)
        await bridge._track_state(messages, ModelOutput.from_message(output))
        return [m.id or "" for m in messages]

    first, side, second = _list_files(), _list_files(), _list_files()
    await request(_rebuilt(task), first)
    await request(_rebuilt(ChatMessageUser(content="Is ls safe?")), side)
    ids = await request(_rebuilt(task, first, result), second)
    final = await request(
        _rebuilt(task, first, result, second, result),
        ChatMessageAssistant(content="done"),
    )

    assert final[:4] == [task.id, first.id, ids[2], second.id]
    assert len(set(final)) == len(final)


async def test_derived_from_survives_the_round_trip() -> None:
    task = ChatMessageUser(content="Hello")
    bridge = AgentBridge(AgentState(messages=[task]))
    replaced = ChatMessageAssistant(
        content="Hi", metadata={"derived_from": ["model-output"]}
    )
    messages = _rebuilt(task)
    apply_message_ids(bridge, messages)
    await bridge._track_state(messages, ModelOutput.from_message(replaced))

    messages = _rebuilt(task, replaced, ChatMessageUser(content="Again"))
    apply_message_ids(bridge, messages)

    assert messages[1].id == replaced.id
    assert messages[1].metadata == {"derived_from": ["model-output"]}
