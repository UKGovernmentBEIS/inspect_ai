"""`ModelEvent` records its input and output as they were when the model was called."""

import json
import math
import threading
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

import numpy as np
import pytest
from pydantic import BaseModel, PrivateAttr
from tenacity import wait_none

from inspect_ai import Task, eval
from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.registry import _registry
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.hooks import BeforeModelGenerate, Hooks, hooks
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
    ModelUsage,
    get_model,
)
from inspect_ai.model._chat_message import logged_json
from inspect_ai.model._model import (
    _rebuilt_message_key,
    _snapshot_messages,
    init_sample_rebuilt_message_ids,
    use_model_event_sink,
)
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import (
    Tool,
    ToolCall,
    ToolCallError,
    ToolChoice,
    ToolInfo,
    tool,
    tool_with,
)


def _conversation() -> list[ChatMessage]:
    return [
        ChatMessageUser(content="What is in the file?"),
        ChatMessageAssistant(
            content="",
            tool_calls=[ToolCall(id="c1", function="read", arguments={"path": "f"})],
        ),
        ChatMessageTool(
            content="original",
            tool_call_id="c1",
            function="read",
            metadata={"notes": ["kept"]},
            error=ToolCallError(type="unknown", message="original error"),
        ),
    ]


def _rewrite_tool_result(message: ChatMessage) -> None:
    assert isinstance(message, ChatMessageTool)
    message.content = "rewritten"
    assert message.metadata is not None
    message.metadata["notes"].append("added")
    message.error = None


def _assert_original(message: ChatMessage) -> None:
    assert isinstance(message, ChatMessageTool)
    assert message.content == "original"
    assert message.metadata == {"notes": ["kept"]}
    assert message.error == ToolCallError(type="unknown", message="original error")


def _model_events() -> list[ModelEvent]:
    return [e for e in transcript().events if isinstance(e, ModelEvent)]


async def test_model_event_input_unchanged_by_later_edits() -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    messages = _conversation()

    await model.generate(messages)
    _rewrite_tool_result(messages[2])
    await model.generate(messages)

    first, second = _model_events()
    _assert_original(first.input[2])
    assert second.input[2].content == "rewritten"

    # unchanged messages share one copy across events, so the log's message
    # pool still dedups them by identity
    assert first.input[0] is second.input[0]
    assert first.input[1] is second.input[1]
    assert first.input[0] is not messages[0]


class _Sink:
    def __init__(self) -> None:
        self.events: list[ModelEvent] = []

    def on_pending(self, event: ModelEvent) -> None:
        self.events.append(event)

    def on_complete(self, event: ModelEvent) -> None:
        pass


async def test_model_event_input_snapshot_with_event_sink() -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    messages = _conversation()
    sink = _Sink()

    with use_model_event_sink(sink):
        await model.generate(messages)
    _rewrite_tool_result(messages[2])

    assert len(sink.events) == 1
    _assert_original(sink.events[0].input[2])
    assert _model_events() == []


@pytest.mark.parametrize("with_sink", [False, True])
async def test_model_event_output_unchanged_by_later_edits(with_sink: bool) -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    messages: list[ChatMessage] = [ChatMessageUser(content="hi")]
    sink = _Sink()

    with use_model_event_sink(sink if with_sink else None):
        output = await model.generate(messages)
        messages.extend([output.message, ChatMessageUser(content="go on")])
        await model.generate(messages)
    original = output.message.text
    output.message.content = "edited"
    output.message.metadata = {"edited": True}

    first, second = sink.events if with_sink else _model_events()
    assert first.output.message.text == original
    assert first.output.message.metadata is None
    # the next input reuses the output's copy
    assert second.input[1] is first.output.message


async def test_model_event_output_snapshot_on_cache_hit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    messages: list[ChatMessage] = [ChatMessageUser(content="hi")]

    await model.generate(messages, cache=True)
    output = await model.generate(messages, cache=True)
    original = output.message.text
    output.message.content = "edited"

    events = _model_events()
    assert [event.cache for event in events] == ["write", "read"]
    assert events[1].output.message.text == original


