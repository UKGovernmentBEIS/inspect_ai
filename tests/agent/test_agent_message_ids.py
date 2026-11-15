"""Message ids stay the same through an agent run and the log.

A react agent, and a scaffold in each bridge dialect, run against mockllm: the
model calls a tool, the agent runs it, and the model answers twice. The ids in
the final messages, in each `ModelEvent`'s input and output, in each
`ToolEvent`, and in the log read back (`.eval` and `.json`) must agree.
"""

import base64
import contextlib
import json
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, cast
from unittest.mock import patch

import anyio
import pytest
from anthropic import AsyncAnthropic, omit
from google import genai
from openai import AsyncOpenAI
from shortuuid import uuid
from test_helpers.checkpoint import RecordingCheckpointer
from test_helpers.message_ids import (
    assert_message_ids,
    edited_id,
    handed_calls,
    recording_placements,
    tool_event_producers,
)

from inspect_ai import Task, eval
from inspect_ai._util._async import tg_collect
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge, handoff, react
from inspect_ai.agent._bridge import bridge as bridge_module
from inspect_ai.agent._bridge import types as bridge_types
from inspect_ai.agent._bridge.responses_impl import filter_duplicate_assistant_content
from inspect_ai.agent._bridge.types import AgentBridge, _unplaced_key
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
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    GenerateInput,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._assistant_internal import init_sample_assistant_internal
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._compaction import (
    CompactionAuto,
    CompactionEdit,
    CompactionNative,
    CompactionStrategy,
    CompactionSummary,
    CompactionTrim,
)
from inspect_ai.model._message_ids import (
    content_hash,
    edited_message,
    stable_message_ids,
)
from inspect_ai.model._model import active_model_context_var
from inspect_ai.model._model_output import ChatCompletionChoice, ModelUsage
from inspect_ai.solver import generate, user_message
from inspect_ai.tool import (
    Tool,
    ToolCall,
    ToolChoice,
    ToolInfo,
    ToolParam,
    ToolParams,
    ToolResult,
    tool,
)
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


def assert_ids_agree(
    log: EvalLog,
    model_calls: int,
    edits: Literal["none", "derived", "unplaced"] = "none",
    input_prompt: bool = True,
) -> int:
    """The final conversation extends every model call, and tool events point into it.

    A reply sent back in another form is in the conversation as an edit of the
    reply (`derived`, a dialect's wire form) or under an id made for messages
    the bridge can't place (`unplaced`, a scaffold's edit), never another
    reply's. Returns the number of such replies. With `input_prompt`, the
    prompt keeps the id it has in the sample input.
    """
    assert log.samples
    sample = resolve_sample_attachments(log.samples[0], "full")
    assert_message_ids(sample)
    final_ids = [m.id for m in sample.messages]
    assert len(set(final_ids)) == len(final_ids)
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == model_calls
    edited = 0
    output_ids = {event.output.message.id for event in model_events}
    for event in model_events:
        input_ids = [m.id for m in event.input]
        assert input_ids == final_ids[: len(input_ids)]
        reply = sample.messages[len(input_ids)]
        if reply.id != event.output.message.id:
            assert edits != "none"
            if edits == "derived":
                assert reply.id == edited_id(event.output.message.id, reply)
            else:
                assert reply.id not in output_ids
            edited += 1
    prompt = next(m for m in sample.messages if m.text == PROMPT)
    assert (prompt.id == sample.store["input_id"]) == input_prompt
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
        # the scaffold's own system message comes first, so its first request
        # doesn't start with the sample's conversation
        assert (
            assert_ids_agree(
                logged,
                model_calls=3,
                edits="unplaced" if mangle else "derived",
                input_prompt=False,
            )
            == edits
        )


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


@pytest.mark.parametrize("side_first", [True, False])
async def test_repeated_message_keeps_the_main_threads_id(side_first: bool) -> None:
    """A side call that repeats a main-thread reply can't lend it its id.

    Before or after the main reply, the side reply could stand in for it, so
    the request holding it isn't placed and the reply gets an id made for
    unplaced messages. The next request continues that one unchanged and
    keeps its ids.
    """
    task = ChatMessageUser(content="List the files twice.")
    result = ChatMessageTool(
        content="a.txt", tool_call_id="call_bash_1", function="bash"
    )
    bridge = AgentBridge(AgentState(messages=[task]))

    async def request(messages: list[ChatMessage], output: ChatMessage) -> list[str]:
        apply_message_ids(bridge, messages)
        await bridge._track_state(messages, ModelOutput.from_message(output), [])
        return [m.id or "" for m in messages]

    first, side, second = _list_files(), _list_files(), _list_files()
    side_question = ChatMessageUser(content="Is ls safe?")
    if side_first:
        await request(_rebuilt(side_question), side)
    await request(_rebuilt(task), first)
    if not side_first:
        await request(_rebuilt(side_question), side)
    ids = await request(_rebuilt(task, first, result), second)
    final = await request(
        _rebuilt(task, first, result, second, result),
        ChatMessageAssistant(content="done"),
    )

    assert ids[1] not in (side.id, second.id)
    assert final[:4] == [*ids, second.id]
    assert len(set(final)) == len(final)


def _ids_by_content(requests: list[list[ChatMessage]]) -> list[list[str]]:
    """The ids the bridge gave requests before it placed continuations.

    Per message JSON without its id, a message took the first id recorded for
    it that no earlier message of its request had, else a new one
    (`id-0`, `id-1`, ...).
    """
    recorded: dict[str, list[str]] = {}
    made = 0
    given_ids: list[list[str]] = []
    for request in requests:
        given: list[str] = []
        for message in request:
            ids = recorded.setdefault(
                to_json_str_safe(message.model_copy(update={"id": None})), []
            )
            id = next((id for id in ids if id not in given), None)
            if id is None:
                id = f"id-{made}"
                made += 1
                ids.append(id)
            given.append(id)
        given_ids.append(given)
    return given_ids


def test_unplaced_messages_get_the_ids_they_got_by_content() -> None:
    """A message no thread places gets the id the bridge gave every message before it placed continuations.

    Each request starts with a system message no earlier request had, so no
    thread places it. Equal messages share ids across requests, and the n-th
    equal message of a request takes the n-th id.
    """
    hi, ok = ChatMessageUser(content="hi"), ChatMessageAssistant(content="ok")
    call, result = _call("call_1"), _result("call_1")
    bodies: list[list[ChatMessage]] = [
        [hi, ok, hi, ok],
        [hi, ok, hi],
        [ok, hi, hi, ok, ok],
        [call, result, hi],
        [call, result, result, ok],
    ]
    requests: list[list[ChatMessage]] = [
        [ChatMessageSystem(content=f"System {n}."), *body]
        for n, body in enumerate(bodies)
    ]
    bridge = AgentBridge(AgentState(messages=[]))
    made = iter(range(1000))
    given: list[list[str]] = []
    with patch.object(bridge_types, "uuid", lambda: f"id-{next(made)}"):
        for request in requests:
            rebuilt = _rebuilt(*request)
            apply_message_ids(bridge, rebuilt)
            given.append([m.id or "" for m in rebuilt])

    assert given == _ids_by_content(requests)


async def test_append_only_repeated_exchanges_keep_occurrence_ids() -> None:
    """An intact history wins over an equal suffix in the shared matcher."""
    task = ChatMessageUser(content="continue")
    first = ChatMessageAssistant(content="ok")
    second_user = ChatMessageUser(content="continue")
    second = ChatMessageAssistant(content="ok")
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))

    first_ids = await scaffold.request([task], first)
    second_ids = await scaffold.request([task, first, second_user], second)
    ids = await scaffold.request([task, first, second_user, second])

    assert ids[:3] == second_ids
    assert ids[0] == first_ids[0]
    assert ids[3] == second.id


