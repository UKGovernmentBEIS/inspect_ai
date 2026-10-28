"""Message ids stay the same through an agent run and the log.

A react agent, and a scaffold in each bridge dialect, run against mockllm: the
model calls a tool, the agent runs it, and the model answers twice. The ids in
the final messages, in each `ModelEvent`'s input and output, in each
`ToolEvent`, and in the log read back (`.eval` and `.json`) must agree.
"""

import copy
import json
from pathlib import Path
from typing import Any, Callable, Literal, cast
from unittest.mock import patch

import pytest
from anthropic import AsyncAnthropic
from google import genai
from openai import AsyncOpenAI
from shortuuid import uuid
from test_helpers.checkpoint import RecordingCheckpointer
from test_helpers.message_ids import assert_message_ids, tool_event_producers

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge, handoff, react
from inspect_ai.agent._bridge import types as bridge_types
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import apply_message_ids
from inspect_ai.dataset import Sample
from inspect_ai.event import ModelEvent, ToolEvent
from inspect_ai.log import (
    EvalLog,
    EvalSample,
    read_eval_log,
    resolve_sample_attachments,
)
from inspect_ai.log._condense import condense_sample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ModelOutput,
    get_model,
)
from inspect_ai.model._message_ids import content_hash, edit_id, edited_message
from inspect_ai.solver import generate, user_message
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


def assert_ids_agree(log: EvalLog, model_calls: int, edits: bool = False) -> int:
    """The final conversation extends every model call, and tool events point into it.

    With `edits`, a reply the scaffold sent back changed is in the conversation as
    an edit of the reply. Returns the number of such edits.
    """
    assert log.samples
    sample = resolve_sample_attachments(log.samples[0], "full")
    assert_message_ids(sample)
    final_ids = [m.id for m in sample.messages]
    assert len(set(final_ids)) == len(final_ids)
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == model_calls
    edited = 0
    for event in model_events:
        input_ids = [m.id for m in event.input]
        assert input_ids == final_ids[: len(input_ids)]
        reply = sample.messages[len(input_ids)]
        if reply.id != event.output.message.id:
            assert edits
            assert reply.id == edit_id(event.output.message.id, content_hash(reply))
            edited += 1
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
    return edited


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
    # Google rebuilds tool call ids, so the reply calling a tool comes back
    # changed; the mangling scaffold changes both replies it sends back
    edits = 2 if mangle else 1 if dialect == "google" else 0
    for logged in [log, read_eval_log(log.location)]:
        assert assert_ids_agree(logged, model_calls=3, edits=edits > 0) == edits


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

    kept = {m.id for m in sample.messages}
    derived: dict[str, set[str]] = {}
    inputs: dict[str, set[str]] = {}
    for event in [e for e in sample.events if isinstance(e, ModelEvent)]:
        for message in event.input:
            assert message.id is not None
            inputs.setdefault(message.id, set()).add(message.model_dump_json())
            if message.id not in kept:
                derived.setdefault(message.id, set()).add(message.model_dump_json())
    # each call's tool message, edited to move its media out, and the media
    assert len(derived) == 2 * calls
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


class _Scaffold:
    """Drives a bridge the way a scaffold does: rebuilt requests, then the reply."""

    def __init__(self, bridge: AgentBridge) -> None:
        self.bridge = bridge

    async def request(
        self, messages: list[ChatMessage], output: ChatMessage | None = None
    ) -> list[str]:
        rebuilt = _rebuilt(*messages)
        apply_message_ids(self.bridge, rebuilt)
        self.sent = rebuilt
        if output is not None:
            await self.bridge._track_state(rebuilt, ModelOutput.from_message(output))
        return [m.id or "" for m in rebuilt]


def _call(call_id: str) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content="",
        tool_calls=[ToolCall(id=call_id, function="bash", arguments={"cmd": "ls"})],
    )


def _result(call_id: str, content: str = "a.txt") -> ChatMessageTool:
    return ChatMessageTool(content=content, tool_call_id=call_id, function="bash")


