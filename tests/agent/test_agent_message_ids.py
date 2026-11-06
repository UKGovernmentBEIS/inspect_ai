"""Message ids stay the same through an agent run and the log.

A react agent, and a scaffold in each bridge dialect, run against mockllm: the
model calls a tool, the agent runs it, and the model answers twice. The ids in
the final messages, in each `ModelEvent`'s input and output, in each
`ToolEvent`, and in the log read back (`.eval` and `.json`) must agree.
"""

import copy
import gc
import json
import weakref
from pathlib import Path
from typing import Any, Callable, Literal, cast
from unittest.mock import patch

import pytest
from anthropic import AsyncAnthropic
from google import genai
from openai import AsyncOpenAI
from shortuuid import uuid
from test_helpers.checkpoint import RecordingCheckpointer
from test_helpers.message_ids import assert_message_ids, edited_id, tool_event_producers

from inspect_ai import Task, eval
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge, handoff, react
from inspect_ai.agent._bridge import types as bridge_types
from inspect_ai.agent._bridge.types import (
    AgentBridge,
    _arguments_digest,
    _handed_calls,
    _loose_message_key,
)
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
    GenerateInput,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._message_ids import (
    content_hash,
    edited_message,
    stable_message_ids,
)
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.solver import generate, user_message
from inspect_ai.tool import (
    Tool,
    ToolCall,
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
            assert reply.id == edited_id(event.output.message.id, reply)
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


class _TextConversation:
    """A text-only scaffold conversation in a bridge dialect, as wire turns."""

    def __init__(self, dialect: Dialect) -> None:
        self.dialect = dialect
        self.turns: list[list[dict[str, Any]]] = []

    def user_turn(self, text: str) -> list[dict[str, Any]]:
        if self.dialect == "google":
            return [{"role": "user", "parts": [{"text": text}]}]
        return [{"role": "user", "content": text}]

    def user(self, text: str) -> None:
        self.turns.append(self.user_turn(text))

    async def generate(self) -> None:
        wire = [item for turn in self.turns for item in turn]
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
                    model="inspect", max_tokens=32, messages=cast(Any, wire)
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
            ).aio.models.generate_content(model="inspect", contents=cast(Any, wire))
            assert google_response.candidates and google_response.candidates[0].content
            reply = [
                google_response.candidates[0].content.model_dump(
                    exclude_none=True, by_alias=True
                )
            ]
        self.turns.append(reply)


@pytest.mark.parametrize(
    "case", ["compacted", "full_history", "distinct_replies", "single_tail"]
)
@pytest.mark.parametrize("dialect", DIALECTS)
def test_compacted_identical_replies_keep_their_own_ids(
    dialect: Dialect, case: str, tmp_path: Path
) -> None:
    """Identical replies retained by compaction keep their own ids, in order.

    Two `OK` replies follow different user messages. Compaction replaces the
    prompt with a summary and keeps both exchanges (or only the latest reply,
    followed by a message equal to the earlier exchange's), and a further call
    makes the compacted thread the bridge's conversation.
    """

    @agent
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                conversation = _TextConversation(dialect)
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
                for text in (follow_up, "Thanks."):
                    conversation.user(text)
                    await conversation.generate()
                return bridge.state

        return execute

    replies = ["OK", "Fine" if case == "distinct_replies" else "OK", "Done", "Bye"]
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
    assert None not in reply_ids and len(set(reply_ids)) == 4
    retained = reply_ids[1:2] if case == "single_tail" else reply_ids[:2]
    assert [m.id for m in events[2].input if m.role == "assistant"] == retained
    assert [m.id for m in sample.messages if m.role == "assistant"] == [
        *retained,
        *reply_ids[2:],
    ]


def test_completions_non_primary_choice_keeps_generated_id(tmp_path: Path) -> None:
    """A scaffold can continue with an unchanged alternate choice."""

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
            ChatCompletionChoice(message=ChatMessageAssistant(content="choice-one")),
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
    assert second_event.input[1].id == first_event.output.choices[1].message.id


