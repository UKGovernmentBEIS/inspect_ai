import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

import anyio
import pytest

from inspect_ai import Task, eval
from inspect_ai._sentinel._config import resolve_sentinel_root, resolve_sentinel_spec
from inspect_ai._sentinel._context import init_sentinel
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import as_solver, as_tool, handoff, react
from inspect_ai.dataset import Sample
from inspect_ai.event import (
    Event,
    ModelEvent,
    SentinelEvent,
    SpanBeginEvent,
    SpanEndEvent,
    ToolEvent,
)
from inspect_ai.log import EvalLog
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.scorer import Reference, Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState, generate, use_tools
from inspect_ai.tool import Tool, ToolCall, ToolCallView, tool
from inspect_ai.util import StoreModel
from inspect_ai.util._limit import LimitExceededError

try:
    from inspect_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        Context,
        Decision,
        Monitor,
        MonitorGroup,
        Observation,
        Protocol,
        ProtocolGroup,
        Reported,
        concurrent,
        decide_final,
        monitor,
        protocol,
    )
except ImportError:
    pytest.skip("inspect_sentinel is not installed", allow_module_level=True)


@tool
def addition() -> Tool:
    async def execute(x: int, y: int) -> str:
        """Add two numbers.

        Args:
            x: First number to add.
            y: Second number to add.
        """
        return str(x + y)

    return execute


@protocol
def d3_reject(
    reason: str = "not allowed", message: str | None = "no adding"
) -> Protocol:
    async def decide(context: Context, step: BeforeToolCall) -> Decision | None:
        return Decision.reject(reason, message=message)

    return decide


@protocol
def d3_modify() -> Protocol:
    async def rewrite(context: Context, step: BeforeToolCall) -> Decision | None:
        modified = replace(step.call, arguments={"x": 10, "y": 20})
        return Decision(action="modify", modified=modified, explanation="bigger")

    return rewrite


@protocol
def d3_terminate() -> Protocol:
    async def stop(context: Context, step: BeforeToolCall) -> Decision | None:
        return Decision.terminate("too risky")

    return stop


@protocol
def d3_terminate_after() -> Protocol:
    async def stop(context: Context, step: AfterToolCall) -> Decision | None:
        return Decision.terminate(f"saw {step.result.text}")

    return stop


@protocol
def d3_escalate() -> Protocol:
    async def unsure(context: Context, step: BeforeToolCall) -> Decision | None:
        return Decision.escalate("not sure")

    return unsure


@protocol
def d3_continue() -> Protocol:
    async def fine(context: Context, step: BeforeToolCall) -> Decision | None:
        return Decision.proceed()

    return fine


@protocol
def d3_final() -> Protocol:
    async def veto(context: Context, step: BeforeToolCall) -> Decision | None:
        decide_final(Decision.reject(message="vetoed"))
        return None

    return veto


@monitor
def d3_suspicion(score: float = 0.25) -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        return Observation.score(score, "looked")

    return check


_CITE = Reference(type="message", id="msg_2", cite="[M2]")


@monitor
def d3_cites() -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        return Observation.score(0.3, "see [M2]", references=[_CITE])

    return check


@protocol
def d3_cites_reject() -> Protocol:
    async def decide(context: Context, step: BeforeToolCall) -> Decision | None:
        return Decision.reject("see [M2]", references=[_CITE])

    return decide


class Trajectory(StoreModel):
    calls: int = 0


@monitor
def d3_trajectory() -> MonitorGroup:
    async def count(context: Context, step: BeforeToolCall) -> Observation | None:
        context.store_as(Trajectory).calls += 1
        return None

    async def report(context: Context, step: AfterToolCall) -> Observation | None:
        return Observation.score(float(context.store_as(Trajectory).calls))

    return MonitorGroup(count, report)


@monitor
def d3_asks_model() -> Monitor:
    async def ask(context: Context, step: BeforeToolCall) -> Observation | None:
        output = await context.host.generate("How suspicious is this call?")
        return Observation.score(float(output.completion))

    return ask


@monitor
def d3_asks_with(model: str | Model | None = None, role: str | None = None) -> Monitor:
    async def ask(context: Context, step: BeforeToolCall) -> Observation | None:
        output = await context.host.generate(
            "How suspicious is this call?", model=model, role=role
        )
        return Observation.score(float(output.completion))

    return ask


@monitor
def d3_raises() -> Monitor:
    async def boom(context: Context, step: BeforeToolCall) -> Observation | None:
        raise RuntimeError("monitor exploded")

    return boom


Seen = list[tuple[Context, BeforeToolCall]]


@monitor
def d3_recording(seen: Any) -> Monitor:
    async def record(context: Context, step: BeforeToolCall) -> Observation | None:
        seen.append((context, step))
        return None

    return record


def agent_model(turns: int = 1) -> Any:
    outputs = [
        ModelOutput.for_tool_call(
            "mockllm/model",
            tool_name="addition",
            tool_arguments={"x": 1, "y": turn + 1},
        )
        for turn in range(turns)
    ]
    outputs.append(ModelOutput.from_content("mockllm/model", content="done"))
    return get_model("mockllm/model", custom_outputs=outputs, memoize=False)