@pytest.mark.parametrize("dialect", DIALECTS)
def test_repeated_exchanges_keep_ids_through_dialect(
    dialect: Dialect, tmp_path: Path
) -> None:
    """Three append-only requests retain occurrence ids over each wire dialect."""

    @agent
    def repeated() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                if dialect == "completions":
                    async with AsyncOpenAI(api_key="inspect") as client:
                        messages: list[dict[str, Any]] = [
                            {"role": "user", "content": "continue"}
                        ]
                        for turn in range(3):
                            completion = await client.chat.completions.create(
                                model="inspect", messages=cast(Any, messages)
                            )
                            messages.append(
                                completion.choices[0].message.model_dump(
                                    exclude_none=True
                                )
                            )
                            if turn < 2:
                                messages.append({"role": "user", "content": "continue"})
                elif dialect == "responses":
                    async with AsyncOpenAI(api_key="inspect") as client:
                        input: list[dict[str, Any]] = [
                            {"role": "user", "content": "continue"}
                        ]
                        for turn in range(3):
                            response_result = await client.responses.create(
                                model="inspect", input=cast(Any, input)
                            )
                            input.extend(
                                item.model_dump(exclude_none=True)
                                for item in response_result.output
                            )
                            if turn < 2:
                                input.append({"role": "user", "content": "continue"})
                elif dialect == "anthropic":
                    async with AsyncAnthropic(api_key="inspect") as anthropic_client:
                        messages = [{"role": "user", "content": "continue"}]
                        for turn in range(3):
                            anthropic_response = await anthropic_client.messages.create(
                                model="inspect",
                                max_tokens=32,
                                messages=cast(Any, messages),
                            )
                            messages.append(
                                {
                                    "role": "assistant",
                                    "content": [
                                        block.model_dump(exclude_none=True)
                                        for block in anthropic_response.content
                                    ],
                                }
                            )
                            if turn < 2:
                                messages.append({"role": "user", "content": "continue"})
                else:
                    google_client = genai.Client(api_key="inspect")
                    contents: list[dict[str, Any]] = [
                        {"role": "user", "parts": [{"text": "continue"}]}
                    ]
                    for turn in range(3):
                        google_response = (
                            await google_client.aio.models.generate_content(
                                model="inspect", contents=contents
                            )
                        )
                        assert (
                            google_response.candidates
                            and google_response.candidates[0].content
                        )
                        contents.append(
                            google_response.candidates[0].content.model_dump(
                                exclude_none=True, by_alias=True
                            )
                        )
                        if turn < 2:
                            contents.append(
                                {"role": "user", "parts": [{"text": "continue"}]}
                            )
                return bridge.state

        return execute

    log = eval(
        Task(dataset=[Sample(input="continue")], solver=repeated()),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content("mockllm/model", "ok") for _ in range(3)
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(events) == 3
    assert [m.id for m in events[2].input[:3]] == [
        events[1].input[0].id,
        events[0].output.message.id,
        events[1].input[2].id,
    ]
    assert events[2].input[3].id == events[1].output.message.id


_Turn = list[dict[str, Any]]
_Sent = list[tuple[list[_Turn], _Turn]]
"""Each generation's request turns and reply turn, in the order generated."""


class _TextConversation:
    """A text-only scaffold conversation in a bridge dialect, as wire turns.

    Each generation is appended to `sent`, which conversations can share.
    """

    def __init__(
        self, dialect: Dialect, system: str | None = None, sent: _Sent | None = None
    ) -> None:
        self.dialect = dialect
        self.system = system
        self.sent = sent if sent is not None else []
        self.turns: list[_Turn] = []

    def user_turn(self, text: str) -> list[dict[str, Any]]:
        if self.dialect == "google":
            return [{"role": "user", "parts": [{"text": text}]}]
        return [{"role": "user", "content": text}]

    def user(self, text: str) -> None:
        self.turns.append(self.user_turn(text))

    async def generate(self) -> None:
        sent = list(self.turns)
        wire = [item for turn in self.turns for item in turn]
        if self.system is not None and self.dialect in ("completions", "responses"):
            wire = [{"role": "system", "content": self.system}, *wire]
        if self.dialect == "completions":
            async with AsyncOpenAI(api_key="inspect") as client:
                completion = await client.chat.completions.create(
                    model="inspect", messages=cast(Any, wire)
                )
                reply = [completion.choices[0].message.model_dump(exclude_none=True)]
        elif self.dialect == "responses":
            async with AsyncOpenAI(api_key="inspect") as client:
                response = await client.responses.create(
                    model="inspect", input=cast(Any, wire)
                )
                reply = [item.model_dump(exclude_none=True) for item in response.output]
        elif self.dialect == "anthropic":
            async with AsyncAnthropic(api_key="inspect") as anthropic_client:
                message = await anthropic_client.messages.create(
                    model="inspect",
                    max_tokens=32,
                    messages=cast(Any, wire),
                    system=self.system if self.system is not None else omit,
                )
                reply = [
                    {
                        "role": "assistant",
                        "content": [
                            block.model_dump(exclude_none=True)
                            for block in message.content
                        ],
                    }
                ]
        else:
            google_response = await genai.Client(
                api_key="inspect"
            ).aio.models.generate_content(
                model="inspect",
                contents=cast(Any, wire),
                config={"system_instruction": self.system} if self.system else None,
            )
            assert google_response.candidates and google_response.candidates[0].content
            reply = [
                google_response.candidates[0].content.model_dump(
                    exclude_none=True, by_alias=True
                )
            ]
        self.sent.append((sent, reply))
        self.turns.append(reply)


@pytest.mark.parametrize(
    "case",
    ["compacted", "full_history", "distinct_replies", "single_tail", "same_reply_next"],
)
@pytest.mark.parametrize("dialect", DIALECTS)
def test_compacted_identical_replies_keep_their_own_ids(
    dialect: Dialect, case: str, tmp_path: Path, placements: list[set[str]]
) -> None:
    """Replies retained by compaction are never placed as another reply.

    Two replies (`OK` twice, or `OK` and `Fine`) follow different user
    messages. Compaction replaces the prompt with a summary and keeps both
    exchanges, or only the latest. The request no longer starts with a thread
    the bridge knows, so the retained replies aren't placed: each gets the id
    an equal message had, which it keeps. A reply generated after that
    compaction keeps its own id, unless it is `OK` too: the conversation
    before compaction holds two `OK` replies, so the next request could
    continue it.
    """
    sent: _Sent = []

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                conversation = _TextConversation(dialect, sent=sent)
                conversation.user("Say OK.")
                await conversation.generate()
                conversation.user("Say it again.")
                await conversation.generate()
                summary = conversation.user_turn("Summary: said it twice.")
                follow_up = "Once more."
                if case in ("compacted", "distinct_replies"):
                    conversation.turns = [summary, *conversation.turns[1:]]
                elif case == "single_tail":
                    conversation.turns = [summary, conversation.turns[-1]]
                    follow_up = "Say it again."
                elif case == "same_reply_next":
                    conversation.turns = [summary, conversation.turns[-1]]
                for text in (follow_up, "Thanks."):
                    conversation.user(text)
                    await conversation.generate()
                return bridge.state

        return execute

    replies = [
        "OK",
        "Fine" if case == "distinct_replies" else "OK",
        "OK" if case == "same_reply_next" else "Done",
        "Bye",
    ]
    log = eval(
        Task(dataset=[Sample(input="Say OK.")], solver=scaffold()),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content("mockllm/model", text) for text in replies
            ],
        ),
        log_dir=str(tmp_path),
    )[0]

    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    events = [e for e in sample.events if isinstance(e, ModelEvent)]
    reply_ids = [event.output.message.id for event in events]
    _assert_owned(events, sent, placements)
    compacted = [m.id for m in events[2].input if m.role == "assistant"]
    final = [m.id for m in events[3].input if m.role == "assistant"]
    if case == "full_history":
        assert final == reply_ids[:3]
    elif case != "same_reply_next":
        assert not set(compacted) & placements[2]
        assert final == [*compacted, reply_ids[2]]
    assert [m.id for m in sample.messages if m.role == "assistant"] == [
        *final,
        reply_ids[3],
    ]


_COMPACTION_STRATEGIES: dict[str, Callable[[], CompactionStrategy]] = {
    "trim": lambda: CompactionTrim(threshold=1_000_000),
    "edit": lambda: CompactionEdit(threshold=1_000_000),
    "summary": lambda: CompactionSummary(threshold=1_000_000),
    "native": lambda: CompactionNative(threshold=1_000_000),
    "auto": lambda: CompactionAuto(threshold=1_000_000),
}


@pytest.mark.parametrize("shape", ["equal_replies", "input_prompt", "placed_first"])
@pytest.mark.parametrize("strategy", list(_COMPACTION_STRATEGIES))
@pytest.mark.parametrize("dialect", DIALECTS)
def test_retried_request_after_equal_replies_keeps_its_input_length(
    dialect: Dialect, strategy: str, shape: str, tmp_path: Path
) -> None:
    """Retrying a request that holds an ambiguous reply never grows the compacted input.

    The prompt is sent twice and both replies are `OK`, so the retained reply
    in `[prompt, OK, follow-up]` can't be placed. Each of its messages gets the
    same id on every retry, also one placed before (the sample input's prompt
    with `input_prompt`, the first `OK` placed under its generated id before
    the second was generated with `placed_first`), so compaction counts them
    as already processed (below its threshold nothing is compacted) and the
    input doesn't grow.
    """

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(
                state, compaction=_COMPACTION_STRATEGIES[strategy]()
            ) as bridge:
                conversation = _TextConversation(dialect)
                conversation.user("Say OK.")
                await conversation.generate()
                if shape == "placed_first":
                    conversation.user("Thanks.")
                    await conversation.generate()
                conversation.turns = conversation.turns[:1]
                await conversation.generate()
                conversation.user("Thanks.")
                retried = list(conversation.turns)
                for _ in range(2 if shape == "placed_first" else 3):
                    conversation.turns = list(retried)
                    await conversation.generate()
                return bridge.state

        return execute

    if shape == "placed_first":
        replies, lengths = ["OK", "Bye", "OK", "Bye", "Bye"], [1, 3, 3, 3, 3]
    else:
        replies, lengths = ["OK", "OK", "Bye", "Bye", "Bye"], [1, 1, 3, 3, 3]
    prompt = "Say OK." if shape == "input_prompt" else "Start."
    events, _ = _reply_events(scaffold, replies, tmp_path, prompt=prompt)
    assert [len(event.input) for event in events] == lengths


def _stripped(value: Any) -> Any:
    """A wire reply turn with its text stripped of surrounding whitespace."""
    if isinstance(value, dict):
        return {
            key: item.strip()
            if key in ("text", "content") and isinstance(item, str)
            else _stripped(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_stripped(item) for item in value]
    return value


@pytest.mark.parametrize("dialect", DIALECTS)
def test_initial_example_replies_keep_their_ids_across_turns(
    dialect: Dialect, tmp_path: Path
) -> None:
    """Equal replies in a fresh bridge's input keep their ids on every request.

    The input holds two examples answered `4`. Each request resends them
    unchanged, so they keep the input's ids on every turn.
    """
    examples: list[ChatMessage] = [
        ChatMessageUser(content="What is 2+2?"),
        ChatMessageAssistant(content="4"),
        ChatMessageUser(content="What is 1+3?"),
        ChatMessageAssistant(content="4"),
        ChatMessageUser(content="What is 3+3?"),
    ]
    sent: _Sent = []

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                conversation = _TextConversation(dialect, sent=sent)
                for message in state.messages:
                    if message.role == "user":
                        conversation.user(message.text)
                    elif dialect == "google":
                        conversation.turns.append(
                            [{"role": "model", "parts": [{"text": message.text}]}]
                        )
                    else:
                        conversation.turns.append(
                            [{"role": "assistant", "content": message.text}]
                        )
                await conversation.generate()
                for text in ("And 4+4?", "Thanks."):
                    conversation.user(text)
                    await conversation.generate()
                return bridge.state

        return execute

    log = eval(
        Task(dataset=[Sample(input=examples)], solver=scaffold()),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content("mockllm/model", text)
                for text in ("6", "8", "Bye")
            ],
        ),
        log_dir=str(tmp_path),
    )[0]

    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert isinstance(sample.input, list)
    input_ids = [m.id for m in sample.input if m.role == "assistant"]
    assert len(set(input_ids)) == 2
    for event in events:
        assert [m.id for m in event.input if m.role == "assistant"][:2] == input_ids
    assert [m.id for m in sample.messages if m.role == "assistant"][:2] == input_ids


@pytest.fixture
def placements() -> Iterator[list[set[str]]]:
    with recording_placements() as recorded:
        yield recorded