@pytest.mark.parametrize("dialect", DIALECTS)
async def test_recorded_side_reply_beats_loose_tracked_match(
    dialect: Dialect,
) -> None:
    """A recorded call ID keeps a side reply distinct from an equal main reply."""
    task = ChatMessageUser(content="Read a file.")
    a_id, b_id = {
        "completions": ("call_a", "call_b"),
        "responses": ("fc_a", "fc_b"),
        "anthropic": ("toolu_a", "toolu_b"),
        "google": ("call_bash_a", "call_bash_b"),
    }[dialect]
    main = _call(a_id)
    side = _call(b_id)
    bridge = AgentBridge(AgentState(messages=[task]))
    scaffold = _Scaffold(bridge)
    await scaffold.request([task], main)
    await scaffold.request([ChatMessageUser(content="Is ls safe?")], side)
    if dialect == "google":
        bridge._record_transported_reply(side, [side])
    [event] = _awaiting(bridge, side)
    result = _result(b_id)

    ids = await scaffold.request([task, side, result])

    assert ids[1] == side.id
    assert event.message_id == ids[2]


@pytest.mark.parametrize("second_edit", [False, True])
async def test_edited_parallel_reply_links_results_from_separate_requests(
    second_edit: bool,
) -> None:
    """An edited reply keeps its pending calls when a later result arrives."""
    task = ChatMessageUser(content="Read two files.")
    reply = ChatMessageAssistant(
        content="Reading both.",
        tool_calls=[
            ToolCall(id="a", function="bash", arguments={"cmd": "cat a"}),
            ToolCall(id="b", function="bash", arguments={"cmd": "cat b"}),
        ],
    )
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], reply)
    [first] = _awaiting(scaffold.bridge, reply, index=0)
    [second] = _awaiting(scaffold.bridge, reply, index=1)
    edited = reply.model_copy(update={"content": "Reading both. "})
    result_a = _result("a", "A")
    result_b = _result("b", "B")

    await scaffold.request(
        [task, edited, result_a], ChatMessageAssistant(content="wait")
    )
    assert first.message_id == scaffold.sent[2].id
    assert second.message_id is None

    later = (
        reply.model_copy(update={"content": "Reading both.  "})
        if second_edit
        else edited
    )
    await scaffold.request(
        [task, later, result_a, ChatMessageAssistant(content="wait"), result_b]
    )
    assert second.message_id == scaffold.sent[4].id


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


@pytest.mark.parametrize(
    "operation",
    ["content_hash", "edited_message", "arguments_digest", "loose_key", "stable_ids"],
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
    elif operation == "arguments_digest":
        assert _arguments_digest(call.arguments) == _arguments_digest(
            {"data": {"name": "value", 1: "one"}}
        )
    elif operation == "loose_key":
        assert _loose_message_key(reply, reply.text) == _loose_message_key(
            reply.model_copy(deep=True), reply.text
        )
    else:
        stable_message_ids()([reply])
        assert reply.id is not None


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


def _transported(reply: ChatMessageAssistant, call_id: str) -> ChatMessageAssistant:
    """`reply` as the Google dialect hands it to a scaffold: call ids re-derived."""
    assert reply.tool_calls
    [call] = reply.tool_calls
    return reply.model_copy(
        update={"tool_calls": [ToolCall(call_id, call.function, call.arguments)]}
    )


async def test_compaction_after_re_derived_ids_keeps_the_latest_replys_id() -> None:
    """A retained latest reply equal to an earlier one is the latest, once both came back transported."""
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
    await scaffold.request([task, first_back, _result("call_bash_1", "OLD")], second)
    bridge._record_transported_reply(second, [second_back])
    [event] = _awaiting(bridge, second)
    summary = ChatMessageUser(content="Summary: listed the files once.")

    ids = await scaffold.request([summary, second_back, _result("call_bash_1", "NEW")])

    assert second.id is not None
    assert ids[1] == edited_id(second.id, scaffold.sent[1])
    assert event.message_id == ids[2]


@pytest.mark.parametrize(
    "field", ["metadata", "model", "source", "text_form", "reasoning_signature"]
)
async def test_non_content_fields_do_not_override_aligned_reply(field: str) -> None:
    """A side reply's serialized form cannot take an aligned main reply's ID."""
    task = ChatMessageUser(content="Keep the main reply.")
    if field == "metadata":
        main = ChatMessageAssistant(content="same", metadata={"origin": "main"})
        returned = main.model_copy(update={"metadata": None})
    elif field == "model":
        main = ChatMessageAssistant(content="same", model="main/model")
        returned = main.model_copy(update={"model": None})
    elif field == "source":
        main = ChatMessageAssistant(content="same", source="generate")
        returned = main.model_copy(update={"source": None})
    elif field == "text_form":
        main = ChatMessageAssistant(content=[ContentText(text="same")])
        returned = main.model_copy(update={"content": "same"})
    else:
        main = ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="opaque", redacted=True, signature="main")
            ]
        )
        returned = main.model_copy(
            update={"content": [ContentReasoning(reasoning="opaque", redacted=True)]}
        )
    side = returned.model_copy(deep=True)
    side.id = uuid()
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    await scaffold.request([task], main)
    await scaffold.request([ChatMessageUser(content="Side question")], side)
    assert main.id is not None and side.id is not None and main.id != side.id

    ids = await scaffold.request([task, returned])

    assert ids[1] == main.id