def run(sentinel: Any, turns: int = 1, **kwargs: Any) -> EvalLog:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2", metadata={"s": 1})],
        solver=[use_tools(addition()), generate()],
        metadata={"t": 1},
        sentinel=sentinel,
    )
    return eval(task, model=agent_model(turns), **kwargs)[0]


def sentinel_events(log: EvalLog) -> list[SentinelEvent]:
    assert log.samples
    return [e for e in log.samples[0].events if isinstance(e, SentinelEvent)]


def tool_messages(log: EvalLog) -> list[ChatMessageTool]:
    assert log.samples
    return [m for m in log.samples[0].messages if isinstance(m, ChatMessageTool)]


def summary(events: list[SentinelEvent]) -> list[tuple[Any, ...]]:
    return [(e.factory, e.path, e.function, e.kind, e.status, e.action) for e in events]


def test_reject_message_reaches_the_model_and_is_recorded() -> None:
    log = run(d3_reject(reason="internal reason", message="use X instead"))
    assert log.status == "success", log.error

    [message] = tool_messages(log)
    assert message.error is not None
    assert message.error.type == "approval"
    assert message.error.message == "use X instead"
    assert "internal reason" not in message.text

    events = sentinel_events(log)
    assert summary(events) == [
        ("d3_reject", "", "decide", "decision", "reported", "reject")
    ]
    assert all(e.stage == "tool_call" for e in events)
    assert all(e.step_id == message.tool_call_id for e in events)
    assert all(e.explanation == "internal reason" for e in events)
    assert all(e.message == "use X instead" for e in events)


def test_reject_without_message_uses_the_default() -> None:
    log = run(d3_reject(reason="internal reason", message=None))
    assert log.status == "success", log.error

    [message] = tool_messages(log)
    assert message.error is not None
    assert message.error.message == "Tool call not approved."
    assert "internal reason" not in message.text
    assert all(e.message is None for e in sentinel_events(log))


def test_modify_executes_the_modified_call() -> None:
    log = run(d3_modify())
    assert log.status == "success", log.error

    [message] = tool_messages(log)
    assert message.error is None
    assert message.text == "30"
    events = sentinel_events(log)
    assert [e.action for e in events] == ["modify"]
    for event in events:
        assert event.modified is not None
        assert event.modified.arguments == {"x": 10, "y": 20}
        assert event.modified.id == message.tool_call_id

    # as with approval's modify, the ToolEvent shows the call the model made
    assert log.samples
    [tool_event] = [e for e in log.samples[0].events if isinstance(e, ToolEvent)]
    assert tool_event.arguments == {"x": 1, "y": 1}


def test_terminate_ends_the_sample() -> None:
    log = run(d3_terminate())
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is not None
    assert sample.limit.type == "operator"
    assert sample.limit.reason == "too risky"
    tool_events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert [e.pending for e in tool_events] == [None]
    assert tool_events[0].failed is True


def test_terminate_after_the_call() -> None:
    log = run(d3_terminate_after())
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is not None
    assert sample.limit.type == "operator"
    assert sample.limit.reason == "saw 2"
    events = sentinel_events(log)
    assert {e.stage for e in events} == {"tool_result"}
    assert [e.action for e in events] == ["terminate"]


@protocol
def d3_reject_handoff() -> Protocol:
    async def decide(context: Context, step: BeforeToolCall) -> Decision | None:
        if step.call.function == "transfer_to_helper":
            return Decision.reject("no handoffs", message="do it yourself")
        return None

    return decide


def run_handoff(sentinel: Any) -> EvalLog:
    helper_model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model", tool_name="addition", tool_arguments={"x": 2, "y": 3}
            ),
            ModelOutput.from_content("mockllm/model", content="helper done"),
        ],
        memoize=False,
    )
    helper = react(
        name="helper",
        description="A helper agent.",
        tools=[addition()],
        model=helper_model,
        submit=False,
    )
    parent_model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model", tool_name="transfer_to_helper", tool_arguments={}
            ),
            ModelOutput.from_content("mockllm/model", content="done"),
        ],
        memoize=False,
    )
    task = Task(
        dataset=[Sample(input="What is 2 + 3?", target="5")],
        solver=[use_tools(handoff(helper)), generate()],
        sentinel=sentinel,
    )
    return eval(task, model=parent_model)[0]


def handoff_call_id(log: EvalLog) -> str:
    assert log.samples
    [call_id] = [
        call.id
        for m in log.samples[0].messages
        if isinstance(m, ChatMessageAssistant)
        for call in m.tool_calls or []
        if call.function == "transfer_to_helper"
    ]
    return call_id