@pytest.mark.parametrize("call_ids", [("unique-1", "unique-2"), ("call_1", "call_1")])
async def test_compacted_history_keeps_the_ids_of_the_retained_messages(
    call_ids: tuple[str, str],
) -> None:
    """After scaffold compaction the retained tail keeps its ids, by call id or by position."""
    task = ChatMessageUser(content="List the files twice.")
    first, second = _call(call_ids[0]), _call(call_ids[1])
    result_1, result_2 = _result(call_ids[0]), _result(call_ids[1])
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], first)
    await scaffold.request([task, first, result_1], second)
    summary = ChatMessageUser(content="Summary: listed the files once.")

    ids = await scaffold.request([summary, second, result_2])

    assert ids[1] == second.id


async def test_resumed_bridge_keeps_the_main_threads_id() -> None:
    """A side call's equal output recorded first doesn't take the main thread's id after a resume."""
    task = ChatMessageUser(content="List the files.")
    side, first = _call("call_1"), _call("call_1")
    checkpointer = RecordingCheckpointer()
    scaffold = _Scaffold(
        AgentBridge(AgentState(messages=[task]), checkpointer=checkpointer)
    )
    await scaffold.request([ChatMessageUser(content="Is ls safe?")], side)
    await scaffold.request([task], first)
    snapshot = {
        key: copy.deepcopy(callback())
        for key, callback in checkpointer.callbacks.items()
    }
    before = await scaffold.request([task, first, _result("call_1")])

    resumed = _Scaffold(
        AgentBridge(
            AgentState(messages=[task]),
            checkpointer=RecordingCheckpointer(restored=snapshot),
        )
    )
    after = await resumed.request([task, first, _result("call_1")])

    assert before[1] == after[1] == first.id


async def test_scaffold_edits_get_ids_derived_from_the_originals() -> None:
    """A tool result and a user message the scaffold edits are new messages with derived ids."""
    task = ChatMessageUser(content="List the files.")
    first, second = _call("call_1"), ChatMessageAssistant(content="Anything else?")
    result = _result("call_1", "a very long listing")
    follow_up = ChatMessageUser(content="No, thanks.")
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], first)
    await scaffold.request([task, first, result], second)
    final = ChatMessageAssistant(content="Bye.")
    ids = await scaffold.request([task, first, result, second, follow_up], final)
    edited_conversation: list[ChatMessage] = [
        task,
        first,
        _result("call_1", "[truncated]"),
        second,
        ChatMessageUser(content="No, thanks!"),
        final,
    ]

    edited = await scaffold.request(edited_conversation)
    sent = scaffold.sent
    again = await scaffold.request(edited_conversation)

    assert [edited[i] for i in (0, 1, 3)] == [ids[i] for i in (0, 1, 3)]
    assert edited[5] == final.id
    for i in (2, 4):
        assert edited[i] == edit_id(ids[i], content_hash(sent[i])) != ids[i]
        assert sent[i].metadata is None
    assert again == edited


class _CountingList(list[str]):
    reads = 0

    def __getitem__(self, index: Any) -> Any:
        _CountingList.reads += 1
        return super().__getitem__(index)

    def __contains__(self, value: object) -> bool:
        _CountingList.reads += len(self)
        return super().__contains__(value)

    def __iter__(self) -> Any:
        for item in super().__iter__():
            _CountingList.reads += 1
            yield item


async def _matching_work(repeats: int, compacted: bool) -> int:
    """Key comparisons and id-list reads to match one request on a repetitive history."""
    task = ChatMessageUser(content="Keep going until told to stop.")
    history: list[ChatMessage] = [task]
    for _ in range(repeats):
        history += [
            ChatMessageAssistant(content="OK"),
            ChatMessageUser(content="continue"),
        ]
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request(history, ChatMessageAssistant(content="OK"))
    bridge = scaffold.bridge
    for key, ids in bridge._message_ids.items():
        bridge._message_ids[key] = _CountingList(ids)

    strengths = 0
    key_strength = bridge_types._key_strength

    def counting_strength(key: str) -> int:
        nonlocal strengths
        strengths += 1
        return key_strength(key)

    _CountingList.reads = 0
    request = (
        [ChatMessageUser(content="Summary: said OK a lot."), *history[1:]]
        if compacted
        else history
    )
    with patch.object(bridge_types, "_key_strength", counting_strength):
        await scaffold.request(request + [ChatMessageUser(content="continue")])
    return strengths + _CountingList.reads