@pytest.mark.parametrize("regenerated", [False, True])
async def test_fresh_compacted_result_is_not_an_edit_of_earlier_answer(
    regenerated: bool,
) -> None:
    """A later equal call receives its own result ID after compaction."""
    task = ChatMessageUser(content="List the files twice.")
    first_id, second_id, returned_id = (
        ("toolu_1", "toolu_2", "call_bash_1")
        if regenerated
        else ("reused", "reused", "reused")
    )
    first, second = _call(first_id), _call(second_id)
    first_back = _transported(first, returned_id) if regenerated else first
    second_back = _transported(second, returned_id) if regenerated else second
    bridge = AgentBridge(AgentState(messages=[task]))
    scaffold = _Scaffold(bridge)
    await scaffold.request([task], first)
    if regenerated:
        bridge._record_transported_reply(first, [first_back])
    [first_event] = _awaiting(bridge, first)
    first_ids = await scaffold.request(
        [task, first_back, _result(returned_id, "OLD")], second
    )
    assert first_event.message_id == first_ids[2]
    if regenerated:
        bridge._record_transported_reply(second, [second_back])
    [second_event] = _awaiting(bridge, second)
    summary = ChatMessageUser(content="Summary: listed once.")

    ids = await scaffold.request([summary, second_back, _result(returned_id, "NEW")])

    assert ids[2] != first_ids[2]
    assert second_event.message_id == ids[2]


@pytest.mark.parametrize("copied", [False, True])
@pytest.mark.parametrize("regenerated", [False, True])
async def test_equal_compacted_result_is_fresh_unless_copied(
    regenerated: bool, copied: bool
) -> None:
    """A later call's equal answer gets its own ID; a copy of the earlier answer keeps its ID."""
    task = ChatMessageUser(content="Read the file twice.")
    first_id, second_id, returned_id = (
        ("toolu_1", "toolu_2", "call_bash_1")
        if regenerated
        else ("reused", "reused", "reused")
    )
    first, second = _call(first_id), _call(second_id)
    first_back = _transported(first, returned_id) if regenerated else first
    second_back = _transported(second, returned_id) if regenerated else second
    bridge = AgentBridge(AgentState(messages=[task]))
    scaffold = _Scaffold(bridge)
    await scaffold.request([task], first)
    if regenerated:
        bridge._record_transported_reply(first, [first_back])
    [first_event] = _awaiting(bridge, first, result="contents")
    first_ids = await scaffold.request(
        [task, first_back, _result(returned_id, "contents")], second
    )
    assert first_event.message_id == first_ids[2]
    if regenerated:
        bridge._record_transported_reply(second, [second_back])
    [second_event] = _awaiting(
        bridge, second, result="changed" if copied else "contents"
    )
    summary = ChatMessageUser(content="Summary: read once.")

    ids = await scaffold.request(
        [summary, second_back, _result(returned_id, "contents")]
    )

    assert first_event.message_id == first_ids[2]
    if copied:
        assert ids[2] == first_ids[2]
        assert second_event.message_id is None
    else:
        assert ids[2] != first_ids[2]
        assert second_event.message_id == ids[2]