def test_a_rejected_handoff_does_not_run() -> None:
    log = run_handoff(d3_reject_handoff())
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]

    [message] = tool_messages(log)
    assert message.function == "transfer_to_helper"
    assert message.error is not None
    assert message.error.message == "do it yourself"

    assert not any(
        isinstance(e, SpanBeginEvent) and e.type in ("handoff", "agent")
        for e in sample.events
    )
    assert len([e for e in sample.events if isinstance(e, ModelEvent)]) == 2

    [event] = sentinel_events(log)
    assert event.stage == "tool_call"
    assert event.action == "reject"
    assert event.step_id == handoff_call_id(log)
    [tool_event] = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert tool_event.pending is None


def test_a_handoff_runs_and_its_sub_agent_calls_are_checked() -> None:
    seen: list[Any] = []
    log = run_handoff([d3_recording(seen), d3_suspicion()])
    assert log.status == "success", log.error
    assert [step.call.function for _, step in seen] == [
        "transfer_to_helper",
        "addition",
    ]
    assert log.samples
    assert any("helper done" in m.text for m in log.samples[0].messages)

    events = sentinel_events(log)
    call_ids = {e.step_id for e in events if e.stage == "tool_call"}
    assert handoff_call_id(log) in call_ids
    assert len(call_ids) == 2


def test_a_handoff_result_is_checked() -> None:
    log = run_handoff([d3_trajectory()])
    assert log.status == "success", log.error
    after = [e for e in sentinel_events(log) if e.stage == "tool_result"]
    assert handoff_call_id(log) in {e.step_id for e in after}


@protocol
def d3_terminate_after_handoff() -> Protocol:
    async def stop(context: Context, step: AfterToolCall) -> Decision | None:
        if step.call.function == "transfer_to_helper":
            return Decision.terminate("handoff went badly")
        return None

    return stop


def test_terminate_after_a_handoff_ends_the_sample() -> None:
    log = run_handoff(d3_terminate_after_handoff())
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is not None
    assert sample.limit.type == "operator"
    assert sample.limit.reason == "handoff went badly"
    [event] = [e for e in sentinel_events(log) if e.action == "terminate"]
    assert event.stage == "tool_result"
    assert event.step_id == handoff_call_id(log)


def test_observe_records_observations_without_effect() -> None:
    log = run([d3_suspicion(score=0.4)])
    assert log.status == "success", log.error

    [message] = tool_messages(log)
    assert message.error is None
    assert message.text == "2"
    [event] = sentinel_events(log)
    assert (
        event.factory,
        event.path,
        event.function,
        event.kind,
        event.status,
    ) == ("d3_suspicion", "d3_suspicion", "check", "observation", "reported")
    assert event.suspicion == 0.4
    assert event.explanation == "looked"
    assert event.action is None


def test_references_are_recorded_from_each_report() -> None:
    log = run({"watch": d3_cites(), "block": d3_cites_reject()})
    assert log.status == "success", log.error
    events = {e.path: e for e in sentinel_events(log)}
    assert {path: e.references for path, e in events.items()} == {
        "watch": [_CITE],
        "block": [_CITE],
        "": [_CITE],
    }


def test_final_from_a_nested_protocol() -> None:
    log = run(concurrent({"inner": d3_final()}))
    assert log.status == "success", log.error

    [message] = tool_messages(log)
    assert message.error is not None
    assert message.error.message == "vetoed"
    assert summary(sentinel_events(log)) == [
        ("inspect_sentinel/concurrent", "", None, "decision", "bypassed", None),
        ("d3_final", "inner", "veto", "decision", "reported", "reject"),
    ]
    assert all(e.references == [] for e in sentinel_events(log))


def test_an_escalate_at_the_root_proceeds_and_warns_once(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai._util import logger as logger_module

    monkeypatch.setattr(logger_module, "_warned", [])
    with caplog.at_level(logging.WARNING):
        log = run({"unsure": d3_escalate(), "fine": d3_continue()}, turns=2)
    assert log.status == "success", log.error

    assert [m.text for m in tool_messages(log)] == ["2", "3"]
    assert all(m.error is None for m in tool_messages(log))
    root = [e for e in sentinel_events(log) if e.path == ""]
    assert [e.action for e in root] == ["escalate", "escalate"]
    warnings = [r for r in caplog.records if "nothing to escalate to" in r.message]
    assert len(warnings) == 1
    assert "sequential([..., human()])" in warnings[0].message


def test_multi_function_monitor_shares_state_across_calls() -> None:
    log = run([d3_trajectory()], turns=2)
    assert log.status == "success", log.error

    events = sentinel_events(log)
    assert [(e.function, e.stage, e.suspicion) for e in events] == [
        ("report", "tool_result", 1.0),
        ("report", "tool_result", 2.0),
    ]
    assert log.samples
    assert log.samples[0].store["Trajectory:d3_trajectory:calls"] == 2


def test_host_generate_uses_the_monitor_role() -> None:
    monitor_model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", content="0.75")],
        memoize=False,
    )
    log = run([d3_asks_model()], model_roles={"monitor": monitor_model})
    assert log.status == "success", log.error

    [event] = sentinel_events(log)
    assert event.suspicion == 0.75
    assert log.samples
    roles = [e.role for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert roles.count("monitor") == 1


def sentinel_span_ids(events: Sequence[Event]) -> list[str]:
    return [
        e.id for e in events if isinstance(e, SpanBeginEvent) and e.type == "sentinel"
    ]


def test_sentinel_events_nest_under_a_sentinel_span() -> None:
    monitor_model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", content="0.5")],
        memoize=False,
    )
    log = run([d3_asks_model()], model_roles={"monitor": monitor_model})
    assert log.status == "success", log.error
    assert log.samples
    events = log.samples[0].events

    # the monitor watches only before the call, so no span is opened after it
    [before] = sentinel_span_ids(events)
    [monitor_call] = [
        e for e in events if isinstance(e, ModelEvent) and e.role == "monitor"
    ]
    assert monitor_call.span_id == before
    assert all(e.span_id == before for e in sentinel_events(log))
    agent_calls = [e for e in events if isinstance(e, ModelEvent) and e.role is None]
    assert agent_calls and all(e.span_id != before for e in agent_calls)
    [tool_event] = [e for e in events if isinstance(e, ToolEvent)]
    assert tool_event.span_id != before
    ended = [e.id for e in events if isinstance(e, SpanEndEvent)]
    assert ended.count(before) == 1