def _assert_owned(
    events: list[ModelEvent], sent: _Sent, placements: list[set[str]]
) -> None:
    """Placement never moves an id from one reply to another.

    Each event's assistant messages are its request's reply turns, in order,
    then its output, and `placements` holds the ids each request's messages
    got by placement. A placed reply turn carries an id the same turn had
    before (its generated id, or one it carried in an earlier request), or an
    edit of one. A reply turn the bridge didn't place got its id by content
    and may share it with an equal reply.
    """
    assert len(placements) == len(events)
    carried: dict[int, set[str]] = {}
    for event, (turns, reply), placed in zip(events, sent, placements, strict=True):
        replies = [turn for turn in turns if turn[0].get("role") != "user"]
        messages = [m for m in event.input if m.role == "assistant"]
        for turn, message in zip(replies, messages, strict=True):
            assert message.id is not None
            before = carried.setdefault(id(turn), set())
            if message.id in placed:
                assert message.id in before or any(
                    message.id == edited_id(earlier, message) for earlier in before
                ), f"a placed reply took {message.id}, another reply's id"
            before.add(message.id)
        assert event.output.message.id is not None
        carried.setdefault(id(reply), set()).add(event.output.message.id)


def _reply_events(
    scaffold: Callable[[], Agent],
    replies: list[str],
    tmp_path: Path,
    prompt: str = "Start.",
) -> tuple[list[ModelEvent], EvalSample]:
    log = eval(
        Task(dataset=[Sample(input=prompt)], solver=scaffold()),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content("mockllm/model", text) for text in replies
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    return [e for e in sample.events if isinstance(e, ModelEvent)], sample


@pytest.mark.parametrize("shape", ["middle_dropped", "sliding_window", "kept_prefix"])
@pytest.mark.parametrize("dialect", DIALECTS)
def test_compacted_repeated_exchanges_never_shift_ids(
    dialect: Dialect, shape: str, tmp_path: Path, placements: list[set[str]]
) -> None:
    """Retained `OK` replies keep their own ids or get new ones, never another's.

    Nothing places a reply equal to a dropped one: not a unique message next
    to it (a dropped middle exchange), not an earlier request with the same
    content (a sliding window), not a kept system and task prefix.
    """
    replies = 3 if shape == "middle_dropped" else 4

    sent: _Sent = []

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                conversation = _TextConversation(
                    dialect,
                    system="Be brief." if shape == "kept_prefix" else None,
                    sent=sent,
                )
                if shape == "middle_dropped":
                    for text in ("Start.", "Check step one.", "Check step two."):
                        conversation.user(text)
                        await conversation.generate()
                    conversation.turns = [
                        conversation.user_turn("Summary: earlier checks done."),
                        conversation.turns[1],
                        *conversation.turns[4:],
                    ]
                    conversation.user("Finish.")
                else:
                    if shape == "kept_prefix":
                        conversation.user("Task: keep going.")
                    for _ in range(4):
                        conversation.user("Continue.")
                        await conversation.generate()
                    if shape == "sliding_window":
                        del conversation.turns[:2]
                    else:
                        del conversation.turns[3:5]
                    conversation.user("Continue.")
                await conversation.generate()
                conversation.user("Thanks.")
                await conversation.generate()
                return bridge.state

        return execute

    events, sample = _reply_events(
        scaffold, ["OK"] * replies + ["Done", "Bye"], tmp_path
    )
    reply_ids = [event.output.message.id for event in events]
    _assert_owned(events, sent, placements)
    compacted = [m.id for m in events[replies].input if m.role == "assistant"]
    assert [m.id for m in events[-1].input if m.role == "assistant"] == [
        *compacted,
        reply_ids[replies],
    ]
    assert [m.id for m in sample.messages if m.role == "assistant"] == [
        *compacted,
        *reply_ids[replies:],
    ]


@pytest.mark.parametrize("case", ["retry", "rewind", "side", "compacted_side"])
@pytest.mark.parametrize("dialect", DIALECTS)
def test_retry_rewind_and_side_call_never_take_another_replys_id(
    dialect: Dialect, case: str, tmp_path: Path, placements: list[set[str]]
) -> None:
    """`OK` replies keep their own ids or get new ones after a retry or a rewind, or beside a side call that returns `OK` too.

    A request after the retry could continue the retried request or the
    discarded reply's, so even the retry's own reply may get a new id.
    """
    sent: _Sent = []

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                conversation = _TextConversation(dialect, sent=sent)
                conversation.user("Start.")
                await conversation.generate()
                if case in ("side", "compacted_side"):
                    side = _TextConversation(dialect, sent=sent)
                    side.user("Side task.")
                    await side.generate()
                conversation.user("Next step.")
                await conversation.generate()
                if case == "retry":
                    del conversation.turns[-1]
                    await conversation.generate()
                elif case == "rewind":
                    conversation.turns = conversation.turns[:2]
                elif case == "compacted_side":
                    conversation.turns = [
                        conversation.user_turn("Summary."),
                        *conversation.turns[-2:],
                    ]
                conversation.user("Finish.")
                await conversation.generate()
                return bridge.state

        return execute

    events, sample = _reply_events(scaffold, ["OK", "OK", "OK", "Done"], tmp_path)
    reply_ids = [event.output.message.id for event in events]
    _assert_owned(events, sent, placements)
    final = [m.id for m in events[-1].input if m.role == "assistant"]
    if case in ("retry", "side"):
        assert [m.id for m in sample.messages if m.role == "assistant"] == [
            *final,
            reply_ids[-1],
        ]


_SEED_3_USERS = [
    *("Task: keep going.", "Task: keep going.", "Continue.", "Check.", "Check."),
    *("Continue.", "Continue.", "Continue.", "Task: keep going.", "Summary 2."),
    *("Continue.", "Continue.", "Continue.", "Continue.", "Task: keep going."),
    *("Check.", "Continue.", "Continue."),
]
_SEED_3_TRACE = [
    ("u0", "OK"),
    ("u0 a0 u1", "OK"),
    ("u2", "OK"),
    ("u0 a0 u3", "OK"),
    ("u0 a0 u3 a3 u4", "OK"),
    ("u2 a2 u5", "OK"),
    ("u0 a0 u3 a3 u4 a4 u6", "Sure"),
    ("u0 a0 u3 a3 u4 a4 u6", "Done"),
    ("u4 a4 u6 a7 u7", "OK"),
    ("u4 a4 u6 a7 u7 a8 u8", "OK"),
    ("u9 u7 a8 u8 a9 u10", "Done"),
    ("u9 u7 a8 u8 a9 u10", "OK"),
    ("u9 u7 a8 u8 a9 u10", "OK"),
    ("u11", "OK"),
    ("u11 a13 u12", "OK"),
    ("u12 a14 u13", "OK"),
    ("u9 u7 a8 u8 a9 u10 a12 u14", "Sure"),
    ("u9 u7 a8 u8 a9 u10 a12 u14 a16 u15", "OK"),
    ("u9 u7 a8 u8 a9 u10 a12 u14 a16 u15", "Done"),
    ("u12 a14 u13 a15 u16", "Done"),
    ("u2 a2 u5 a5 u17", "Done"),
]
"""Three conversations' requests from a randomized sweep (seed 3), as user turns `u<n>` and the replies `a<n>` to request `n`."""


@pytest.mark.parametrize("shape", ["side_reply", "side_alias", "seed_3_trace"])
@pytest.mark.parametrize("dialect", DIALECTS)
def test_compacted_conversation_never_takes_another_conversations_id(
    dialect: Dialect, shape: str, tmp_path: Path, placements: list[set[str]]
) -> None:
    """A request another conversation could have sent places none of its replies.

    After compaction, the main conversation sends the same request as a side
    conversation's latest one. That request holds the side's reply, or the
    new id the side's own compaction gave it; neither is the main reply's.
    The seed 3 trace mixes three conversations with retries, rewinds,
    summaries and slides.
    """
    sent: _Sent = []

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                if shape == "seed_3_trace":
                    conversation = _TextConversation(dialect, sent=sent)
                    turns = {
                        f"u{n}": conversation.user_turn(text)
                        for n, text in enumerate(_SEED_3_USERS)
                    }
                    for n, (labels, _) in enumerate(_SEED_3_TRACE):
                        conversation.turns = [turns[label] for label in labels.split()]
                        await conversation.generate()
                        turns[f"a{n}"] = conversation.turns[-1]
                    return bridge.state
                main = _TextConversation(dialect, sent=sent)
                main.user("Main task.")
                await main.generate()
                main.user("Continue.")
                await main.generate()
                side = _TextConversation(dialect, sent=sent)
                side.user("Continue." if shape == "side_reply" else "Side task.")
                await side.generate()
                side.user("Continue.")
                await side.generate()
                if shape == "side_alias":
                    del side.turns[:2]
                    side.user("Continue.")
                    await side.generate()
                del main.turns[:2]
                main.user("Continue.")
                await main.generate()
                return bridge.state

        return execute

    replies = (
        [reply for _, reply in _SEED_3_TRACE]
        if shape == "seed_3_trace"
        else ["OK"] * (4 if shape == "side_alias" else 3) + ["Done", "Bye"]
    )
    prompt = _SEED_3_USERS[0] if shape == "seed_3_trace" else "Main task."
    events, _ = _reply_events(scaffold, replies, tmp_path, prompt)
    _assert_owned(events, sent, placements)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_idle_conversation_never_takes_another_conversations_id(
    dialect: Dialect, tmp_path: Path, placements: list[set[str]]
) -> None:
    """A conversation resumed after the bridge stopped keeping its threads places none of its replies.

    A sub-agent replies `OK` to `Go.`, then waits while the main conversation
    and more one-shot side calls than the bridge keeps threads for run.
    Another conversation then replies `OK` to `Go.`. The sub-agent's next
    request holds that latest generation, but its own reply is the sub-agent's.
    """
    sent: _Sent = []
    side_calls = bridge_types._MAX_RECENT_THREADS

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                main = _TextConversation(dialect, sent=sent)
                main.user("Main task.")
                for step in range(3):
                    await main.generate()
                    main.user(f"Step {step}.")
                sub_agent = _TextConversation(dialect, sent=sent)
                for _ in range(2):
                    sub_agent.user("Go.")
                    await sub_agent.generate()
                await main.generate()
                for n in range(side_calls):
                    side = _TextConversation(dialect, sent=sent)
                    side.user(f"Question {n}?")
                    await side.generate()
                other = _TextConversation(dialect, sent=sent)
                other.user("Go.")
                await other.generate()
                sub_agent.user("Go.")
                await sub_agent.generate()
                return bridge.state

        return execute

    replies = [
        *("Plan.", "Did 0.", "Did 1.", "OK", "Done", "Did 2."),
        *(f"Answer {n}." for n in range(side_calls)),
        *("OK", "Bye"),
    ]
    events, _ = _reply_events(scaffold, replies, tmp_path, "Main task.")
    _assert_owned(events, sent, placements)


class _HeldRequests:
    """A request filter holding `count` one-shot `Unrelated` requests in generation until released."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.entered = 0
        self.all_entered = anyio.Event()
        self.release = anyio.Event()

    async def __call__(
        self,
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        text = messages[-1].text
        if not text.startswith("Unrelated"):
            return None
        self.entered += 1
        if self.entered == self.count:
            self.all_entered.set()
        await self.release.wait()
        return ModelOutput.from_content("mockllm/model", f"Answer to {text}")


@pytest.mark.parametrize("unrelated", [0, bridge_types._MAX_RECENT_THREADS])
@pytest.mark.parametrize("dialect", DIALECTS)
def test_latest_generation_keeps_its_reply_id_with_concurrent_requests(
    dialect: Dialect, unrelated: int, tmp_path: Path
) -> None:
    """Requests still generating don't push the latest generation's reply out of placement.

    After an established main conversation, a side conversation's short
    exchange is the latest generation. `unrelated` one-shot requests
    (concurrent sub-agents) then enter the bridge and stay in generation while
    the side conversation continues unchanged: its reply keeps the id it was
    generated with. The same holds on a bridge resumed from the checkpoint
    taken after the side exchange.
    """

    async def continue_side(
        side: _TextConversation, held: _HeldRequests, serving: AgentBridge
    ) -> None:
        with _serving(serving):
            async with anyio.create_task_group() as tg:
                for n in range(held.count):
                    one_shot = _TextConversation(dialect)
                    one_shot.user(f"Unrelated {n}?")
                    tg.start_soon(one_shot.generate)
                if held.count:
                    await held.all_entered.wait()
                await side.generate()
                held.release.set()

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            initial = list(state.messages)
            checkpointer = RecordingCheckpointer()
            held = _HeldRequests(unrelated)
            bridge = AgentBridge(state, filter=held, checkpointer=checkpointer)
            with _serving(bridge):
                main = _TextConversation(dialect)
                main.user("Main task.")
                for step in range(3):
                    await main.generate()
                    main.user(f"Step {step}.")
                side = _TextConversation(dialect)
                side.user("Side question?")
                await side.generate()
            snapshot = checkpointer.snapshot()
            side.user("And?")
            before = list(side.turns)
            await continue_side(side, held, bridge)
            held = _HeldRequests(unrelated)
            resumed = AgentBridge(
                AgentState(messages=initial),
                filter=held,
                checkpointer=RecordingCheckpointer(restored=snapshot, serialized=True),
            )
            side.turns = before
            await continue_side(side, held, resumed)
            return state

        return execute

    events, _ = _reply_events(
        scaffold,
        ["Plan.", "Did 0.", "Did 1.", "Side answer.", "Side done.", "Side done."],
        tmp_path,
        "Main task.",
    )
    side_reply = events[3].output.message.id
    uninterrupted, resumed = events[4].input, events[5].input
    assert [m.text for m in uninterrupted] == ["Side question?", "Side answer.", "And?"]
    assert uninterrupted[1].id == side_reply
    assert resumed[1].id == side_reply


@pytest.mark.parametrize("dialect", DIALECTS)
def test_repeated_compaction_never_revives_a_dropped_replys_id(
    dialect: Dialect, tmp_path: Path, placements: list[set[str]]
) -> None:
    """A reply kept by a second compaction, equal to the first compaction's dropped reply, never takes its id."""
    sent: _Sent = []

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                conversation = _TextConversation(dialect, sent=sent)
                conversation.user("Say OK.")
                await conversation.generate()
                for summary in ("Summary one.", "Summary two."):
                    conversation.turns = [
                        conversation.user_turn(summary),
                        conversation.turns[-1],
                    ]
                    conversation.user("Again.")
                    await conversation.generate()
                conversation.user("Thanks.")
                await conversation.generate()
                return bridge.state

        return execute

    events, sample = _reply_events(scaffold, ["OK", "OK", "Done", "Bye"], tmp_path)
    reply_ids = [event.output.message.id for event in events]
    _assert_owned(events, sent, placements)
    [retained] = [m.id for m in events[2].input if m.role == "assistant"]
    assert retained not in reply_ids
    assert [m.id for m in sample.messages if m.role == "assistant"] == [
        retained,
        *reply_ids[2:],
    ]


def test_compacted_identical_google_calls_never_link_another_calls_result(
    tmp_path: Path,
) -> None:
    """Ten equal Google calls with equal results, compacted to the last nine, link no wrong result.

    Google re-derives equal call ids, so nothing places the retained calls:
    they get new ids, and the latest call's host result stays unlinked.
    """
    host_events: list[ToolEvent] = []

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            from google.genai import types

            async with agent_bridge(state) as bridge:
                client = genai.Client(api_key="inspect")
                config = types.GenerateContentConfig(
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    )
                )
                contents: list[dict[str, Any]] = [
                    {"role": "user", "parts": [{"text": "Poll the job."}]}
                ]
                for _ in range(10):
                    response = await client.aio.models.generate_content(
                        model="inspect", contents=contents, config=config
                    )
                    host_events.extend(
                        _awaiting(bridge, bridge.state.output.message, result="pending")
                    )
                    assert response.candidates and response.candidates[0].content
                    reply = response.candidates[0].content.model_dump(
                        exclude_none=True, by_alias=True
                    )
                    answer = {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": "echo",
                                    "response": {"output": "pending"},
                                }
                            }
                        ],
                    }
                    contents += [reply, answer]
                summary = {"role": "user", "parts": [{"text": "Summary: pending."}]}
                await client.aio.models.generate_content(
                    model="inspect", contents=[summary, *contents[3:]], config=config
                )
                return bridge.state

        return execute

    log = eval(
        Task(dataset=[Sample(input="Poll the job.")], solver=scaffold()),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                *[
                    ModelOutput.for_tool_call("mockllm/model", "echo", {"text": "s"})
                    for _ in range(10)
                ],
                ModelOutput.from_content("mockllm/model", "Done."),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]

    assert log.status == "success", log.error
    assert log.samples
    events = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    reply_ids = {event.output.message.id for event in events[:10]}
    compacted = events[10].input
    assert not {m.id for m in compacted if m.role == "assistant"} & reply_ids
    assert host_events[-1].message_id is None
    assert all(event.message_id is not None for event in host_events[:-1])