@pytest.mark.parametrize("regenerated", [False, True])
async def test_edited_reply_gets_fresh_result_after_compaction(
    regenerated: bool,
) -> None:
    """An edited pending reply still owns a fresh result with a repeated call ID."""
    task = ChatMessageUser(content="List twice.")
    first_id, second_id, returned_id = (
        ("toolu_1", "toolu_2", "call_bash_1")
        if regenerated
        else ("reused", "reused", "reused")
    )
    first, second = _call(first_id), _call(second_id)
    first_back = _transported(first, returned_id) if regenerated else first
    second_back = _transported(second, returned_id) if regenerated else second
    bridge = AgentBridge(AgentState(messages=[task]))
    scaffold = _Scaffold(bridge)
    await scaffold.request([task], first)
    if regenerated:
        bridge._record_transported_reply(first, [first_back])
    [first_event] = _awaiting(bridge, first)
    old = _result(returned_id, "OLD")
    first_ids = await scaffold.request([task, first_back, old], second)
    assert first_event.message_id == first_ids[2]
    if regenerated:
        bridge._record_transported_reply(second, [second_back])
    [second_event] = _awaiting(bridge, second)
    edited = second_back.model_copy(update={"content": " "})
    observed = await scaffold.request([task, first_back, old, edited])
    assert observed[3] == edited_id(second.id, scaffold.sent[3])

    ids = await scaffold.request(
        [
            ChatMessageUser(content="Summary: listed once."),
            edited,
            ChatMessageAssistant(content="Working."),
            _result(returned_id, "NEW"),
        ]
    )

    assert ids[3] != first_ids[2]
    assert second_event.message_id == ids[3]
    assert ids[3] not in bridge._result_edit_parent


async def _google_compacting() -> None:
    """Two equal calls, then compaction keeping the second call with a new result."""
    from google.genai import types

    client = genai.Client(api_key="inspect")
    config = types.GenerateContentConfig(
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
    )
    contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": PROMPT}]}]
    for result in ("OLD", "NEW"):
        response = await client.aio.models.generate_content(
            model="inspect", contents=contents, config=config
        )
        assert response.candidates and response.candidates[0].content
        reply = response.candidates[0].content.model_dump(
            exclude_none=True, by_alias=True
        )
        answer = {
            "role": "user",
            "parts": [
                {"functionResponse": {"name": "echo", "response": {"output": result}}}
            ],
        }
        contents += [reply, answer]
    summary = {"role": "user", "parts": [{"text": "Summary: echoed once."}]}
    await client.aio.models.generate_content(
        model="inspect", contents=[summary, *contents[-2:]], config=config
    )


def test_google_compaction_keeps_the_latest_replys_id(tmp_path: Path) -> None:
    @agent
    def compacting() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state) as bridge:
                await _google_compacting()
                return bridge.state

        return execute

    log = eval(
        Task(dataset=[Sample(input=PROMPT)], solver=compacting()),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                *[
                    ModelOutput.for_tool_call("mockllm/model", "echo", {"text": "hi"})
                    for _ in range(2)
                ],
                ModelOutput.from_content("mockllm/model", "Done."),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]

    assert log.status == "success", log.error
    assert log.samples
    first, second, compacted = [
        e for e in log.samples[0].events if isinstance(e, ModelEvent)
    ]
    retained = compacted.input[1]
    assert second.output.message.id not in (None, first.output.message.id)
    assert retained.id == edited_id(second.output.message.id, retained)


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
        assert edited[i] == edited_id(ids[i], sent[i]) != ids[i]
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


async def test_scaffold_edit_of_a_reasoning_summary_gets_a_new_id() -> None:
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

    assert ids[1] == edited_message(reply, content=content).id != reply.id


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
            _handed_calls(reply.id, reply.tool_calls)[index], event
        )
    return events