def test_each_stage_runs_in_its_own_sentinel_span() -> None:
    log = run([d3_trajectory()], turns=2)
    assert log.status == "success", log.error
    assert log.samples
    events = log.samples[0].events
    span_ids = sentinel_span_ids(events)
    assert len(span_ids) == 4
    ended = {e.id for e in events if isinstance(e, SpanEndEvent)}
    assert set(span_ids) <= ended
    assert {e.span_id for e in sentinel_events(log)} <= set(span_ids)


def test_a_raising_monitor_fails_the_sample() -> None:
    log = run([d3_raises()])
    assert log.status == "error"
    assert log.samples
    assert log.samples[0].error is not None
    assert "monitor exploded" in log.samples[0].error.message


def test_context_and_step_come_from_the_sample(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: Seen = []
    with caplog.at_level(logging.WARNING):
        log = run([d3_recording(seen)])
    assert not [r for r in caplog.records if "sentinel step's input" in r.message]
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]

    [(context, step)] = seen
    assert context.task == log.eval.task
    assert context.sample_id == sample.id
    assert context.epoch == 1
    assert context.input == "What is 1 + 1?"
    assert context.metadata == {"t": 1, "s": 1}
    assert context.path == "d3_recording"
    assert context.task_description is None
    assert context.sample_description is None

    assert step.conversation == sample.uuid
    assert step.call.function == "addition"
    assert step.view.call is not None
    assert step.history[-1].role == "assistant"
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert [m.text for m in step.input] == [m.text for m in model_events[0].input]


@contextmanager
def active(sentinel: Any) -> Iterator[None]:
    init_sentinel(resolve_sentinel_root(resolve_sentinel_spec(sentinel)))
    try:
        yield
    finally:
        init_sentinel(None)


def addition_call(id: str = "call") -> ToolCall:
    return ToolCall(id=id, function="addition", arguments={"x": 1, "y": 1})


def transcript_tool_events() -> list[ToolEvent]:
    return [e for e in transcript().events if isinstance(e, ToolEvent)]


@monitor
def d3_waiting(started: Any, cleaned_up: Any, after: bool = False) -> MonitorGroup:
    async def wait() -> None:
        started.set()
        try:
            await anyio.sleep_forever()
        finally:
            cleaned_up.set()

    async def before(context: Context, step: BeforeToolCall) -> Observation | None:
        if not after:
            await wait()
        return None

    async def later(context: Context, step: AfterToolCall) -> Observation | None:
        if after:
            await wait()
        return None

    return MonitorGroup(before, later)


async def test_sample_cancellation_during_the_sentinel_propagates() -> None:
    init_transcript(Transcript())
    started = anyio.Event()
    cleaned_up = anyio.Event()

    with active([d3_waiting(started, cleaned_up)]):
        with anyio.CancelScope() as scope:

            async def cancel_sample() -> None:
                await started.wait()
                scope.cancel()

            async with anyio.create_task_group() as tg:
                tg.start_soon(cancel_sample)
                await execute_tools(
                    [ChatMessageAssistant(content=[], tool_calls=[addition_call()])],
                    [addition()],
                )

    assert scope.cancelled_caught
    assert cleaned_up.is_set()
    events = [e for e in transcript().events if isinstance(e, SentinelEvent)]
    assert [(e.path, e.kind, e.status) for e in events] == [
        ("d3_waiting", "observation", "cancelled"),
        ("", "decision", "cancelled"),
    ]
    assert transcript_tool_events() == []
    [span_id] = sentinel_span_ids(transcript().events)
    assert {e.span_id for e in events} == {span_id}
    assert any(
        isinstance(e, SpanEndEvent) and e.id == span_id for e in transcript().events
    )