@pytest.mark.parametrize(
    "before,after", [(0.0, -0.0), ({"x": 1, "y": 2}, {"y": 2, "x": 1})]
)
async def test_model_event_input_keeps_equal_but_distinct_edits(
    before: Any, after: Any
) -> None:
    # == treats these as equal, but they serialize (and are sent) differently
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    messages = _conversation()
    assistant = messages[1]
    assert isinstance(assistant, ChatMessageAssistant) and assistant.tool_calls
    assistant.tool_calls[0].arguments["value"] = before

    await model.generate(messages)
    assistant.tool_calls[0].arguments["value"] = after
    await model.generate(messages)

    logged = []
    for event in _model_events():
        message = event.input[1]
        assert isinstance(message, ChatMessageAssistant) and message.tool_calls
        logged.append(json.dumps(message.tool_calls[0].arguments["value"]))
    assert logged == [json.dumps(before), json.dumps(after)]


async def test_model_event_input_reuses_id_less_snapshots() -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    user = ChatMessageUser.model_validate(
        {"role": "user", "content": "hi"}, context=get_deserializing_context()
    )
    assert user.id is None
    messages: list[ChatMessage] = [user]

    await model.generate(messages)
    await model.generate(messages)
    user.content = "edited"
    await model.generate(messages)

    first, second, third = _model_events()
    assert first.input[0] is second.input[0]
    assert second.input[0].content == "hi"
    assert third.input[0].content == "edited"


@pytest.mark.parametrize(
    "replacement,reused", [(float("nan"), True), (None, False), (math.inf, False)]
)
async def test_model_event_input_compares_nan_as_logged(
    replacement: float | None, reused: bool
) -> None:
    # logs write every NaN the same way but keep NaN, Infinity and null apart
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    nan = float("nan")
    assistant = ChatMessageAssistant(
        content="",
        tool_calls=[ToolCall(id="c1", function="f", arguments={"x": nan})],
    )
    messages: list[ChatMessage] = [assistant]

    await model.generate(messages)
    assert assistant.tool_calls
    assistant.tool_calls[0].arguments["x"] = replacement
    assert assistant.tool_calls[0].arguments["x"] is not nan
    await model.generate(messages)

    first, second = _model_events()
    assert (first.input[0] is second.input[0]) is reused
    for event, expected in ((first, nan), (second, replacement)):
        logged = event.input[0]
        assert isinstance(logged, ChatMessageAssistant) and logged.tool_calls
        assert json.dumps(logged.tool_calls[0].arguments["x"]) == json.dumps(expected)


async def test_model_event_input_logs_unserializable_message_live() -> None:
    # numpy arrays don't serialize, so the event holds the live message
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    message = ChatMessageUser(content="hi", metadata={"values": np.array([1, 2])})

    await model.generate([message])

    [event] = _model_events()
    assert event.input[0] is message


class _Locked(BaseModel):
    step: int = 1
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)


async def test_model_event_logs_uncopyable_messages_live() -> None:
    # serializes, but its lock can't be deep copied: generate succeeds and
    # the event holds the live input and output messages
    output = ModelOutput.from_content("mockllm/model", "done")
    output.message.metadata = {"state": _Locked()}
    usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    output.usage = usage
    init_transcript(Transcript())
    model = get_model("mockllm/model", custom_outputs=[output])
    message = ChatMessageUser(content="hi", metadata={"state": _Locked()})
    assert logged_json(message) is not None
    with pytest.raises(TypeError):
        deepcopy(message)

    result = await model.generate([message])

    [event] = _model_events()
    assert event.pending is None and event.error is None
    assert event.input[0] is message
    assert event.output.message is result.message
    assert event.output.usage == usage


@dataclass(slots=True)
class _SlottedState:
    step: int


def test_model_event_input_snapshots_object_tool_arguments() -> None:
    # called directly: generate() itself fails here, since providers (and
    # mockllm's token count) JSON-encode the arguments
    state = _SlottedState(step=1)
    message = ChatMessageAssistant(
        content="",
        tool_calls=[ToolCall(id="c1", function="f", arguments={"state": state})],
    )

    [first] = _snapshot_messages([message])
    [second] = _snapshot_messages([message])
    state.step = 2
    [third] = _snapshot_messages([message])

    assert first is second
    steps = []
    for logged in (first, third):
        assert isinstance(logged, ChatMessageAssistant) and logged.tool_calls
        steps.append(logged.tool_calls[0].arguments["state"].step)
    assert steps == [1, 2]