@pytest.mark.parametrize("identical", [False, True], ids=["distinct", "identical"])
def test_completions_non_primary_choice_keeps_generated_id(
    identical: bool, tmp_path: Path
) -> None:
    """A scaffold that continues with an alternate choice never gives it another choice's id.

    Only the primary choice's thread places a request, so the alternate gets
    an id made for unplaced messages, whether or not it equals the primary.
    """

    @agent
    def choose_alternate() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                async with AsyncOpenAI(api_key="inspect") as client:
                    messages: list[dict[str, Any]] = [
                        {"role": "user", "content": "Choose a reply."}
                    ]
                    first = await client.chat.completions.create(
                        model="inspect", messages=cast(Any, messages)
                    )
                    messages.append(
                        first.choices[1].message.model_dump(exclude_none=True)
                    )
                    messages.append({"role": "user", "content": "Continue."})
                    await client.chat.completions.create(
                        model="inspect", messages=cast(Any, messages)
                    )
                return bridge.state

        return execute

    choices = ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(message=ChatMessageAssistant(content="choice-zero")),
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content="choice-zero" if identical else "choice-one"
                )
            ),
        ],
    )
    log = eval(
        Task(dataset=[Sample(input="Choose a reply.")], solver=choose_alternate()),
        model=get_model(
            "mockllm/model",
            custom_outputs=[choices, ModelOutput.from_content("mockllm/model", "Done")],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    assert log.samples
    first_event, second_event = [
        event for event in log.samples[0].events if isinstance(event, ModelEvent)
    ]
    choice_ids = [choice.message.id for choice in first_event.output.choices]
    assert second_event.input[1].id not in choice_ids


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
            await self.bridge._track_state(
                rebuilt, ModelOutput.from_message(output), []
            )
        return [m.id or "" for m in rebuilt]


def _call(call_id: str) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content="",
        tool_calls=[ToolCall(id=call_id, function="bash", arguments={"cmd": "ls"})],
    )


def _result(call_id: str, content: str = "a.txt") -> ChatMessageTool:
    return ChatMessageTool(content=content, tool_call_id=call_id, function="bash")


@pytest.mark.parametrize(
    "operation",
    ["content_hash", "edited_message", "unplaced_key", "stable_ids"],
)
def test_yaml_mixed_keys_are_accepted_by_message_identity(operation: str) -> None:
    """A parsed YAML object with integer and string keys has stable identity."""
    info = ToolInfo(
        name="read",
        description="Read data.",
        parameters=ToolParams(properties={"data": ToolParam(type="object")}),
    )
    call = parse_tool_call("call", "read", "1: one\nname: value", [info])
    assert call.parse_error is None
    assert call.arguments == {"data": {1: "one", "name": "value"}}
    reply = ChatMessageAssistant(id=uuid(), content="", tool_calls=[call])

    if operation == "content_hash":
        assert content_hash(reply) == content_hash(reply.model_copy(deep=True))
    elif operation == "edited_message":
        assert edited_message(reply, content="edited").id != reply.id
    elif operation == "unplaced_key":
        assert _unplaced_key(reply) == _unplaced_key(reply.model_copy(deep=True))
    else:
        stable_message_ids()([reply])
        assert reply.id is not None


def test_responses_dedupe_tells_a_lone_surrogate_from_its_escaped_text() -> None:
    """Assistant text whose `internal` holds a lone surrogate isn't a duplicate of one holding its escaped text."""

    def text(internal_id: str) -> ContentText:
        return ContentText(text="same", internal={"id": internal_id})

    content: list[Content] = [text("msg \ud800"), text("msg \\ud800")]
    assert filter_duplicate_assistant_content([*content, content[1]]) == content


def _compacted_to(reply: ChatMessageAssistant) -> list[ChatMessage]:
    """A compacted conversation keeping `reply`, ready for the next call."""
    return [
        ChatMessageUser(content="Summary: done once."),
        reply,
        ChatMessageUser(content="Once more."),
    ]


def _transported(reply: ChatMessageAssistant, call_id: str) -> ChatMessageAssistant:
    """`reply` as the Google dialect hands it to a scaffold: call ids re-derived."""
    assert reply.tool_calls
    [call] = reply.tool_calls
    return reply.model_copy(
        update={"tool_calls": [ToolCall(call_id, call.function, call.arguments)]}
    )


@pytest.mark.parametrize("placed", [True, False])
async def test_compaction_after_re_derived_ids_keeps_the_latest_replys_id(
    placed: bool,
) -> None:
    """A retained latest reply equal to an earlier one, once both came back transported.

    Generated after a compaction that kept a later reply, it is the latest
    generation's reply and keeps its id: the conversation before compaction
    can't hold that reply before an equal call. Generated before, nothing
    tells it from the earlier one: it isn't placed, and its host result stays
    unlinked.
    """
    task = ChatMessageUser(content="List the files twice.")
    first, second = _call("toolu_1"), _call("toolu_2")
    # Google derives the call id from the function and arguments, so both
    # replies come back with the same one
    first_back, second_back = (
        _transported(first, "call_bash_1"),
        _transported(second, "call_bash_1"),
    )
    bridge = AgentBridge(AgentState(messages=[task]))
    scaffold = _Scaffold(bridge)
    await scaffold.request([task], first)
    bridge._record_transported_reply(first, [first_back])
    old_result = _result("call_bash_1", "OLD")
    if placed:
        listed = ChatMessageAssistant(content="Listed.")
        await scaffold.request([task, first_back, old_result], listed)
        kept = _compacted_to(listed)
        await scaffold.request(kept, second)
    else:
        kept = [ChatMessageUser(content="Summary: listed the files once.")]
        await scaffold.request([task, first_back, old_result], second)
    bridge._record_transported_reply(second, [second_back])
    [event] = _awaiting(bridge, second)

    with recording_placements() as placements:
        ids = await scaffold.request(
            [*kept, second_back, _result("call_bash_1", "NEW")]
        )

    assert first.id is not None and second.id is not None
    reply, result = ids[-2], ids[-1]
    if placed:
        assert reply == edited_id(second.id, scaffold.sent[-2])
        assert event.message_id == result
    else:
        assert reply not in placements[0]
        assert event.message_id is None


@pytest.mark.parametrize(
    "arguments",
    ["1: one\nname: value", '{"data": {"1": "one", "name": "value"}}'],
    ids=["yaml-mixed-keys", "json-string-keys"],
)
def test_google_reply_with_non_string_argument_keys_keeps_its_id(
    arguments: str, tmp_path: Path
) -> None:
    """A reply whose parsed arguments have integer keys is sent and recognized as JSON."""
    info = ToolInfo(
        name="read",
        description="Read data.",
        parameters=ToolParams(properties={"data": ToolParam(type="object")}),
    )
    call = parse_tool_call("call", "read", arguments, [info])
    assert call.parse_error is None
    sent_args: list[dict[str, Any]] = []

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                from google.genai import types

                client = genai.Client(api_key="inspect")
                config = types.GenerateContentConfig(
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    )
                )
                contents: list[dict[str, Any]] = [
                    {"role": "user", "parts": [{"text": PROMPT}]}
                ]
                response = await client.aio.models.generate_content(
                    model="inspect", contents=contents, config=config
                )
                assert response.candidates and response.candidates[0].content
                reply = response.candidates[0].content
                assert reply.parts and reply.parts[0].function_call
                sent_args.append(reply.parts[0].function_call.args or {})
                contents += [
                    reply.model_dump(exclude_none=True, by_alias=True),
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": "read",
                                    "response": {"output": "ok"},
                                }
                            }
                        ],
                    },
                ]
                await client.aio.models.generate_content(
                    model="inspect", contents=contents, config=config
                )
                return bridge.state

        return execute

    log = eval(
        Task(dataset=[Sample(input=PROMPT)], solver=scaffold()),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_message(
                    ChatMessageAssistant(content="", tool_calls=[call])
                ),
                ModelOutput.from_content("mockllm/model", "Done."),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]

    assert log.status == "success", log.error
    assert sent_args == [{"data": {"1": "one", "name": "value"}}]
    assert log.samples
    first, second = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    returned = second.input[1]
    assert returned.id == edited_id(first.output.message.id, returned)