def _waiting(bridge: AgentBridge) -> int:
    return sum(
        not entry.settled
        for calls in bridge._awaited_results.values()
        for entry in calls.values()
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


async def test_host_results_pair_by_call_id_when_the_scaffold_reorders_calls() -> None:
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

    assert (event_a.message_id, event_b.message_id) == (ids[3], ids[2])


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
        result = _result(reply.tool_calls[0].id if reply.tool_calls else "")
        bridge._link_result_messages([reply, result], [reply.id, None])

    assert events[0].message_id is None
    assert events[-1].message_id is not None


def test_tracked_host_calls_keep_no_unexecuted_calls() -> None:
    """A tracked call keeps nothing of the other calls in its reply."""
    bridge = AgentBridge(AgentState(messages=[]))
    calls = [
        ToolCall(id=f"call_{n}", function="bash", arguments={"cmd": "ls"})
        for n in range(5000)
    ]
    unexecuted = weakref.ref(calls[-1])
    event = ToolEvent(id="call_0", function="bash", arguments={"cmd": "ls"})
    bridge._await_result_message(_handed_calls("reply", calls)[0], event)

    del calls
    gc.collect()

    assert unexecuted() is None


async def test_answer_records_are_bounded() -> None:
    """A long run of host calls under compaction keeps a bounded number of answer records and no calls."""
    task = ChatMessageUser(content="Start")
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    window: list[ChatMessage] = [task]
    sent_calls: list[weakref.ref[ToolCall]] = []
    events: list[ToolEvent] = []
    calls = 3000
    for n in range(calls):
        call = ToolCall(
            id=f"call_{n}",
            function="read",
            arguments={"path": f"{n}", "data": "x" * 10_000},
        )
        reply = ChatMessageAssistant(content=f"Reading {n}", tool_calls=[call])
        await scaffold.request(window, reply)
        events += _awaiting(scaffold.bridge, reply, result="contents")
        copy = reply.model_copy(deep=True)
        assert copy.tool_calls
        sent_calls.append(weakref.ref(copy.tool_calls[0]))
        window = [
            ChatMessageUser(content=f"Summary {n}"),
            copy,
            _result(call.id, "contents"),
        ]
        del call, reply, copy
    ids = await scaffold.request(window)

    bridge = scaffold.bridge
    assert all(event.message_id is not None for event in events)
    assert events[-1].message_id == ids[2]
    records = sum(
        len(answers.message_ids) + len(answers.occurrences)
        for answers in bridge._reply_answers.values()
    )
    assert records == bridge._answer_records <= bridge_types._MAX_ANSWER_RECORDS
    assert len(bridge._answers) < calls
    del window, scaffold.sent
    gc.collect()
    assert sum(ref() is not None for ref in sent_calls) == 0


@pytest.mark.parametrize("dropped", [False, True])
async def test_equal_host_result_after_its_earlier_answer_record_is_dropped(
    dropped: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later host call's result equal to an earlier answer is fresh while the earlier answer's record is kept; once dropped it is taken for the earlier answer and links nothing.

    The earlier reply is no longer tracked for its result in either case.
    """
    monkeypatch.setattr(bridge_types, "_MAX_AWAITED_RESULTS", 1)
    if dropped:
        monkeypatch.setattr(bridge_types, "_MAX_ANSWER_RECORDS", 8)
    task = ChatMessageUser(content="Start")
    scaffold = _Scaffold(AgentBridge(AgentState(messages=[task])))
    first = _call("call_1")
    await scaffold.request([task], first)
    [first_event] = _awaiting(scaffold.bridge, first, result="A")
    window: list[ChatMessage] = [task, first, _result("call_1", "A")]
    earlier = ""
    for n in range(3):
        side = _call(f"side_{n}")
        ids = await scaffold.request(window, side)
        earlier = earlier or ids[2]
        window = [
            ChatMessageUser(content=f"Summary {n}"),
            side,
            _result(f"side_{n}", f"{n}"),
        ]
    assert first_event.message_id == earlier
    # the provider reuses the call id
    later = _call("call_1").model_copy(update={"content": "Again."})
    await scaffold.request(window, later)
    [later_event] = _awaiting(scaffold.bridge, later, result="A")

    window = [ChatMessageUser(content="Summary"), later, _result("call_1", "A")]
    ids = await scaffold.request(window)
    next_ids = await scaffold.request([*window, ChatMessageUser(content="Thanks.")])

    assert next_ids[2] == ids[2]
    if dropped:
        assert (ids[2], later_event.message_id) == (earlier, None)
    else:
        assert ids[2] != earlier
        assert later_event.message_id == ids[2]


@pytest.mark.parametrize("regenerated", [False, True])
async def test_copied_answer_stays_unlinked_when_its_record_is_dropped_in_the_same_request(
    regenerated: bool,
) -> None:
    """A later call's copy of an earlier answer isn't linked when a later result in the request drops the earlier answer's record."""
    first_id, second_id, returned_id = (
        ("toolu_1", "toolu_2", "call_read_1")
        if regenerated
        else ("reuse", "reuse", "reuse")
    )
    first = ChatMessageAssistant(content="Reading.", tool_calls=[_read(first_id, "a")])
    second = ChatMessageAssistant(content="Again.", tool_calls=[_read(second_id, "a")])
    first_back = _transported(first, returned_id) if regenerated else first
    second_back = _transported(second, returned_id) if regenerated else second
    task = ChatMessageUser(content="Start")
    bridge = AgentBridge(AgentState(messages=[task]))
    scaffold = _Scaffold(bridge)
    await scaffold.request([task], first)
    if regenerated:
        bridge._record_transported_reply(first, [first_back])
    _awaiting(bridge, first, result="A")
    window: list[ChatMessage] = [task, first_back, _result(returned_id, "A")]
    earlier = (await scaffold.request(window))[2]
    records = bridge._answer_records
    for n in range(bridge_types._MAX_ANSWER_RECORDS // records - 1):
        filler = ChatMessageAssistant(content="", tool_calls=[_read(f"f{n}", f"{n}")])
        await scaffold.request(window, filler)
        _awaiting(bridge, filler, result=f"{n}")
        window = [
            ChatMessageUser(content=f"Summary {n}"),
            filler,
            _result(f"f{n}", f"{n}"),
        ]
        await scaffold.request(window)
    assert bridge._answer_records == bridge_types._MAX_ANSWER_RECORDS
    assert earlier in bridge._answers and first.id not in bridge._awaited_results
    await scaffold.request(window, second)
    if regenerated:
        bridge._record_transported_reply(second, [second_back])
    [second_event] = _awaiting(bridge, second, result="B")
    last = ChatMessageAssistant(content="", tool_calls=[_read("last", "last")])
    summary = ChatMessageUser(content="New summary")
    window = [summary, second_back, _result(returned_id, "A")]
    await scaffold.request(window, last)
    [last_event] = _awaiting(bridge, last, result="C")

    window = [*window, last, _result("last", "C")]
    ids = await scaffold.request(window)
    next_ids = await scaffold.request([*window, ChatMessageUser(content="Thanks.")])

    assert earlier not in bridge._answers
    assert bridge._answer_records <= bridge_types._MAX_ANSWER_RECORDS
    assert ids[2] == earlier
    assert second_event.message_id is None
    assert last_event.message_id == ids[4]
    assert next_ids[:5] == ids


def _read(call_id: str, path: str) -> ToolCall:
    return ToolCall(id=call_id, function="read", arguments={"path": path})


def _link_copy(
    handed: list[ToolCall],
    results: list[tuple[int, str]],
    copy: list[ToolCall],
    answers: list[tuple[ToolCall, str]],
) -> list[str | None]:
    """Track executions of `handed` calls, send a copy with `answers`; the events' message ids."""
    bridge = AgentBridge(AgentState(messages=[]))
    tracked = _handed_calls("reply", handed)
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
        [reply, *tool_messages], ["reply", *([None] * len(tool_messages))]
    )
    return [event.message_id for event in events]


def test_host_result_is_not_claimed_through_another_handed_calls_id() -> None:
    """A copy keeping an unexecuted call's id, with the executed call's arguments, isn't the executed call."""
    handed = [_read("a", "a"), _read("b", "b")]
    rewritten = _read("b", "a")

    ids = _link_copy(handed, [(0, "A")], [rewritten], [(rewritten, "B")])

    assert ids == [None]


def test_identical_re_derived_calls_stay_unlinked_beside_a_distinct_one() -> None:
    handed = [_read("a", "a"), _read("b", "a"), _read("c", "c")]
    copy = [_read("x", "a"), _read("y", "a"), _read("z", "c")]

    ids = _link_copy(
        handed,
        [(0, "A"), (1, "A"), (2, "C")],
        copy,
        [(copy[0], "A"), (copy[1], "A"), (copy[2], "C")],
    )

    assert ids == [None, None, "result-2"]


@pytest.mark.parametrize(
    "calls", [bridge_types._MAX_HANDED_IDS, bridge_types._MAX_HANDED_IDS + 1]
)
def test_re_derived_ids_match_only_while_handed_ids_are_kept(calls: int) -> None:
    """Beyond `_MAX_HANDED_IDS` calls a reply keeps no handed ids, so a re-derived id can't match."""
    handed = [_read(f"call_{n}", str(n)) for n in range(calls)]
    copy = [_read("re-derived", "0")]

    ids = _link_copy(handed, [(0, "0")], copy, [(copy[0], "0")])

    assert ids == (["result-0"] if calls <= bridge_types._MAX_HANDED_IDS else [None])


@pytest.mark.parametrize(
    "calls", [bridge_types._MAX_HANDED_IDS, bridge_types._MAX_HANDED_IDS + 1]
)
@pytest.mark.parametrize("current_id", ["current", "call_5"])
def test_host_result_is_not_claimed_through_an_unkept_handed_id(
    calls: int, current_id: str
) -> None:
    """A copy carrying an unexecuted call's id from a tracked reply that kept no handed ids isn't the current call.

    With a distinct current id the copy matches by function and arguments; with
    the same id it matches by id.
    """
    bridge = AgentBridge(AgentState(messages=[]))
    earlier = [_read(f"call_{n}", str(n)) for n in range(calls)]
    current = _read(current_id, "5")
    events = []
    for reply_id, reply in (("earlier-reply", earlier), ("current-reply", [current])):
        event = ToolEvent(id=reply[0].id, function="read", arguments=reply[0].arguments)
        bridge._await_result_message(_handed_calls(reply_id, reply)[0], event)
        events.append(event)
    copy = earlier[5]
    answer = ChatMessageTool(
        id="earlier-answer", content="5", tool_call_id=copy.id, function="read"
    )
    bridge._link_result_messages(
        [
            ChatMessageAssistant(id="current-reply", content="", tool_calls=[copy]),
            answer,
        ],
        ["current-reply", None],
    )
    assert [event.message_id for event in events] == [None, None]

    answer_0 = ChatMessageTool(
        id="answer-0", content="0", tool_call_id="call_0", function="read"
    )
    bridge._link_result_messages(
        [
            ChatMessageAssistant(id="earlier-reply", content="", tool_calls=earlier),
            answer_0,
        ],
        ["earlier-reply", None],
    )
    assert events[0].message_id == "answer-0"


def test_host_results_under_an_id_handed_to_two_calls_stay_unlinked() -> None:
    """A kept id handed to two calls is ambiguous, even when the arguments pick one."""
    handed = [_read("same", "a"), _read("same", "b")]

    ids = _link_copy(handed, [(0, "A"), (1, "B")], [handed[0]], [(handed[0], "B")])

    assert ids == [None, None]


def test_host_result_links_to_the_answer_whatever_its_content() -> None:
    """`message_id` names the answer to the call, not a message holding `result`."""
    handed = [_read("a", "a")]

    ids = _link_copy(handed, [(0, "A")], handed, [(handed[0], "edited")])

    assert ids == ["result-0"]


def test_host_result_is_not_claimed_through_an_earlier_replys_id() -> None:
    """A copy carrying an earlier reply's call and answer isn't the current call."""
    bridge = AgentBridge(AgentState(messages=[]))
    earlier, current = _read("earlier", "a"), _read("current", "a")
    events = []
    for reply_id, call in (("earlier-reply", earlier), ("current-reply", current)):
        event = ToolEvent(id=call.id, function="read", arguments=call.arguments)
        bridge._await_result_message(_handed_calls(reply_id, [call])[0], event)
        events.append(event)
    answer = ChatMessageTool(
        id="earlier-answer", content="A", tool_call_id="earlier", function="read"
    )
    bridge._link_result_messages(
        [
            ChatMessageAssistant(id="current-reply", content="", tool_calls=[earlier]),
            answer,
        ],
        ["current-reply", None],
    )

    assert [event.message_id for event in events] == [None, None]


@pytest.mark.parametrize("reused", [True, False])
def test_kept_id_reused_across_tracked_replies_stays_unlinked(reused: bool) -> None:
    """An id two tracked replies handed can't tell their answers apart; an id handed once links."""
    bridge = AgentBridge(AgentState(messages=[]))
    first = _read("reused", "a")
    second = _read("reused" if reused else "second", "a")
    events = []
    for reply_id, call, result in (("first", first, "OLD"), ("second", second, "NEW")):
        event = ToolEvent(
            id=call.id, function="read", arguments=call.arguments, result=result
        )
        bridge._await_result_message(_handed_calls(reply_id, [call])[0], event)
        events.append(event)
    answer = ChatMessageTool(
        id="answer", content="OLD", tool_call_id=second.id, function="read"
    )
    bridge._link_result_messages(
        [ChatMessageAssistant(id="second", content="", tool_calls=[second]), answer],
        ["second", None],
    )

    assert [event.message_id for event in events] == (
        [None, None] if reused else [None, "answer"]
    )


@pytest.mark.parametrize("copied", [False, True])
def test_kept_id_reused_after_the_earlier_call_linked(copied: bool) -> None:
    """A reused id links to a new answer once the earlier call is linked, never to the earlier answer."""
    bridge = AgentBridge(AgentState(messages=[]))
    call = _read("reused", "a")
    first = ToolEvent(id="reused", function="read", arguments=call.arguments)
    bridge._await_result_message(_handed_calls("first", [call])[0], first)
    old = ChatMessageTool(
        id="old", content="OLD", tool_call_id="reused", function="read"
    )
    first_reply = ChatMessageAssistant(id="first", content="", tool_calls=[call])
    bridge._link_result_messages([first_reply, old], ["first", None])

    second = ToolEvent(id="reused", function="read", arguments=call.arguments)
    bridge._await_result_message(_handed_calls("second", [call])[0], second)
    new = (
        old
        if copied
        else ChatMessageTool(
            id="new", content="NEW", tool_call_id="reused", function="read"
        )
    )
    second_reply = ChatMessageAssistant(id="second", content="", tool_calls=[call])
    bridge._link_result_messages(
        [first_reply, old, second_reply, new], ["first", None, "second", None]
    )

    assert (first.message_id, second.message_id) == (
        ("old", None) if copied else ("old", "new")
    )


@pytest.mark.parametrize("copied", [True, False])
def test_answer_linked_through_a_re_derived_id_is_not_claimed_again(
    copied: bool,
) -> None:
    """An answer linked to an earlier call isn't taken for a later call's, whatever id carried it."""
    bridge = AgentBridge(AgentState(messages=[]))
    first_call, second_call = _read("handed-1", "a"), _read("handed-2", "a")
    # Google re-derives both calls' ids as the same one
    back = _read("re-derived", "a")
    first = ToolEvent(id="handed-1", function="read", arguments=back.arguments)
    bridge._await_result_message(_handed_calls("first", [first_call])[0], first)
    old = ChatMessageTool(
        id="old", content="OLD", tool_call_id="re-derived", function="read"
    )
    first_reply = ChatMessageAssistant(id="first", content="", tool_calls=[back])
    bridge._link_result_messages([first_reply, old], ["first", None])

    second = ToolEvent(id="handed-2", function="read", arguments=back.arguments)
    bridge._await_result_message(_handed_calls("second", [second_call])[0], second)
    answer = (
        old
        if copied
        else ChatMessageTool(
            id="new", content="NEW", tool_call_id="re-derived", function="read"
        )
    )
    second_reply = ChatMessageAssistant(id="second", content="", tool_calls=[back])
    bridge._link_result_messages([second_reply, answer], ["second", None])

    assert (first.message_id, second.message_id) == (
        ("old", None) if copied else ("old", "new")
    )


@pytest.mark.parametrize("regenerated", [False, True])
def test_edited_earlier_answer_is_not_claimed_by_reused_call_id(
    regenerated: bool,
) -> None:
    """An edited copy of a linked result still belongs to the earlier call."""
    bridge = AgentBridge(AgentState(messages=[]))
    first_id, second_id, returned_id = (
        ("handed-1", "handed-2", "re-derived")
        if regenerated
        else ("reused", "reused", "reused")
    )
    first_call, second_call = _read(first_id, "a"), _read(second_id, "a")
    returned = _read(returned_id, "a")
    first = ToolEvent(id=first_id, function="read", arguments=first_call.arguments)
    bridge._await_result_message(_handed_calls("first", [first_call])[0], first)
    old = ChatMessageTool(
        id="old", content="OLD", tool_call_id=returned_id, function="read"
    )
    bridge._link_result_messages(
        [ChatMessageAssistant(id="first", content="", tool_calls=[returned]), old],
        ["first", None],
    )
    assert first.message_id == "old"

    second = ToolEvent(id=second_id, function="read", arguments=second_call.arguments)
    bridge._await_result_message(_handed_calls("second", [second_call])[0], second)
    bridge._content_by_id["old"] = content_hash(old)
    edited = old.model_copy(update={"content": "OLD "})
    edited.id = bridge._version_id("old", edited)
    bridge._link_result_messages(
        [ChatMessageAssistant(id="second", content="", tool_calls=[returned]), edited],
        ["second", "old"],
    )

    assert edited.id != "old"
    assert second.message_id is None