@pytest.mark.parametrize("compacted", [False, True])
async def test_matching_work_is_linear_in_a_repetitive_conversation(
    compacted: bool,
) -> None:
    small = await _matching_work(100, compacted)
    large = await _matching_work(800, compacted)
    # linear is 8x; the quadratic matching this replaced was 64x
    assert large < 12 * small


def _assert_contract(log: EvalLog) -> EvalSample:
    """Check the message id contract live and read back; return the read-back sample."""
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    for logged in [log, read]:
        for sample in logged.samples or []:
            assert_message_ids(resolve_sample_attachments(sample, "full"))
    assert read.samples
    return resolve_sample_attachments(read.samples[0], "full")


def test_react_submit_keeps_the_contract(tmp_path: Path) -> None:
    """Appending the answer edits the output, and removing the submit call edits that."""
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model", "echo", {"text": "hi", "count": 1}
            ),
            ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": "done"}),
        ],
    )
    log = eval(
        Task(dataset=[Sample(input=PROMPT)], solver=react(tools=[echo()])),
        model=model,
        log_dir=str(tmp_path),
    )[0]

    sample = _assert_contract(log)
    submitted = [e for e in sample.events if isinstance(e, ModelEvent)][
        -1
    ].output.message
    final = sample.messages[-1]
    assert isinstance(final, ChatMessageAssistant)
    assert not final.tool_calls and final.text.endswith("done")
    answered = sample.output.message
    assert answered.id == edit_id(submitted.id, content_hash(answered))
    assert final.id == edit_id(answered.id, content_hash(final))
    assert answered.id != final.id
    assert tool_event_producers(sample) == [1, 1]


@agent(description="Searches for things.")
def searcher() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        state.output = await get_model().generate(state.messages)
        state.messages.append(state.output.message)
        return state

    return execute


def test_handoff_keeps_the_contract(tmp_path: Path) -> None:
    """The agent name prefix and the content_only output filter are edits of their sources."""
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call("mockllm/model", "transfer_to_searcher", {}),
            ModelOutput.from_content("mockllm/model", "child answer"),
            ModelOutput.from_content("mockllm/model", "parent answer"),
        ],
    )
    log = eval(
        Task(
            dataset=[Sample(input=PROMPT)],
            solver=react(tools=[handoff(searcher())], submit=False),
        ),
        model=model,
        log_dir=str(tmp_path),
    )[0]

    sample = _assert_contract(log)
    child = [e for e in sample.events if isinstance(e, ModelEvent)][1].output.message
    [prefixed] = [m for m in sample.messages if m.text == "[searcher] child answer"]
    assert prefixed.id == edit_id(child.id, content_hash(prefixed))


def test_configured_system_message_keeps_one_id(tmp_path: Path) -> None:
    log = eval(
        Task(
            dataset=[Sample(input=PROMPT)],
            solver=[generate(), user_message("Again."), generate()],
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[ModelOutput.from_content("mockllm/model", "OK")] * 2,
        ),
        log_dir=str(tmp_path),
        system_message="Always here.",
    )[0]

    sample = _assert_contract(log)
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len({e.input[0].id for e in model_events}) == 1


async def test_native_and_bridge_edits_of_a_message_agree() -> None:
    """An edit is the same message whether Inspect makes it or a scaffold sends it back."""
    task = ChatMessageUser(content="Hello")
    reply = ChatMessageAssistant(content="Hi there.")
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], reply)

    ids = await scaffold.request(
        [
            task,
            ChatMessageAssistant(content="Hi  there."),
            ChatMessageUser(content="Again"),
        ]
    )
    native = edited_message(reply, content="Hi  there.")

    assert ids[1] == native.id != reply.id