async def test_resumed_bridge_keeps_the_main_threads_id() -> None:
    """A side call's equal output recorded first doesn't take the main thread's id, before or after a resume.

    The side reply could stand in for the main reply, so the main reply gets a
    new id. The checkpoint keeps the side thread, so the resumed bridge
    decides the same.
    """
    task = ChatMessageUser(content="List the files.")
    side, first = _call("call_1"), _call("call_1")
    checkpointer = RecordingCheckpointer()
    scaffold = _Scaffold(
        AgentBridge(AgentState(messages=[task]), checkpointer=checkpointer)
    )
    await scaffold.request([ChatMessageUser(content="Is ls safe?")], side)
    await scaffold.request([task], first)
    snapshot = checkpointer.snapshot()
    before = await scaffold.request([task, first, _result("call_1")])

    resumed = _Scaffold(
        AgentBridge(
            AgentState(messages=[task]),
            checkpointer=RecordingCheckpointer(restored=snapshot, serialized=True),
        )
    )
    after = await resumed.request([task, first, _result("call_1")])

    assert after[0] == before[0]
    assert {before[1], after[1]}.isdisjoint({side.id, first.id})


@contextlib.contextmanager
def _serving(bridge: AgentBridge) -> Iterator[None]:
    """Serve the dialect clients' requests with `bridge`."""
    bridge_module.init_bridge_request_patch()
    token = bridge_module._patch_config.set(
        bridge_module.PatchConfig(enabled=True, bridge=bridge)
    )
    try:
        yield
    finally:
        bridge_module._patch_config.reset(token)


@pytest.mark.parametrize("checkpoint", ["current", "without_placement"])
@pytest.mark.parametrize("dialect", DIALECTS)
def test_resumed_bridge_never_gives_a_conversation_another_conversations_ids(
    dialect: Dialect, checkpoint: str, tmp_path: Path, placements: list[set[str]]
) -> None:
    """A compacted main conversation takes no side conversation's ids, before or after a resume.

    A side conversation repeats the main one's later replies and becomes the
    tracked thread. The main conversation then slides away its first exchange
    and sends the replies it shares with the side, to the bridge and to one
    resumed from a checkpoint taken before. Neither gives them the side's
    ids, including the new id the side's second request gave its copy. A
    checkpoint without the bridge's matching evidence (written before it was
    kept) places none of the replies it recorded.
    """
    sent: _Sent = []

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            initial = list(state.messages)
            checkpointer = RecordingCheckpointer()
            with _serving(AgentBridge(state, checkpointer=checkpointer)):
                main = _TextConversation(dialect, sent=sent)
                for text in ("Main task.", "Next.", "Go."):
                    main.user(text)
                    await main.generate()
                side = _TextConversation(dialect, sent=sent)
                for text in ("Next.", "Go."):
                    side.user(text)
                    await side.generate()
                snapshot = checkpointer.snapshot()
                del main.turns[:2]
                main.user("Finish.")
                await main.generate()
            if checkpoint == "without_placement":
                snapshot.pop("bridge_placement", None)
            resumed = AgentBridge(
                AgentState(messages=initial),
                checkpointer=RecordingCheckpointer(restored=snapshot, serialized=True),
            )
            with _serving(resumed):
                main.turns.pop()
                await main.generate()
            return state

        return execute

    events, _ = _reply_events(
        scaffold,
        ["Plan.", "OK", "Done", "OK", "Done", "Bye", "Bye"],
        tmp_path,
        "Main task.",
    )
    _assert_owned(events, sent, placements)


@pytest.mark.parametrize("checkpoint", ["current", "without_reach"])
@pytest.mark.parametrize("dialect", DIALECTS)
def test_resumed_bridge_places_as_uninterrupted_after_a_compacted_side_leaves_the_window(
    dialect: Dialect, checkpoint: str, tmp_path: Path, placements: list[set[str]]
) -> None:
    """A resumed bridge remembers how many replies a forgotten conversation had.

    A four-reply side conversation, whose first reply is `OK`, compacts to a
    branch that keeps that reply. The main conversation's third reply is
    also `OK`. One-shot calls push the side conversation out of the kept
    threads, and a checkpoint is taken while the branch is still kept. One
    more call pushes the branch out too, and the main conversation goes on.
    The side conversation could hold its three replies, so neither the
    bridge nor one resumed from the checkpoint places them, and both give
    them the same ids. A checkpoint without the reach (the field removed,
    as in one written before it was kept) falls back to counting the threads
    it restores: only the branch's two replies, so the resumed bridge places
    the main conversation's replies where the uninterrupted one didn't.
    """
    sent: _Sent = []
    one_shots = bridge_types._MAX_RECENT_THREADS - 2

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            initial = list(state.messages)
            checkpointer = RecordingCheckpointer()

            async def ask(text: str) -> None:
                one_shot = _TextConversation(dialect, sent=sent)
                one_shot.user(text)
                await one_shot.generate()

            async def continue_main(main: _TextConversation) -> None:
                await ask("Question 99?")
                main.user("Fourth main.")
                await main.generate()

            with _serving(AgentBridge(state, checkpointer=checkpointer)):
                main = _TextConversation(dialect, sent=sent)
                main.user("Main task.")
                await main.generate()
                side = _TextConversation(dialect, sent=sent)
                for n in range(4):
                    side.user(f"Side {n}.")
                    await side.generate()
                side.turns = [side.user_turn("Summary."), side.turns[1]]
                side.user("Go.")
                await side.generate()
                for text in ("Next main.", "Third main."):
                    main.user(text)
                    await main.generate()
                for n in range(one_shots):
                    await ask(f"Question {n}?")
                snapshot = checkpointer.snapshot()
                before = list(main.turns)
                await continue_main(main)
            if checkpoint == "without_reach":
                del snapshot["bridge_placement"]["held_replies"]
            resumed = AgentBridge(
                AgentState(messages=initial),
                checkpointer=RecordingCheckpointer(restored=snapshot, serialized=True),
            )
            with _serving(resumed):
                main.turns = before
                await continue_main(main)
            return state

        return execute

    replies = [
        *("Plan.", "OK", "Side 1.", "Side 2.", "Side 3.", "Branch.", "Did main."),
        "OK",
        *(f"Answer {n}." for n in range(one_shots)),
        *("Evicted.", "Bye", "Evicted.", "Bye"),
    ]
    events, _ = _reply_events(scaffold, replies, tmp_path, "Main task.")
    _assert_owned(events, sent, placements)
    uninterrupted, resumed = events[-3], events[-1]
    assert len(uninterrupted.input) == 7
    assert placements[-3] == set()
    if checkpoint == "current":
        assert placements[-1] == placements[-3]
        # the new user message gets a new id in each run
        assert [m.id for m in resumed.input[:6]] == [
            m.id for m in uninterrupted.input[:6]
        ]
    else:
        assert placements[-1] == {m.id for m in resumed.input[:6]}
        [main_ok] = [
            event.output.message.id
            for event in events
            if event.input[0].text == "Main task." and event.output.completion == "OK"
        ]
        assert resumed.input[5].id == main_ok != uninterrupted.input[5].id