async def test_model_event_input_reuses_deeply_nested_metadata() -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")
    nested: dict[str, Any] = {}
    inner = nested
    for _ in range(250):
        inner["k"] = {}
        inner = inner["k"]
    message = ChatMessageUser(content="hi", metadata={"nested": nested})

    await model.generate([message])
    await model.generate([message])

    first, second = _model_events()
    assert first.input[0] is second.input[0]


_PNG = "data:image/png;base64,iVBORw0KGgo="


@tool
def step() -> Tool:
    async def execute(n: int) -> str:
        """Run a step.

        Args:
          n: Step number.
        """
        return f"output {n}"

    return execute


def _step_call(n: int) -> list[ChatMessage]:
    return [
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning=f"thinking {n}"),
                ContentText(text=f"step {n}"),
            ],
            tool_calls=[ToolCall(id=f"c{n}", function="step", arguments={"n": n})],
        ),
        ChatMessageTool(
            content=[ContentText(text=f"output {n}"), ContentImage(image=_PNG)],
            tool_call_id=f"c{n}",
            function="step",
        ),
    ]


def _truncate_older(
    index: int, total: int, content: str | list[Content], hints: Any
) -> str | list[Content]:
    return content if index == total - 1 else "[removed]"


_REBUILD_PATHS = ["system_message", "reasoning", "model_input", "media", "collapse"]


