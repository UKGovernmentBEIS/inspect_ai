"""`ModelEvent` records its input and output as they were when the model was called."""

import json
import math
import threading
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

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
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    ModelUsage,
    get_model,
)
from inspect_ai.model._chat_message import logged_json
from inspect_ai.model._model import (
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


async def _generate_twice(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> tuple[list[ChatMessage], list[ModelEvent]]:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    model = get_model("mockllm/model")
    monkeypatch.setattr(model.api, "tool_result_images", lambda: path != "media")
    monkeypatch.setattr(model.api, "collapse_user_messages", lambda: path == "collapse")
    messages = [
        ChatMessageUser(content="Do the steps."),
        *_step_call(1),
        *_step_call(2),
    ]
    if path == "collapse":
        messages.append(ChatMessageUser(content="Continue."))
        messages.append(ChatMessageUser(content="Please."))
        messages.append(ChatMessageUser(content="Thanks."))
    tools = (
        [tool_with(step(), model_input=_truncate_older)]
        if path == "model_input"
        else []
    )
    config = GenerateConfig(
        system_message="Be careful." if path == "system_message" else None,
        reasoning_history="last" if path == "reasoning" else None,
    )
    before = deepcopy(messages)

    await model.generate(messages, tools=tools, config=config)
    await model.generate(messages, tools=tools, config=config)

    # the caller's messages are not changed
    assert [m.model_dump() for m in messages] == [m.model_dump() for m in before]
    return messages, _model_events()


@pytest.mark.parametrize(
    "path", ["system_message", "reasoning", "model_input", "media", "collapse"]
)
async def test_model_event_input_rebuilt_messages_keep_ids(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    messages, (first, second) = await _generate_twice(monkeypatch, path)

    caller_ids = {m.id for m in messages}
    rebuilt = [i for i, m in enumerate(first.input) if m.id not in caller_ids]
    assert rebuilt
    assert [m.id for m in first.input] == [m.id for m in second.input]
    assert len({m.id for m in first.input}) == len(first.input)
    for i in rebuilt:
        # the unchanged rebuilt message reuses the first event's snapshot
        assert first.input[i] is second.input[i]


@pytest.mark.parametrize(
    "flag",
    [
        "collapse_user_messages",
        "collapse_assistant_messages",
        "collapse_system_messages",
    ],
)
async def test_model_event_input_collapsed_runs_keep_ids(
    monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    model = get_model("mockllm/model")
    monkeypatch.setattr(model.api, flag, lambda: True)
    builders: dict[str, Callable[[str], ChatMessage]] = {
        "collapse_user_messages": lambda text: ChatMessageUser(content=text),
        "collapse_assistant_messages": lambda text: ChatMessageAssistant(content=text),
        "collapse_system_messages": lambda text: ChatMessageSystem(content=text),
    }
    message = builders[flag]
    messages = [message(f"part {i}") for i in range(3)]
    messages.append(ChatMessageUser(content="Go."))

    await model.generate(messages)
    await model.generate(messages)

    first, second = _model_events()
    # the run combines an earlier combination, whose id it records
    assert first.input[0].metadata is not None
    assert first.input[0].metadata["combined_from"][0] not in {m.id for m in messages}
    assert first.input[0].id == second.input[0].id
    assert first.input[0] is second.input[0]


class _EditSystemMessage(Hooks):
    edits: list[str] = []

    def __init__(self) -> None:
        self.calls = 0

    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        data.input[0].content = self.edits[self.calls]
        self.calls += 1


@contextmanager
def _edit_system_message(edits: list[str]) -> Iterator[None]:
    name = "test_model_event_input_edit_system_message"
    _EditSystemMessage.edits = edits

    @hooks(name, description="Edit the system message.")
    def edit_system_message() -> type[Hooks]:
        return _EditSystemMessage

    try:
        yield
    finally:
        del _registry[f"hooks:{name}"]


@pytest.mark.parametrize("edits", [["one", "two"], ["one", "one"]])
async def test_model_event_input_rebuilt_ids_follow_hook_edits(
    edits: list[str],
) -> None:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    model = get_model("mockllm/model")
    messages: list[ChatMessage] = [ChatMessageUser(content="hi")]

    with _edit_system_message(edits):
        for _ in edits:
            await model.generate(messages, config=GenerateConfig(system_message="x"))

    first, second = _model_events()
    assert [first.input[0].text, second.input[0].text] == edits
    assert (first.input[0].id == second.input[0].id) == (edits[0] == edits[1])


@pytest.mark.parametrize("edits", [["one", "two"], ["one", "one"]])
async def test_model_event_input_rebuilt_ids_follow_hook_edits_on_retry(
    monkeypatch: pytest.MonkeyPatch, edits: list[str]
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

    with _edit_system_message(edits):
        await model.generate(
            [ChatMessageUser(content="hi")],
            config=GenerateConfig(system_message="x", max_retries=2),
        )

    assert [message.text for message in sent] == edits
    assert (sent[0].id == sent[1].id) == (edits[0] == edits[1])


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


async def test_model_event_input_identical_rebuilt_messages_get_distinct_ids() -> None:
    init_transcript(Transcript())
    init_sample_rebuilt_message_ids()
    model = get_model("mockllm/model")
    assistant: list[Content] = [
        ContentReasoning(reasoning="hmm"),
        ContentText(text="Thinking."),
    ]
    messages: list[ChatMessage] = [
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(content=list(assistant)),
        ChatMessageUser(content="go on"),
        ChatMessageAssistant(content=list(assistant)),
        ChatMessageUser(content="go on"),
    ]

    await model.generate(messages, config=GenerateConfig(reasoning_history="none"))

    (event,) = _model_events()
    assert event.input[1] == event.input[3].model_copy(update={"id": event.input[1].id})
    assert event.input[1].id != event.input[3].id


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