@pytest.mark.parametrize("checkpointed_again", [False, True])
@pytest.mark.parametrize("dialect", DIALECTS)
def test_side_call_after_resume_keeps_the_main_threads_ids(
    dialect: Dialect, checkpointed_again: bool, tmp_path: Path
) -> None:
    """A side call right after a resume doesn't displace the restored main thread.

    The main conversation generates once and a checkpoint is taken; then a
    one-shot side call runs and the main conversation continues. Run on the
    bridge and on one resumed from the checkpoint, the continuation sends
    the main reply under the id it was generated with in both. With
    `checkpointed_again`, the resumed bridge is checkpointed again before it
    sees a generation, and the bridge resumed from that checkpoint runs the
    side call: the checkpoint holds the restored main thread, while the
    scaffold still starts from its initial prompt.
    """
    pending: list[tuple[list[str | None], dict[str, Any], dict[str, Any]]] = []

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            initial = list(state.messages)
            checkpointer = RecordingCheckpointer()
            main = _TextConversation(dialect)
            main.user("Main task.")
            with _serving(AgentBridge(state, checkpointer=checkpointer)):
                await main.generate()
                before = list(main.turns)
                snapshot = checkpointer.snapshot()
                side = _TextConversation(dialect)
                side.user("Detect shell.")
                await side.generate()
                main.user("Continue main.")
                await main.generate()
            if checkpointed_again:
                again = RecordingCheckpointer(restored=snapshot, serialized=True)
                started = AgentBridge(AgentState(messages=initial), checkpointer=again)
                pending.append(
                    (
                        [m.id for m in started.state.messages],
                        snapshot,
                        snapshot := again.snapshot(),
                    )
                )
            resumed = AgentBridge(
                AgentState(messages=initial),
                checkpointer=RecordingCheckpointer(restored=snapshot, serialized=True),
            )
            with _serving(resumed):
                side = _TextConversation(dialect)
                side.user("Detect shell.")
                await side.generate()
                main.turns = before
                main.user("Continue main.")
                await main.generate()
            return state

        return execute

    events, _ = _reply_events(
        scaffold,
        ["Unique main answer.", "bash", "Done", "bash", "Done"],
        tmp_path,
        "Main task.",
    )
    generated = events[0].output.message.id
    assert generated is not None
    uninterrupted, resumed = events[2].input, events[4].input
    assert uninterrupted[1].id == generated
    # the continuation's new user message gets a new id in each run
    assert [m.id for m in resumed[:2]] == [m.id for m in uninterrupted[:2]]
    for started, first, second in pending:
        assert started == [uninterrupted[0].id]
        assert second == first


@pytest.mark.parametrize("checkpoint", ["current", "without_tracking"])
async def test_resumed_bridge_tracks_the_thread_the_checkpointed_one_would(
    checkpoint: str,
) -> None:
    """A resumed bridge keeps the restored main thread tracked through a side call.

    Its state is the restored main thread from the side call on, as the
    checkpointed bridge's is. A checkpoint without the tracking state
    (written before it was kept) tracks the side call instead, and the main
    reply then takes none of the side call's ids.
    """
    task = ChatMessageUser(content="Main task.")
    answer = ChatMessageAssistant(content="Unique main answer.")
    side: list[ChatMessage] = [ChatMessageUser(content="Detect shell.")]
    checkpointer = RecordingCheckpointer()
    bridge = AgentBridge(AgentState(messages=[task]), checkpointer=checkpointer)
    await _Scaffold(bridge).request([task], answer)
    snapshot = checkpointer.snapshot()
    if checkpoint == "without_tracking":
        del snapshot["bridge_placement"]["tracking"]
    resumed = AgentBridge(
        AgentState(messages=[task]),
        checkpointer=RecordingCheckpointer(restored=snapshot, serialized=True),
    )
    assert [m.id for m in resumed.state.messages] == [task.id]

    states: list[list[str | None]] = []
    ids: list[list[str]] = []
    for current in (bridge, resumed):
        scaffold = _Scaffold(current)
        await scaffold.request(side, ChatMessageAssistant(content="bash"))
        states.append([m.id for m in current.state.messages])
        continued = await scaffold.request(
            [task, answer, ChatMessageUser(content="Continue main.")]
        )
        ids.append(continued[:2])

    assert states[0] == [task.id, answer.id]
    assert ids[0] == [task.id, answer.id]
    if checkpoint == "current":
        assert states[1] == states[0] and ids[1] == ids[0]
    else:
        assert len(states[1]) == 2 and states[1][0] not in (task.id, answer.id)
        assert ids[1][1] not in states[1]


_UNTRUSTED_SUFFIXES = ["1", "\ud800", "\\ud800"]
_UNTRUSTED_SUFFIX_IDS = ["ordinary", "lone surrogate", "literal backslash"]


def _written_checkpoint(checkpointer: RecordingCheckpointer) -> dict[str, Any]:
    # the tracked state as `CheckpointerImpl._write_host_context` writes it
    agent_state = {key: callback() for key, callback in checkpointer.callbacks.items()}
    return cast(dict[str, Any], json.loads(to_json_str_safe(agent_state)))


def _call_exchange(dialect: Dialect, suffix: str) -> list[dict[str, Any]]:
    """A scaffold-run call of `read_<suffix>` (id `call_<suffix>`) and its result."""
    call_id, name = f"call_{suffix}", f"read_{suffix}"
    user: dict[str, Any] = {"role": "user", "content": "Read the file."}
    if dialect == "completions":
        return [
            user,
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": call_id, "content": "a.txt"},
        ]
    elif dialect == "responses":
        return [
            user,
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": "{}",
            },
            {"type": "function_call_output", "call_id": call_id, "output": "a.txt"},
        ]
    elif dialect == "anthropic":
        return [
            user,
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": call_id, "name": name, "input": {}}
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": call_id, "content": "a.txt"}
                ],
            },
        ]
    return [
        {"role": "user", "parts": [{"text": "Read the file."}]},
        {"role": "model", "parts": [{"functionCall": {"name": name, "args": {}}}]},
        {
            "role": "user",
            "parts": [
                {"functionResponse": {"name": name, "response": {"output": "a.txt"}}}
            ],
        },
    ]


async def _send(dialect: Dialect, wire: list[dict[str, Any]]) -> None:
    conversation = _TextConversation(dialect)
    conversation.turns = [[item] for item in wire]
    await conversation.generate()


@contextlib.contextmanager
def _active_mock_model(*outputs: ModelOutput) -> Iterator[None]:
    """Serve generations with `outputs`, outside an eval and its sample.

    Outside an eval, log writing doesn't need to encode the lone surrogates.
    Outside a sample, provider assistant-internal state would be recorded in
    the process-wide default, where later tests that checkpoint would write
    it, so it is bound fresh here and cleared on exit, as a sample does.
    """
    init_sample_assistant_internal()
    token = active_model_context_var.set(
        get_model("mockllm/model", custom_outputs=list(outputs))
    )
    try:
        yield
    finally:
        active_model_context_var.reset(token)
        init_sample_assistant_internal()


@pytest.mark.parametrize("suffix", _UNTRUSTED_SUFFIXES, ids=_UNTRUSTED_SUFFIX_IDS)
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_scaffold_call_ids_with_a_lone_surrogate_keep_their_ids_across_a_checkpoint(
    dialect: Dialect, suffix: str
) -> None:
    """A scaffold's call whose id or name holds a lone surrogate is checkpointed, and keeps its ids once resumed.

    Each request sends the same call and result. The tracked state is
    written as the checkpointer writes it, and a bridge resumed from it
    gives the request the ids the checkpointed bridge gives it.
    """
    wire = _call_exchange(dialect, suffix)
    task = ChatMessageUser(content="Read the file.")
    checkpointer = RecordingCheckpointer()
    bridge = AgentBridge(AgentState(messages=[task]), checkpointer=checkpointer)
    ids: list[list[str | None]] = []
    with _active_mock_model(*[ModelOutput.from_content("mockllm/model", "Done.")] * 3):
        with _serving(bridge):
            await _send(dialect, wire)
            ids.append([m.id for m in bridge.state.messages[:3]])
            resumed = AgentBridge(
                AgentState(messages=[task]),
                checkpointer=RecordingCheckpointer(
                    restored=_written_checkpoint(checkpointer), serialized=True
                ),
            )
            assert resumed._placement_state() == bridge._placement_state()
            await _send(dialect, wire)
            ids.append([m.id for m in bridge.state.messages[:3]])
        with _serving(resumed):
            await _send(dialect, wire)
            ids.append([m.id for m in resumed.state.messages[:3]])

    assert len(bridge.state.messages) == 4
    assert ids[0] == ids[1] == ids[2]


@pytest.mark.parametrize("suffix", _UNTRUSTED_SUFFIXES, ids=_UNTRUSTED_SUFFIX_IDS)
async def test_google_unmatched_function_response_with_a_lone_surrogate_is_checkpointed(
    suffix: str,
) -> None:
    """A Google function response without a call, whose name holds a lone surrogate, leaves state the checkpointer writes."""
    name = f"read_{suffix}"
    wire: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": "Read the file."}]},
        {
            "role": "user",
            "parts": [
                {"functionResponse": {"name": name, "response": {"output": "a.txt"}}}
            ],
        },
    ]
    checkpointer = RecordingCheckpointer()
    bridge = AgentBridge(AgentState(messages=[]), checkpointer=checkpointer)
    with _active_mock_model(ModelOutput.from_content("mockllm/model", "Done.")):
        with _serving(bridge):
            await _send("google", wire)

    written = _written_checkpoint(checkpointer)
    results = [m for m in bridge.state.messages if isinstance(m, ChatMessageTool)]
    assert [m.function for m in results] == [name]
    assert written["bridge_message_ids"]


