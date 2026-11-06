"""A log without origins built to make inference over it super-linear, and a count of the work done over it.

Shared by the scaling tests of `timeline_build()` (tests/timeline) and `steps_from_events()` (tests/sentinel).
"""

import os
import sys
from collections.abc import Callable
from types import FrameType
from typing import Any, NamedTuple, TypeVar

import inspect_ai
from inspect_ai.event import (
    Event,
    ModelEvent,
    SentinelEvent,
    SpanBeginEvent,
    SpanEndEvent,
    ToolEvent,
)
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
)
from inspect_ai.tool import ToolCall

T = TypeVar("T")


class AdversarialLog(NamedTuple):
    events: list[Event]
    """The events, with model inputs expanded."""
    messages: list[ChatMessage]
    """The final messages: the last call's input and output."""


def adversarial_log(rounds: int, window: int | None, checks: bool) -> AdversarialLog:
    """A main agent without origins over `rounds` rounds, combining what has made inference over such a log super-linear.

    - Repeated ids: every call issues a tool call `task`, which a bridge task (`agent-task`) at the start waits on and is never answered.
    - Fragmented inputs: a new reminder sits second in every input.
    - Falling lengths: in the first half each input carries on the last; in the second each is shorter than the one before, cycling.
    - Unresolved forks: every fourth call is sent again with its input, and that answer is never carried on.
    - Legacy checks (`checks`): before each call, a sentinel 0.1.x check named by its input's last message id, with a repeat suffix when the id repeats.

    `window` bounds the history an input holds, so expanded inputs grow linearly with the rounds; None leaves it unbounded, for pooled inputs.
    """
    system = ChatMessageSystem(content="You are the main agent.")
    user = ChatMessageUser(content="Do the tasks.")
    events: list[Event] = [
        SpanBeginEvent(id="solvers", name="solvers", type="solvers"),
        SpanBeginEvent(id="main", name="main", type="agent", parent_id="solvers"),
        SpanBeginEvent(id="agent-task", name="sub", type="agent", parent_id="main"),
        _model(
            "sub",
            "agent-task",
            [ChatMessageUser(content="Do the task.")],
            ChatMessageAssistant(content="Working."),
        ),
        SpanEndEvent(id="agent-task"),
    ]
    history: list[ChatMessage] = []
    longest: list[ChatMessage] = []
    named: dict[str, int] = {}
    half = rounds // 2
    input: list[ChatMessage] = []
    output = ChatMessageAssistant(content="")
    for round in range(rounds):
        reminder = ChatMessageUser(content=f"Reminder {round}.")
        if round < half:
            kept = history if window is None else history[-window:]
            longest = kept
        else:
            falls = 2 * (round - half + 1)
            kept = longest[: len(longest) - falls % (len(longest) + 1)]
        input = [system, reminder, user, *kept]
        call = ToolCall(id=f"c{round}", function="addition", arguments={"n": round})
        task = ToolCall(id="task", function="task", arguments={})
        output = ChatMessageAssistant(
            content=f"Round {round}.", tool_calls=[task, call]
        )
        if checks:
            name = input[-1].id or ""
            count = named.get(name, 0)
            named[name] = count + 1
            events += _check(f"m{round}", name if count == 0 else f"{name}:{count}")
        events.append(_model(f"m{round}", "main", input, output))
        if round % 4 == 3:
            alternative = ChatMessageAssistant(
                content=f"Alternative {round}.", tool_calls=[task]
            )
            events.append(_model(f"f{round}", "main", input, alternative))
        events.append(
            ToolEvent(
                id=call.id,
                function="addition",
                arguments={"n": round},
                result="2",
                span_id="main",
            )
        )
        if round < half:
            result = ChatMessageTool(
                content="2", tool_call_id=call.id, function="addition"
            )
            history = [*history, output, result]
    events += [SpanEndEvent(id="main"), SpanEndEvent(id="solvers")]
    return AdversarialLog(events, [*input, output])


def _model(
    uuid: str, span: str, input: list[ChatMessage], output: ChatMessageAssistant
) -> ModelEvent:
    return ModelEvent(
        uuid=uuid,
        span_id=span,
        model="mockllm/model",
        input=list(input),
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(
            model="mockllm/model",
            choices=[ChatCompletionChoice(message=output, stop_reason="stop")],
        ),
    )


def _check(call: str, step_id: str) -> list[Event]:
    span = f"check-{call}"
    return [
        SpanBeginEvent(id=span, name="probe", type="sentinel", parent_id="main"),
        SentinelEvent(
            factory="probe",
            path="probe",
            function="check",
            step_id=step_id,
            conversation="main",
            stage="model_input",
            kind="observation",
            status="reported",
            suspicion=0.1,
            span_id=span,
        ),
        SpanEndEvent(id=span),
    ]


def executed_lines(
    function: Callable[..., T], *args: Any, **kwargs: Any
) -> tuple[T, int]:
    """`function(*args, **kwargs)`, and the lines of inspect_ai's source it executed: a count of Python-level work, which a loop over a growing structure raises however cheap its body."""
    root = os.path.dirname(inspect_ai.__file__) + os.sep
    count = 0

    def local(frame: FrameType, event: str, arg: Any) -> Any:
        nonlocal count
        if event == "line":
            count += 1
        return local

    def trace(frame: FrameType, event: str, arg: Any) -> Any:
        return local if frame.f_code.co_filename.startswith(root) else None

    previous = sys.gettrace()
    sys.settrace(trace)
    try:
        result = function(*args, **kwargs)
    finally:
        sys.settrace(previous)
    return result, count