def test_sample_time_limit_during_the_sentinel_ends_the_sample() -> None:
    started = anyio.Event()
    cleaned_up = anyio.Event()
    log = run([d3_waiting(started, cleaned_up)], time_limit=1)
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is not None
    assert sample.limit.type == "time"
    assert cleaned_up.is_set()
    assert [(e.path, e.kind, e.status) for e in sentinel_events(log)] == [
        ("d3_waiting", "observation", "cancelled"),
        ("", "decision", "cancelled"),
    ]
    assert tool_messages(log) == []


async def test_operator_cancel_during_the_after_call_sentinel() -> None:
    init_transcript(Transcript())
    started = anyio.Event()
    cleaned_up = anyio.Event()

    async def cancel_call() -> None:
        await started.wait()
        [event] = transcript_tool_events()
        event._cancel()

    with active([d3_waiting(started, cleaned_up, after=True)]):
        async with anyio.create_task_group() as tg:
            tg.start_soon(cancel_call)
            with pytest.raises(TerminateSampleError, match="cancelled"):
                await execute_tools(
                    [ChatMessageAssistant(content=[], tool_calls=[addition_call()])],
                    [addition()],
                )

    [event] = transcript_tool_events()
    assert event.result == "2"
    assert event.pending is None
    assert cleaned_up.is_set()


async def test_parallel_calls_run_their_sentinels_concurrently() -> None:
    init_transcript(Transcript())
    both = anyio.Event()
    arrived: list[str] = []

    @monitor
    def d3_rendezvous() -> Monitor:
        async def meet(context: Context, step: BeforeToolCall) -> Observation | None:
            arrived.append(step.call.id)
            if len(arrived) == 2:
                both.set()
            await both.wait()
            return Observation.score(0.0)

        return meet

    @tool(parallel=True)
    def parallel_addition() -> Tool:
        async def execute(x: int, y: int) -> str:
            """Add two numbers.

            Args:
                x: First number to add.
                y: Second number to add.
            """
            return str(x + y)

        return execute

    calls = [
        ToolCall(id=id, function="parallel_addition", arguments={"x": 1, "y": 1})
        for id in ("a", "b")
    ]
    with active([d3_rendezvous()]):
        with anyio.fail_after(10):
            result = await execute_tools(
                [ChatMessageAssistant(content=[], tool_calls=calls)],
                [parallel_addition()],
            )

    assert sorted(arrived) == ["a", "b"]
    assert [m.text for m in result.messages] == ["2", "2"]
    events = [e for e in transcript().events if isinstance(e, SentinelEvent)]
    assert sorted(e.step_id for e in events) == ["a", "b"]


def test_conversation_is_the_enclosing_agent_span() -> None:
    seen: Seen = []
    task = Task(
        dataset=[Sample(input="What is 1 + 1?")],
        solver=as_solver(react(tools=[addition()], submit=False)),
        sentinel=[d3_recording(seen)],
    )
    log = eval(task, model=agent_model())[0]
    assert log.status == "success", log.error
    assert log.samples

    [(_, step)] = seen
    agent_spans = [
        e.id
        for e in log.samples[0].events
        if isinstance(e, SpanBeginEvent) and e.type == "agent"
    ]
    assert step.conversation == agent_spans[-1]


@monitor
def d3_raising(error: Any, after: bool = False) -> MonitorGroup:
    async def before(context: Context, step: BeforeToolCall) -> Observation | None:
        if not after:
            raise error
        return None

    async def later(context: Context, step: AfterToolCall) -> Observation | None:
        if after:
            raise error
        return None

    return MonitorGroup(before, later)


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize(
    "error", [TimeoutError("sentinel timed out"), PermissionError("sentinel denied")]
)
def test_sentinel_errors_fail_the_sample_rather_than_the_call(
    error: Exception, after: bool
) -> None:
    log = run([d3_raising(error, after=after)])
    assert log.status == "error"
    assert log.samples
    sample_error = log.samples[0].error
    assert sample_error is not None
    assert type(error).__name__ in sample_error.traceback
    assert str(error) in sample_error.message
    if isinstance(error, TimeoutError):
        stage = "tool_result" if after else "tool_call"
        assert f"A sentinel timed out at the {stage} stage" in sample_error.message
    assert tool_messages(log) == []
    [event] = [e for e in log.samples[0].events if isinstance(e, ToolEvent)]
    assert event.pending is None
    assert event.failed is True
    assert event.result == ("2" if after else "")
    events = log.samples[0].events
    ended = {e.id for e in events if isinstance(e, SpanEndEvent)}
    assert sentinel_span_ids(events) and set(sentinel_span_ids(events)) <= ended


def test_host_generate_without_a_monitor_role_labels_the_agent_model() -> None:
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model", tool_name="addition", tool_arguments={"x": 1, "y": 1}
            ),
            ModelOutput.from_content("mockllm/model", content="0.5"),
            ModelOutput.from_content("mockllm/model", content="done"),
        ],
        memoize=False,
    )
    task = Task(
        dataset=[Sample(input="What is 1 + 1?")],
        solver=[use_tools(addition()), generate()],
        sentinel=[d3_asks_model()],
    )
    log = eval(task, model=model)[0]
    assert log.status == "success", log.error

    [event] = sentinel_events(log)
    assert event.suspicion == 0.5
    assert log.samples
    roles = [e.role for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert roles == [None, "monitor", None]


def _scoring_model(score: str) -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", content=score)],
        memoize=False,
    )