@pytest.mark.parametrize("suffix", _UNTRUSTED_SUFFIXES, ids=_UNTRUSTED_SUFFIX_IDS)
async def test_google_reply_calling_a_name_with_a_lone_surrogate_is_returned(
    suffix: str,
) -> None:
    """A model call whose function name holds a lone surrogate reaches a Google scaffold, and its reply keeps its id."""
    name = f"read_{suffix}"
    call = ToolCall(id="call", function=name, arguments={"path": "a.txt"})
    bridge = AgentBridge(AgentState(messages=[]))
    client = genai.Client(api_key="inspect")
    contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": PROMPT}]}]
    with _active_mock_model(
        ModelOutput.from_message(ChatMessageAssistant(content="", tool_calls=[call])),
        ModelOutput.from_content("mockllm/model", "Done."),
    ):
        with _serving(bridge):
            response = await client.aio.models.generate_content(
                model="inspect", contents=contents
            )
            first = bridge.state.output.message
            assert response.candidates and response.candidates[0].content
            reply = response.candidates[0].content
            assert reply.parts and reply.parts[0].function_call
            assert reply.parts[0].function_call.name == name
            contents += [
                reply.model_dump(exclude_none=True, by_alias=True),
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": name,
                                "response": {"output": "ok"},
                            }
                        }
                    ],
                },
            ]
            await client.aio.models.generate_content(model="inspect", contents=contents)

    returned = bridge.state.messages[1]
    assert returned.id == edited_id(first.id or "", returned)


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
    """Form comparisons and id-list reads to match one request on a repetitive history."""
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

    _CountingList.reads = 0
    request = (
        [ChatMessageUser(content="Summary: said OK a lot."), *history[1:]]
        if compacted
        else history
    )
    with patch.object(bridge, "_matches", wraps=bridge._matches) as matches:
        await scaffold.request(request + [ChatMessageUser(content="continue")])
    return matches.call_count + _CountingList.reads


@pytest.mark.parametrize("compacted", [False, True])
async def test_matching_work_is_linear_in_a_repetitive_conversation(
    compacted: bool,
) -> None:
    small = await _matching_work(100, compacted)
    large = await _matching_work(800, compacted)
    # linear is 8x; the quadratic matching this replaced was 64x
    assert large <= 12 * small


def _concurrent_candidates_work(dialect: Dialect, n: int, tmp_path: Path) -> int:
    """Message comparisons to match the request after `n` concurrent generations of an `n`-reply history."""
    work = 0

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            phase = "history"
            entered = 0
            all_entered = anyio.Event()

            async def candidates(*_: Any) -> ModelOutput:
                nonlocal entered
                if phase == "candidates":
                    entered += 1
                    if entered == n:
                        all_entered.set()
                    await all_entered.wait()
                reply = "OK" if phase == "history" else "Different."
                return ModelOutput.from_content("mockllm/model", reply)

            async with agent_bridge(state, filter=candidates) as bridge:
                main = _TextConversation(dialect)
                main.user("Main task.")
                for _ in range(n):
                    await main.generate()
                    main.user("Continue.")
                phase = "candidates"
                branches = [_TextConversation(dialect) for _ in range(n)]
                for branch in branches:
                    branch.turns = main.turns.copy()
                await tg_collect([branch.generate for branch in branches])
                phase = "final"
                with patch.object(bridge, "_matches", wraps=bridge._matches) as matches:
                    await main.generate()
                nonlocal work
                work = matches.call_count
                return bridge.state

        return execute

    log = eval(
        Task(dataset=[Sample(input="Main task.")], solver=scaffold()),
        model=get_model("mockllm/model"),
        log_dir=str(tmp_path / str(n)),
    )[0]
    assert log.status == "success", log.error
    return work


@pytest.mark.parametrize("dialect", DIALECTS)
def test_matching_work_is_linear_with_concurrent_candidates(
    dialect: Dialect, tmp_path: Path
) -> None:
    """Matching after concurrent generations of the same history is linear in their number.

    Every candidate's output stays a reason the next request may not be a
    retry, and none is compared with each reply.
    """
    # both above the recent threads the bridge keeps (`_MAX_RECENT_THREADS`)
    small = _concurrent_candidates_work(dialect, 16, tmp_path)
    large = _concurrent_candidates_work(dialect, 128, tmp_path)
    # linear is 8x; comparing each output with each reply is 64x
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
    assert answered.id == edited_id(submitted.id, answered)
    assert final.id == edited_id(answered.id, final)
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
    assert prefixed.id == edited_id(child.id, prefixed)


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


def test_response_filter_change_of_call_type_gets_a_new_id(tmp_path: Path) -> None:
    """A filter that only turns a function call into a custom call edits the reply."""

    async def to_custom(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        for call in output.message.tool_calls or []:
            call.type = "custom"
        return output

    item_types: list[str] = []

    @agent
    def custom_scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state, response_filter=to_custom) as bridge:
                async with AsyncOpenAI(api_key="inspect") as client:
                    input: list[dict[str, Any]] = [{"role": "user", "content": PROMPT}]
                    for _ in range(2):
                        response = await client.responses.create(
                            model="inspect",
                            input=cast(Any, input),
                            tools=[{"type": "custom", "name": "patch"}],
                        )
                        for item in response.output:
                            item_types.append(item.type)
                            input.append(item.model_dump(exclude_none=True))
                            if item.type == "custom_tool_call":
                                input.append(
                                    {
                                        "type": "custom_tool_call_output",
                                        "call_id": item.call_id,
                                        "output": "patched",
                                    }
                                )
                return bridge.state

        return execute

    log = eval(
        Task(dataset=[Sample(input=PROMPT)], solver=custom_scaffold()),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call("mockllm/model", "patch", {"input": "x"}),
                ModelOutput.from_content("mockllm/model", "Patched."),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]

    sample = _assert_contract(log)
    assert "custom_tool_call" in item_types and "function_call" not in item_types
    generated = [e for e in sample.events if isinstance(e, ModelEvent)][0]
    handed = next(m for m in sample.messages if isinstance(m, ChatMessageAssistant))
    assert generated.output.message.tool_calls
    assert generated.output.message.tool_calls[0].type == "function"
    assert handed.tool_calls and handed.tool_calls[0].type == "custom"
    assert handed.id == edited_id(generated.output.message.id, handed)
    assert handed.id != generated.output.message.id
    native = edited_message(generated.output.message, tool_calls=handed.tool_calls)
    assert native.id == handed.id


async def test_scaffold_edit_of_a_reasoning_summary_gets_a_new_id() -> None:
    """A changed reasoning summary is a different message, which isn't placed as the reply."""
    task = ChatMessageUser(content="Hello")
    reply = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="signature", summary="Greet.", redacted=True),
            ContentText(text="Hi there."),
        ]
    )
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], reply)
    content: list[Content] = [
        ContentReasoning(reasoning="signature", summary="Wave.", redacted=True),
        ContentText(text="Hi there."),
    ]

    ids = await scaffold.request(
        [
            task,
            ChatMessageAssistant(content=content),
            ChatMessageUser(content="Again"),
        ]
    )

    assert ids[1] != reply.id


def _awaiting(
    bridge: AgentBridge,
    reply: ChatMessageAssistant,
    executions: int = 1,
    index: int = 0,
    result: str = "",
) -> list[ToolEvent]:
    """Host tool events for call `index` of `reply`, as executing a granted call records them."""
    assert reply.id is not None and reply.tool_calls is not None
    call = reply.tool_calls[index]
    events = [
        ToolEvent(
            id=call.id, function=call.function, arguments=call.arguments, result=result
        )
        for _ in range(executions)
    ]
    for event in events:
        bridge._await_result_message(
            handed_calls(bridge, reply.id, reply.tool_calls)[index], event
        )
    return events


def _waiting(bridge: AgentBridge) -> int:
    return sum(
        event is not None
        for reply in bridge._awaited_results.values()
        for event in reply.events.values()
    )


def _same_calls(*call_ids: str) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(id=call_id, function="bash", arguments={"cmd": "cat a.txt"})
            for call_id in call_ids
        ],
    )


async def test_host_result_is_linked_when_the_scaffold_first_sends_it() -> None:
    """A request with the reply but not its result (a side call) leaves the event waiting."""
    task = ChatMessageUser(content="List the files.")
    reply = _call("call_1")
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], reply)
    [event] = _awaiting(scaffold.bridge, reply)

    await scaffold.request([task, reply, ChatMessageUser(content="Title?")])
    assert event.message_id is None
    ids = await scaffold.request([task, reply, _result("call_1")])
    assert event.message_id == ids[2]
    await scaffold.request([task, reply, _result("call_1", "changed")])
    assert event.message_id == ids[2]


async def test_host_result_after_a_reply_copy_given_its_id_by_content_stays_unlinked() -> (
    None
):
    """A copy of a handed reply that got the reply's id by content leaves its calls unlinked.

    After compaction the copy isn't placed: it takes the id an equal message
    had, which an equal reply's copy would take too. The next request, which
    continues it, places it under that id, but which reply it is stays
    unknown, so its result doesn't link.
    """
    task = ChatMessageUser(content="List the files.")
    reply = _call("call_1")
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], reply)
    [event] = _awaiting(scaffold.bridge, reply)
    await scaffold.request([task, reply, ChatMessageUser(content="Title?")])
    summary = ChatMessageUser(content="Summary: listing.")

    compacted = await scaffold.request([summary, reply])
    ids = await scaffold.request([summary, reply, _result("call_1")])

    assert compacted[1] == ids[1] == reply.id
    assert event.message_id is None
    assert _waiting(scaffold.bridge) == 0


@pytest.mark.parametrize("ambiguity", ["two results", "two executions"])
async def test_ambiguous_host_results_stay_unlinked(ambiguity: str) -> None:
    task = ChatMessageUser(content="List the files.")
    reply = _call("call_1")
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], reply)
    events = _awaiting(
        scaffold.bridge, reply, executions=2 if ambiguity == "two executions" else 1
    )
    results = [_result("call_1")]
    if ambiguity == "two results":
        results.append(_result("call_1", "b.txt"))

    await scaffold.request([task, reply, *results])
    await scaffold.request([task, reply, _result("call_1")])

    assert all(event.message_id is None for event in events)
    assert _waiting(scaffold.bridge) == 0


async def test_host_results_of_a_reply_with_reordered_calls_stay_unlinked() -> None:
    """A scaffold that reorders a reply's calls edits it, so the reply isn't placed and its results don't link."""
    task = ChatMessageUser(content="Read a.txt twice.")
    reply = _same_calls("call_a", "call_b")
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], reply)
    [event_a] = _awaiting(scaffold.bridge, reply, index=0)
    [event_b] = _awaiting(scaffold.bridge, reply, index=1)

    reordered = reply.model_copy(deep=True)
    reordered.tool_calls = list(reversed(reordered.tool_calls or []))
    ids = await scaffold.request(
        [task, reordered, _result("call_b", "B"), _result("call_a", "A")]
    )

    assert reply.id not in ids
    assert (event_a.message_id, event_b.message_id) == (None, None)