def _rebuilt_input(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> tuple[Model, list[ChatMessage], list[Tool], GenerateConfig]:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    model = get_model("mockllm/model")
    monkeypatch.setattr(model.api, "tool_result_images", lambda: path != "media")
    monkeypatch.setattr(model.api, "collapse_user_messages", lambda: path == "collapse")
    messages = [
        ChatMessageUser(content="Do the steps."),
        *([ChatMessageUser(content="Go on.")] if path == "collapse" else []),
        *_step_call(1),
        *_step_call(2),
    ]
    tools = (
        [tool_with(step(), model_input=_truncate_older)]
        if path == "model_input"
        else []
    )
    config = GenerateConfig(
        system_message="Be careful." if path == "system_message" else None,
        reasoning_history="last" if path == "reasoning" else None,
    )
    return model, messages, tools, config


def _rebuilt_positions(event: ModelEvent, messages: list[ChatMessage]) -> list[int]:
    caller_ids = {m.id for m in messages}
    return [i for i, m in enumerate(event.input) if m.id not in caller_ids]


def _assert_one_content_per_id(events: list[ModelEvent]) -> None:
    contents: dict[str | None, bytes | None] = {}
    for event in events:
        ids = [m.id for m in event.input]
        assert len(set(ids)) == len(ids)
        for message in event.input:
            content = logged_json(message, exclude_id=True)
            assert contents.setdefault(message.id, content) == content


@contextmanager
def _registered_hook(hook: type[Hooks]) -> Iterator[None]:
    name = "test_model_event_input_hook"

    @hooks(name, description="Test hook.")
    def test_hook() -> type[Hooks]:
        return hook

    try:
        yield
    finally:
        del _registry[f"hooks:{name}"]


@contextmanager
def _input_hook(
    action: Callable[[int, BeforeModelGenerate], None],
) -> Iterator[None]:
    class InputHook(Hooks):
        calls = 0

        async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
            InputHook.calls += 1
            action(InputHook.calls, data)

    with _registered_hook(InputHook):
        yield


def _set_header(call: int, data: BeforeModelGenerate) -> None:
    # like a tracing hook: reads the input, changes only the request headers
    data.config.extra_headers = {"x-input-length": str(len(data.input))}


@pytest.mark.parametrize("hook", [False, True], ids=["no_hook", "header_only_hook"])
@pytest.mark.parametrize("path", _REBUILD_PATHS)
async def test_model_event_input_rebuilt_messages_keep_ids(
    monkeypatch: pytest.MonkeyPatch, path: str, hook: bool
) -> None:
    model, messages, tools, config = _rebuilt_input(monkeypatch, path)
    before = deepcopy(messages)

    with _input_hook(_set_header) if hook else nullcontext():
        for _ in range(2):
            await model.generate(messages, tools=tools, config=config)

    # the caller's messages are not changed
    assert [m.model_dump() for m in messages] == [m.model_dump() for m in before]
    first, second = _model_events()
    rebuilt = _rebuilt_positions(first, messages)
    assert rebuilt
    assert [m.id for m in first.input] == [m.id for m in second.input]
    assert len({m.id for m in first.input}) == len(first.input)
    for i in rebuilt:
        # the unchanged rebuilt message reuses the first event's snapshot
        assert first.input[i] is second.input[i]


@pytest.mark.parametrize("path", _REBUILD_PATHS)
async def test_model_event_input_hook_edit_gives_rebuilt_messages_new_ids(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    model, messages, tools, config = _rebuilt_input(monkeypatch, path)
    caller_ids = {m.id for m in messages}
    before = deepcopy(messages)

    def edit_second_call(call: int, data: BeforeModelGenerate) -> None:
        if call == 2:
            next(m for m in data.input if m.id not in caller_ids).content = "edited"

    with _input_hook(edit_second_call):
        for _ in range(3):
            await model.generate(messages, tools=tools, config=config)

    assert [m.model_dump() for m in messages] == [m.model_dump() for m in before]
    events = _model_events()
    _assert_one_content_per_id(events)
    first, edited, third = events
    rebuilt = _rebuilt_positions(first, messages)
    assert rebuilt == _rebuilt_positions(edited, messages)
    assert "edited" in [edited.input[i].text for i in rebuilt]
    # every rebuilt message of the edited call gets a new id, used only there
    edited_ids = {edited.input[i].id for i in rebuilt}
    assert len(edited_ids) == len(rebuilt)
    assert not edited_ids & {m.id for e in (first, third) for m in e.input}
    for i in range(len(first.input)):
        if i in rebuilt:
            assert first.input[i] is third.input[i]
        else:
            assert first.input[i].id == edited.input[i].id == third.input[i].id


@pytest.mark.parametrize("case", ["saved", "saved_edited", "alias"])
async def test_model_event_input_hook_reintroduced_rebuilt_message_gets_new_id(
    case: str,
) -> None:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    model = get_model("mockllm/model")
    config = GenerateConfig(system_message="one")
    saved: list[ChatMessage] = []
    saved_ids: list[str | None] = []

    def reintroduce(call: int, data: BeforeModelGenerate) -> None:
        if call == 1:
            saved.append(data.input[0].model_copy())
            saved_ids.append(data.input[0].id)
        elif case == "alias":
            data.input.append(data.input[0])
        else:
            if case == "saved_edited":
                saved[0].content = "edited"
            data.input.append(saved[0])

    with _input_hook(reintroduce):
        await model.generate([ChatMessageUser(content="hi")], config=config)
        # the caller passes on a copy of the rebuilt message, with its id
        caller = _model_events()[0].input[0].model_copy(deep=True)
        messages: list[ChatMessage] = [caller, ChatMessageUser(content="again")]
        before = deepcopy(messages)
        await model.generate(messages, config=config)

    events = _model_events()
    _assert_one_content_per_id(events)
    second = events[1]
    assert second.input[1].id == caller.id == saved_ids[0]
    assert second.input[-1].id != caller.id
    assert [m.model_dump() for m in messages] == [m.model_dump() for m in before]


@pytest.mark.parametrize("path", _REBUILD_PATHS)
async def test_model_event_input_hook_giving_rebuilt_message_caller_id_renews_it(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    model, messages, tools, config = _rebuilt_input(monkeypatch, path)
    caller_ids = [m.id for m in messages]
    before = deepcopy(messages)

    def take_caller_id(call: int, data: BeforeModelGenerate) -> None:
        rebuilt = next(m for m in data.input if m.id not in caller_ids)
        rebuilt.id = next(m.id for m in data.input if m.id in caller_ids)

    with _input_hook(take_caller_id):
        await model.generate(messages, tools=tools, config=config)

    [event] = _model_events()
    ids = [m.id for m in event.input]
    assert len(set(ids)) == len(ids)
    assert set(caller_ids) & set(ids)
    assert [m.model_dump() for m in messages] == [m.model_dump() for m in before]


async def test_model_event_input_hook_appending_combined_caller_keeps_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    model = get_model("mockllm/model")
    monkeypatch.setattr(model.api, "collapse_user_messages", lambda: True)
    await model.generate(
        [ChatMessageUser(content="one"), ChatMessageUser(content="two")]
    )
    # the caller passes on the combined message, which is combined again
    caller = _model_events()[0].input[0].model_copy(deep=True)
    before = caller.model_dump()

    def append_caller(call: int, data: BeforeModelGenerate) -> None:
        data.input.append(caller)

    with _input_hook(append_caller):
        await model.generate([caller, ChatMessageUser(content="three")])

    # the caller's message keeps its id and content
    assert caller.model_dump() == before
    _assert_one_content_per_id(_model_events())


@pytest.mark.parametrize("path", _REBUILD_PATHS)
async def test_model_event_input_hook_appending_earlier_snapshot_leaves_it_unchanged(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    model, messages, tools, config = _rebuilt_input(monkeypatch, path)
    await model.generate(messages, tools=tools, config=config)
    [first] = _model_events()
    rebuilt = _rebuilt_positions(first, messages)[0]
    snapshot = first.input[rebuilt]
    snapshot_id = snapshot.id

    def append_snapshot(call: int, data: BeforeModelGenerate) -> None:
        if call == 1:
            data.input.append(snapshot)

    with _input_hook(append_snapshot):
        for _ in range(2):
            await model.generate(messages, tools=tools, config=config)

    # the earlier event keeps its id, and a later unchanged call reuses it
    _, _, third = _model_events()
    assert snapshot.id == snapshot_id
    assert third.input[rebuilt] is snapshot
    _assert_one_content_per_id(_model_events())


@pytest.mark.parametrize("metadata", [False, True])
async def test_model_event_input_hook_edits_on_retry_get_new_ids(
    monkeypatch: pytest.MonkeyPatch, metadata: bool
) -> None:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    sent: list[ChatMessage] = []

    def output(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        sent.append(input[0].model_copy())
        if len(sent) == 1:
            raise RuntimeError("retry once")
        return ModelOutput.from_content(model="mockllm", content="ok")

    model = get_model("mockllm/model", memoize=False, custom_outputs=output)
    monkeypatch.setattr(model.api, "should_retry", lambda ex: True)
    monkeypatch.setattr(model.api, "retry_wait", lambda: wait_none())
    seen: list[str | None] = []

    def edit(call: int, data: BeforeModelGenerate) -> None:
        seen.append(data.input[0].id)
        data.input[0].content = f"edit {call}"
        # a value with no content key on the first attempt only
        data.input[0].metadata = (
            {"items": iter([1, 2])} if metadata and call == 1 else None
        )

    with _input_hook(edit):
        await model.generate(
            [ChatMessageUser(content="hi")],
            config=GenerateConfig(system_message="x", max_retries=2),
        )

    assert [m.text for m in sent] == ["edit 1", "edit 2"]
    # each attempt's edit gets its own new id
    assert len({seen[0], sent[0].id, sent[1].id}) == 3
    _assert_one_content_per_id(_model_events())


@pytest.mark.parametrize("field", ["metadata", "arguments"])
async def test_model_event_input_rebuilt_message_with_non_json_values_gets_new_id(
    field: str,
) -> None:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()

    def output(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # with usage, so mockllm does not count tokens of the iterator
        result = ModelOutput.from_content(model="mockllm", content="ok")
        result.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        return result

    model = get_model("mockllm/model", memoize=False, custom_outputs=output)

    for items in [iter([1, 2]), [1, 2], [1, 2]]:
        value = {"items": items}
        await model.generate(
            [
                ChatMessageUser(id="user", content="hi"),
                ChatMessageAssistant(
                    id="assistant",
                    content=[
                        ContentReasoning(reasoning="thought"),
                        ContentText(text="answer"),
                    ],
                    metadata=value if field == "metadata" else None,
                    tool_calls=[
                        ToolCall(
                            id="call",
                            function="step",
                            arguments=value if field == "arguments" else {},
                        )
                    ],
                ),
            ],
            config=GenerateConfig(reasoning_history="none"),
        )

    # serializing an iterator consumes it, so it is not keyed; plain JSON is
    first, second, third = _model_events()
    assert first.input[1].id != second.input[1].id
    assert second.input[1].id == third.input[1].id
    assert second.input[1] is third.input[1]


async def test_model_event_input_changed_system_message_gets_new_id() -> None:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    model = get_model("mockllm/model")
    messages: list[ChatMessage] = [ChatMessageUser(content="hi")]

    for system_message in ["one", "two", "one"]:
        await model.generate(
            messages, config=GenerateConfig(system_message=system_message)
        )

    ids = [event.input[0].id for event in _model_events()]
    assert ids[0] != ids[1]
    assert ids[0] == ids[2]


@pytest.mark.parametrize("reasoning_history", ["none", "last"])
async def test_model_event_input_identical_rebuilt_messages_keep_distinct_ids(
    reasoning_history: Literal["none", "last"],
) -> None:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    model = get_model("mockllm/model")
    messages: list[ChatMessage] = [ChatMessageUser(content="hi")]
    # identical once their reasoning is removed
    for n in range(3):
        messages.append(
            ChatMessageAssistant(
                content=[
                    ContentReasoning(reasoning=f"thought {n}"),
                    ContentText(text="Thinking."),
                ]
            )
        )
        messages.append(ChatMessageUser(content="go on"))
    before = deepcopy(messages)

    for _ in range(3):
        await model.generate(
            messages, config=GenerateConfig(reasoning_history=reasoning_history)
        )

    assert [m.model_dump() for m in messages] == [m.model_dump() for m in before]
    first, *rest = _model_events()
    assert len({m.id for m in first.input}) == len(first.input)
    for event in rest:
        assert [m.id for m in event.input] == [m.id for m in first.input]
        assert all(a is b for a, b in zip(event.input, first.input))


@pytest.mark.parametrize("role", ["user", "assistant"])
async def test_model_event_input_rebuilt_ids_avoid_combined_caller_ids(
    monkeypatch: pytest.MonkeyPatch, role: Literal["user", "assistant"]
) -> None:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    model = get_model("mockllm/model")
    monkeypatch.setattr(model.api, f"collapse_{role}_messages", lambda: True)
    message_type = ChatMessageUser if role == "user" else ChatMessageAssistant
    separator_type = ChatMessageAssistant if role == "user" else ChatMessageUser
    pair: list[ChatMessage] = [message_type(content="one"), message_type(content="two")]
    await model.generate(pair)
    # the caller keeps the combined message's id but changes its content
    edited = _model_events()[0].input[0].model_copy(update={"content": "edited"})
    messages: list[ChatMessage] = [
        *pair,
        separator_type(content="separator"),
        edited,
        message_type(content="three"),
    ]
    before = deepcopy(messages)

    await model.generate(messages)
    await model.generate(messages)

    assert [m.model_dump() for m in messages] == [m.model_dump() for m in before]
    _, second, third = _model_events()
    assert second.input[2].metadata is not None
    assert second.input[2].metadata["combined_from"][0] == edited.id
    assert second.input[0].id != edited.id
    assert [m.id for m in second.input] == [m.id for m in third.input]
    for a, b in zip(second.input, third.input):
        assert a is b


def test_model_event_input_rebuilt_ids_not_shared_across_samples() -> None:
    system_ids: list[list[str | None]] = []

    @solver
    def generate_twice() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state = await generate(state)
            state.messages.append(ChatMessageUser(content="again"))
            state = await generate(state)
            system_ids.append([event.input[0].id for event in _model_events()])
            return state

        return solve

    log = eval(
        Task(
            dataset=[Sample(input="one"), Sample(input="two")],
            solver=generate_twice(),
            config=GenerateConfig(system_message="Be careful."),
            epochs=2,
        ),
        model="mockllm/model",
        display="none",
    )[0]

    assert log.status == "success"
    assert len(system_ids) == 4
    assert all(first == second for first, second in system_ids)
    assert len({first for first, _ in system_ids}) == 4


@pytest.mark.parametrize("shape", ["cyclic", "deep"])
@pytest.mark.parametrize("field", ["metadata", "arguments"])
def test_rebuilt_message_with_recursive_values_has_no_key(
    field: str, shape: str
) -> None:
    def message(value: dict[str, Any]) -> ChatMessage:
        return ChatMessageAssistant(
            content="answer",
            metadata=value if field == "metadata" else None,
            tool_calls=[
                ToolCall(
                    id="call",
                    function="step",
                    arguments=value if field == "arguments" else {},
                )
            ],
        )

    value: dict[str, Any] = {}
    if shape == "cyclic":
        value["self"] = value
    else:
        inner = value
        for _ in range(2000):
            inner["k"] = {}
            inner = inner["k"]

    # no key (so a fresh id) rather than an error; plain JSON is keyed
    assert _rebuilt_message_key(message(value)) is None
    assert _rebuilt_message_key(message({"items": [1, 2]})) is not None