def test_host_generate_uses_a_named_role() -> None:
    log = run(
        [d3_asks_with(role="trusted")], model_roles={"trusted": _scoring_model("0.25")}
    )
    assert log.status == "success", log.error
    [event] = sentinel_events(log)
    assert event.suspicion == 0.25
    assert log.samples
    roles = [e.role for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert roles.count("trusted") == 1


def test_host_generate_model_is_always_a_model_name() -> None:
    # a role named like the model must not shadow an explicit model
    log = run(
        [d3_asks_with(model="mockllm/model")],
        model_roles={"mockllm/model": _scoring_model("0.9")},
    )
    assert log.status == "error"
    assert log.error is not None
    assert "could not convert string to float" in log.error.message


def test_host_generate_prefers_a_configured_role_to_the_model() -> None:
    log = run(
        [d3_asks_with(model=_scoring_model("0.6"), role="trusted")],
        model_roles={"trusted": _scoring_model("0.25")},
    )
    assert log.status == "success", log.error
    [event] = sentinel_events(log)
    assert event.suspicion == 0.25


def test_host_generate_uses_the_model_when_the_role_is_not_configured(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        log = run([d3_asks_with(model=_scoring_model("0.6"), role="trusted")])
    assert log.status == "success", log.error
    [event] = sentinel_events(log)
    assert event.suspicion == 0.6
    assert not [r for r in caplog.records if "sentinel role" in r.getMessage()]


def test_host_generate_warns_once_without_the_role(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inspect_ai._util.logger as logger_module

    monkeypatch.setattr(logger_module, "_warned", [])
    with caplog.at_level(logging.WARNING):
        run([d3_asks_with(role="judge")])
    warnings = [
        r.getMessage()
        for r in caplog.records
        if "sentinel role 'judge'" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert "--model-role judge=" in warnings[0]


async def test_missing_model_event_falls_back_to_the_prior_conversation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    init_transcript(Transcript())
    seen: Seen = []

    @tool(parallel=True)
    def parallel_addition() -> Tool:
        async def execute(x: int, y: int) -> str:
            """Add two numbers.

            Args:
                x: First number to add.
                y: Second number to add.
            """
            return str(x + y)

        return execute

    prompt = ChatMessageUser(content="What is 1 + 1?")
    calls = [
        ToolCall(id=id, function="parallel_addition", arguments={"x": 1, "y": 1})
        for id in ("a", "b")
    ]
    with active([d3_recording(seen)]), caplog.at_level(logging.WARNING):
        await execute_tools(
            [prompt, ChatMessageAssistant(content=[], tool_calls=calls)],
            [parallel_addition()],
        )

    assert [step.input for _, step in seen] == [[prompt], [prompt]]
    warnings = [r for r in caplog.records if "No ModelEvent was found" in r.message]
    assert len(warnings) == 1


def test_missing_assistant_message_falls_back_to_the_whole_conversation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    init_transcript(Transcript())
    from inspect_ai._sentinel._dispatch import _model_input

    history: list[ChatMessage] = [ChatMessageUser(content="hi")]
    with caplog.at_level(logging.WARNING):
        assert _model_input(addition_call(), history) == history
        assert _model_input(addition_call(), history) == history
    warnings = [r for r in caplog.records if "No assistant message" in r.message]
    assert len(warnings) == 1


def indexed_model_event(input: str, role: str | None = None) -> ModelEvent:
    return ModelEvent(
        model="mockllm/model",
        role=role,
        input=[ChatMessageUser(content=input)],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", content=input),
    )


def output_id(event: ModelEvent) -> str:
    message_id = event.output.choices[0].message.id
    assert message_id is not None
    return message_id


def test_model_input_index_is_bounded_to_resident_events() -> None:
    from inspect_ai._sentinel._dispatch import _sample_inputs

    current = Transcript(bounded=True, resident_tail=3)
    init_transcript(current)
    inputs = _sample_inputs(current)
    events = []
    for turn in range(10):
        event = indexed_model_event(f"turn {turn}")
        current._event(event)
        events.append(event)
        found = inputs.find(current, output_id(event))
        assert found is not None and found[0].text == f"turn {turn}"
    assert len(inputs._inputs) <= len(current.history.resident_events)


def test_model_input_index_skips_monitor_calls() -> None:
    from inspect_ai._sentinel._dispatch import _sample_inputs

    current = Transcript()
    init_transcript(current)
    agent = indexed_model_event("agent")
    monitor_call = indexed_model_event("monitor", role="monitor")
    current._event(agent)
    current._event(monitor_call)
    inputs = _sample_inputs(current)
    assert inputs.find(current, output_id(monitor_call)) is None
    found = inputs.find(current, output_id(agent))
    assert found is not None and found[0].text == "agent"
    assert list(inputs._inputs) == [output_id(agent)]


@pytest.mark.parametrize("action", ["continue", "reject", "terminate"])
def test_a_modified_call_on_a_non_modify_decision_is_not_dropped(
    action: Any,
) -> None:
    from inspect_ai._sentinel._dispatch import _context, _Recorder

    init_transcript(Transcript())
    call = addition_call()
    step = BeforeToolCall(
        conversation="c",
        message="",
        call=call,
        view=ToolCallView(),
        input=[],
        history=[],
    )
    reported = Reported(
        name="p", path="p", function="f", report=Decision(action=action, modified=call)
    )
    with pytest.raises(ValueError, match="modified is set only"):
        _Recorder(call.id).record(
            replace(_context(call.id), factory="p", path="p"), step, reported
        )


def test_apply_sentinel_decision() -> None:
    from inspect_ai._sentinel._context import SentinelFailure
    from inspect_ai._sentinel._dispatch import apply_sentinel_decision
    from inspect_ai.tool._tool import ToolApprovalError

    call = addition_call()
    modified = replace(call, arguments={"x": 5, "y": 6})
    assert apply_sentinel_decision(None, call) is call
    assert apply_sentinel_decision(Decision.proceed(), call) is call
    assert (
        apply_sentinel_decision(Decision(action="modify", modified=modified), call)
        is modified
    )
    with pytest.raises(ToolApprovalError, match="use X"):
        apply_sentinel_decision(Decision.reject("why", message="use X"), call)
    with pytest.raises(TerminateSampleError, match="too risky"):
        apply_sentinel_decision(Decision.terminate("too risky"), call)
    with pytest.raises(SentinelFailure):
        apply_sentinel_decision(Decision(action="modify"), call)


def test_a_modify_decision_without_a_modified_call_fails_the_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._sentinel import _dispatch

    async def modify_without_call(*args: Any) -> Decision:
        return Decision(action="modify")

    monkeypatch.setattr(_dispatch, "sentinel_before_tool_call", modify_without_call)
    log = run([d3_suspicion()])
    assert log.status == "error"
    assert log.samples
    sample_error = log.samples[0].error
    assert sample_error is not None
    assert "modify decision has no modified call" in sample_error.message
    assert tool_messages(log) == []
    [event] = [e for e in log.samples[0].events if isinstance(e, ToolEvent)]
    assert event.failed is True


@pytest.mark.parametrize(
    "error,limit",
    [
        (TerminateSampleError("stop now"), "operator"),
        (
            LimitExceededError(
                "working", value=10, limit=5, message="working limit hit"
            ),
            "working",
        ),
    ],
)
def test_sentinel_limits_end_the_sample_before_the_call(
    error: Exception, limit: str
) -> None:
    log = run([d3_raising(error)])
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    assert sample.error is None
    assert sample.limit is not None and sample.limit.type == limit
    assert tool_messages(log) == []
    [event] = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert event.pending is None
    assert event.failed is True


def test_each_turn_sees_its_own_model_input(caplog: pytest.LogCaptureFixture) -> None:
    seen: Seen = []
    with caplog.at_level(logging.WARNING):
        log = run([d3_recording(seen)], turns=3)
    assert log.status == "success", log.error
    assert not [r for r in caplog.records if "sentinel step's input" in r.message]
    assert log.samples
    model_events = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert len(seen) == 3
    for (_, step), event in zip(seen, model_events, strict=False):
        assert [m.id for m in step.input] == [m.id for m in event.input]
    assert len({len(step.input) for _, step in seen}) == 3


GenerateSeen = list[BeforeGenerate | AfterGenerate]


@monitor
def d3_generates(seen: Any, ask: bool = False) -> MonitorGroup:
    async def before(context: Context, step: BeforeGenerate) -> Observation | None:
        seen.append(step)
        if ask:
            await context.host.generate("How suspicious is this request?")
        return Observation.score(0.1)

    async def after(context: Context, step: AfterGenerate) -> Observation | None:
        seen.append(step)
        return Observation.score(0.2)

    return MonitorGroup(before, after)


@protocol
def d3_generate_decides(action: Any, after: bool) -> ProtocolGroup:
    async def before_generate(
        context: Context, step: BeforeGenerate
    ) -> Decision | None:
        return None if after else Decision(action=action, explanation="no generate")

    async def after_generate(context: Context, step: AfterGenerate) -> Decision | None:
        if after and step.output.message.tool_calls:
            return Decision(action=action, explanation="no tools")
        return None

    return ProtocolGroup(before_generate, after_generate)


@tool
def graded() -> Tool:
    async def execute(text: str) -> str:
        """Grade some text with a model.

        Args:
            text: The text to grade.
        """
        output = await get_model().generate(f"Grade: {text}")
        return output.completion

    return execute


@scorer(metrics=[])
def d3_model_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        output = await get_model().generate("Grade the answer.")
        return Score(value=output.completion)

    return score


def agent_events(log: EvalLog) -> list[ModelEvent]:
    assert log.samples
    return [
        e for e in log.samples[0].events if isinstance(e, ModelEvent) and e.role is None
    ]


def test_a_monitor_sees_each_agent_generate_before_and_after() -> None:
    seen: GenerateSeen = []
    log = run([d3_generates(seen)])
    assert log.status == "success", log.error

    model_events = agent_events(log)
    assert len(model_events) == 2
    assert [type(step) for step in seen] == [
        BeforeGenerate,
        AfterGenerate,
        BeforeGenerate,
        AfterGenerate,
    ]
    for index, event in enumerate(model_events):
        before, after = seen[2 * index], seen[2 * index + 1]
        assert isinstance(after, AfterGenerate)
        assert [m.id for m in before.input] == [m.id for m in event.input]
        assert [t.name for t in before.tools] == ["addition"]
        assert before.model == "mockllm/model"
        assert after.output.message.id == event.output.message.id
        assert after.input is before.input

    events = sentinel_events(log)
    assert [(e.stage, e.step_id) for e in events if e.path == "d3_generates"] == [
        ("model_input", model_events[0].input[-1].id),
        ("model_output", model_events[0].output.message.id),
        ("model_input", model_events[1].input[-1].id),
        ("model_output", model_events[1].output.message.id),
    ]
    assert log.samples
    assert len(sentinel_span_ids(log.samples[0].events)) == 4


def test_generate_stages_check_only_the_agents_own_calls() -> None:
    seen: GenerateSeen = []
    agent = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model", tool_name="graded", tool_arguments={"text": "hi"}
            ),
            ModelOutput.from_content("mockllm/model", content="tool grade"),
            ModelOutput.from_content("mockllm/model", content="done"),
            ModelOutput.from_content("mockllm/model", content="scorer grade"),
        ],
        memoize=False,
    )
    monitor_model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", content="0") for _ in range(2)
        ],
        memoize=False,
    )
    task = Task(
        dataset=[Sample(input="Grade hi.", target="ok")],
        solver=[use_tools(graded()), generate()],
        scorer=d3_model_scorer(),
        sentinel=[d3_generates(seen, ask=True)],
    )
    log = eval(task, model=agent, model_roles={"monitor": monitor_model})[0]
    assert log.status == "success", log.error

    # the agent's two turns, then the tool's and the scorer's calls
    model_events = agent_events(log)
    assert [e.output.completion for e in model_events][1:] == [
        "tool grade",
        "done",
        "scorer grade",
    ]
    agent_turns = [model_events[0], model_events[2]]
    afters = [step for step in seen if isinstance(step, AfterGenerate)]
    assert [step.output.message.id for step in afters] == [
        e.output.message.id for e in agent_turns
    ]
    assert len(seen) == 4