async def test_host_results_of_calls_sharing_an_id_stay_unlinked() -> None:
    """Two calls under one call id and one result: neither event can claim it."""
    task = ChatMessageUser(content="Read a.txt twice.")
    reply = _same_calls("call_1", "call_1")
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], reply)
    events = [
        *_awaiting(scaffold.bridge, reply, index=0),
        *_awaiting(scaffold.bridge, reply, index=1),
    ]

    await scaffold.request([task, reply, _result("call_1")])

    assert [event.message_id for event in events] == [None, None]


async def test_host_results_with_changed_arguments_stay_unlinked() -> None:
    """A copy that keeps the call ids but swaps the arguments identifies neither call."""
    task = ChatMessageUser(content="Read a.txt and b.txt.")
    reply = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(id="call_a", function="bash", arguments={"cmd": "cat a.txt"}),
            ToolCall(id="call_b", function="bash", arguments={"cmd": "cat b.txt"}),
        ],
    )
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], reply)
    events = [
        *_awaiting(scaffold.bridge, reply, index=0),
        *_awaiting(scaffold.bridge, reply, index=1),
    ]

    swapped = reply.model_copy(deep=True)
    assert swapped.tool_calls is not None
    first, second = swapped.tool_calls
    first.arguments, second.arguments = second.arguments, first.arguments
    await scaffold.request(
        [task, swapped, _result("call_a", "B"), _result("call_b", "A")]
    )

    assert [event.message_id for event in events] == [None, None]


@pytest.mark.parametrize("delay", ["split-parallel", "later-result"])
async def test_host_results_sent_late_still_link(delay: str) -> None:
    """A call keeps waiting while the scaffold sends other results, or goes on, without its own."""
    task = ChatMessageUser(content="Read a.txt and b.txt.")
    reply = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(id="call_a", function="bash", arguments={"cmd": "cat a.txt"}),
            ToolCall(id="call_b", function="bash", arguments={"cmd": "cat b.txt"}),
        ],
    )
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], reply)
    [event_a] = _awaiting(scaffold.bridge, reply, index=0)
    [event_b] = _awaiting(scaffold.bridge, reply, index=1)

    if delay == "split-parallel":
        first = await scaffold.request([task, reply, _result("call_a", "A")])
        assert (event_a.message_id, event_b.message_id) == (first[2], None)
    else:
        await scaffold.request([task, reply, ChatMessageAssistant(content="Working.")])
        assert (event_a.message_id, event_b.message_id) == (None, None)
    ids = await scaffold.request(
        [task, reply, _result("call_a", "A"), _result("call_b", "B")]
    )

    assert (event_a.message_id, event_b.message_id) == (ids[2], ids[3])
    assert _waiting(scaffold.bridge) == 0


def test_host_results_waiting_are_capped() -> None:
    bridge = AgentBridge(AgentState(messages=[]))
    replies = [_call(f"call_{n}") for n in range(bridge_types._MAX_AWAITED_RESULTS + 1)]
    events = [_awaiting(bridge, reply)[0] for reply in replies]
    assert len(bridge._awaited_results) == bridge_types._MAX_AWAITED_RESULTS

    for reply in (replies[0], replies[-1]):
        assert reply.id is not None
        result = _result(reply.tool_calls[0].id if reply.tool_calls else "")
        bridge._link_result_messages([reply, result], {0: reply.id}, {1}, set(), {})

    assert events[0].message_id is None
    assert events[-1].message_id is not None


def test_host_reply_dropped_from_the_awaited_results_links_no_later_execution() -> None:
    """A call first executed after its reply was dropped from the awaited results stays unlinked.

    The bridge no longer holds evidence of the reply's earlier executions.
    """
    bridge = AgentBridge(AgentState(messages=[]))
    reply = ChatMessageAssistant(
        content="",
        tool_calls=[
            ToolCall(id="call_a", function="bash", arguments={"cmd": "ls"}),
            ToolCall(id="call_b", function="bash", arguments={"cmd": "pwd"}),
        ],
    )
    assert reply.id is not None
    _awaiting(bridge, reply, index=0)
    for n in range(bridge_types._MAX_AWAITED_RESULTS):
        _awaiting(bridge, _call(f"call_{n}"))
    assert reply.id not in bridge._awaited_results
    [event] = _awaiting(bridge, reply, index=1)

    result = _result("call_b")
    bridge._link_result_messages([reply, result], {0: reply.id}, {1}, set(), {})

    assert event.message_id is None


def _read(call_id: str, path: str) -> ToolCall:
    return ToolCall(id=call_id, function="read", arguments={"path": path})


def _link_copy(
    handed: list[ToolCall],
    results: list[tuple[int, str]],
    copy: list[ToolCall],
    answers: list[tuple[ToolCall, str]],
) -> list[str | None]:
    """Track executions of `handed` calls, place a copy with new `answers`; the events' message ids."""
    bridge = AgentBridge(AgentState(messages=[]))
    tracked = handed_calls(bridge, "reply", handed)
    events = []
    for position, result in results:
        call = handed[position]
        event = ToolEvent(
            id=call.id, function=call.function, arguments=call.arguments, result=result
        )
        bridge._await_result_message(tracked[position], event)
        events.append(event)
    tool_messages = [
        ChatMessageTool(
            id=f"result-{n}", content=content, tool_call_id=call.id, function="read"
        )
        for n, (call, content) in enumerate(answers)
    ]
    reply = ChatMessageAssistant(id="reply", content="", tool_calls=copy)
    bridge._link_result_messages(
        [reply, *tool_messages],
        {0: "reply"},
        set(range(1, len(tool_messages) + 1)),
        set(),
        {},
    )
    return [event.message_id for event in events]


def test_host_result_links_to_the_answer_whatever_its_content() -> None:
    """`message_id` names the answer to the call, not a message holding `result`."""
    handed = [_read("a", "a")]

    ids = _link_copy(handed, [(0, "A")], handed, [(handed[0], "edited")])

    assert ids == ["result-0"]


# validates as `internal` (pydantic's limit is ~255) but is too deep to serialize
_TOO_DEEP = base64.b64encode(("[" * 250 + "]" * 250).encode()).decode()

_LITERAL_MARKERS = {
    "unpadded": "The marker is <content-internal>example</content-internal>.",
    "not_utf8": "<content-internal>abcd</content-internal> is the marker",
    "not_json": "Wrap it as <content-internal>bm90IGpzb24=</content-internal>.",
    "unpaired": "Open with <content-internal> and close with </content-internal>.",
    # decodes, but the value can't be a content object's `internal`
    "too_deep": f"See <content-internal>{_TOO_DEEP}</content-internal>.",
    "think_too_deep": f'See <think internal="{_TOO_DEEP}">quoted</think> here.',
    "think_not_json": '<think internal="bm90IGpzb24=">quoted</think> is the marker',
}


async def _dialect_request(
    dialect: Dialect, bridge: AgentBridge, history: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Send `history` through the `dialect` handler; the reply's wire turns."""
    from inspect_ai.agent._bridge.anthropic_api import inspect_anthropic_api_request
    from inspect_ai.agent._bridge.completions import inspect_completions_api_request
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request
    from inspect_ai.agent._bridge.responses import inspect_responses_api_request
    from inspect_ai.agent._bridge.util import (
        default_code_execution_providers,
        internal_web_search_providers,
    )

    if dialect == "completions":
        completion = await inspect_completions_api_request(
            {"model": "scaffold", "messages": history}, None, bridge
        )
        return [completion.choices[0].message.model_dump(exclude_none=True)]
    elif dialect == "responses":
        response = await inspect_responses_api_request(
            {"model": "scaffold", "input": history},
            None,
            internal_web_search_providers(),
            default_code_execution_providers(),
            bridge,
        )
        return [item.model_dump(exclude_none=True) for item in response.output]
    elif dialect == "anthropic":
        message = await inspect_anthropic_api_request(
            {"model": "scaffold", "max_tokens": 32, "messages": history},
            None,
            internal_web_search_providers(),
            default_code_execution_providers(),
            bridge,
        )
        return [
            {
                "role": "assistant",
                "content": [b.model_dump(exclude_none=True) for b in message.content],
            }
        ]
    else:
        google = await inspect_google_api_request(
            {"model": "scaffold", "contents": history}, None, None, bridge
        )
        return [google["candidates"][0]["content"]]


def _wire_user(dialect: Dialect, text: str) -> dict[str, Any]:
    if dialect == "google":
        return {"role": "user", "parts": [{"text": text}]}
    return {"role": "user", "content": text}


def _wire_text(dialect: Dialect, turns: list[dict[str, Any]]) -> str:
    if dialect == "completions":
        return str(turns[0]["content"])
    elif dialect == "responses":
        return "".join(c["text"] for item in turns for c in item["content"])
    elif dialect == "anthropic":
        return "".join(block["text"] for block in turns[0]["content"])
    else:
        return "".join(part["text"] for part in turns[0]["parts"])


@pytest.mark.parametrize("literal", list(_LITERAL_MARKERS))
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_literal_internal_marker_is_text_in_every_dialect(
    dialect: Dialect, literal: str
) -> None:
    """Text quoting an internal-state marker is delivered and kept as written.

    Only a marker the bridge itself encoded is internal state; recognizing
    the reply when the scaffold sends it back must not reject or alter a reply
    or prompt that merely contains the marker (Google, which carries internal
    state natively, is the control).
    """
    text = _LITERAL_MARKERS[literal]
    usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    outputs = [
        ModelOutput.from_content("mockllm/model", text),
        ModelOutput.from_content("mockllm/model", "done"),
    ]
    for output in outputs:
        output.usage = usage
    bridge = AgentBridge(
        AgentState(messages=[ChatMessageUser(content="Quote the marker.")]),
        model_aliases={
            "scaffold": get_model(
                "mockllm/model", memoize=False, custom_outputs=outputs
            )
        },
    )

    # a final, single-turn answer
    history = [_wire_user(dialect, "Quote the marker.")]
    reply = await _dialect_request(dialect, bridge, history)
    assert _wire_text(dialect, reply) == text
    first = bridge.state.output.message
    assert first.text == text

    # the scaffold continues with the reply and another quoting prompt
    history = [*history, *reply, _wire_user(dialect, f"again: {text}")]
    assert _wire_text(dialect, await _dialect_request(dialect, bridge, history)) == (
        "done"
    )
    assert [(m.role, m.text) for m in bridge.state.messages] == [
        ("user", "Quote the marker."),
        ("assistant", text),
        ("user", f"again: {text}"),
        ("assistant", "done"),
    ]
    assert bridge.state.messages[1].id == first.id