def test_a_sub_agent_on_another_model_is_not_checked() -> None:
    seen: GenerateSeen = []
    log = run_handoff([d3_generates(seen)])
    assert log.status == "success", log.error
    afters = [step for step in seen if isinstance(step, AfterGenerate)]
    assert [step.output.completion for step in afters][1:] == ["done"]
    assert len(afters) == 2


def test_an_agent_run_as_a_tool_is_checked() -> None:
    seen: GenerateSeen = []
    agent = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model", tool_name="helper", tool_arguments={"input": "add"}
            ),
            ModelOutput.for_tool_call(
                "mockllm/model", tool_name="submit", tool_arguments={"answer": "5"}
            ),
            ModelOutput.from_content("mockllm/model", content="done"),
        ],
        memoize=False,
    )
    helper = react(name="helper", description="A helper agent.", tools=[addition()])
    task = Task(
        dataset=[Sample(input="What is 2 + 3?", target="5")],
        solver=[use_tools(as_tool(helper)), generate()],
        sentinel=[d3_generates(seen)],
    )
    log = eval(task, model=agent)[0]
    assert log.status == "success", log.error
    afters = [step for step in seen if isinstance(step, AfterGenerate)]
    assert [step.output.message.id for step in afters] == [
        e.output.message.id for e in agent_events(log)
    ]
    assert len(afters) == 3
    parent, sub_agent, _ = (step.conversation for step in afters)
    assert parent != sub_agent


@pytest.mark.parametrize("after", [False, True])
def test_terminate_at_a_generate_stage_ends_the_sample(after: bool) -> None:
    log = run(d3_generate_decides("terminate", after))
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is not None
    assert sample.limit.type == "operator"
    assert sample.limit.reason == ("no tools" if after else "no generate")
    assert len(agent_events(log)) == (1 if after else 0)
    assert not [e for e in sample.events if isinstance(e, ToolEvent)]
    assert {(e.stage, e.action) for e in sentinel_events(log)} == {
        ("model_output" if after else "model_input", "terminate")
    }


@pytest.mark.parametrize("action", ["reject", "escalate"])
@pytest.mark.parametrize("after", [False, True])
def test_unsupported_actions_at_a_generate_stage_fail_the_sample(
    action: str, after: bool
) -> None:
    log = run(d3_generate_decides(action, after))
    assert log.status == "error"
    assert log.samples
    error = log.samples[0].error
    assert error is not None
    assert "only 'continue' and 'terminate' are supported" in error.message
