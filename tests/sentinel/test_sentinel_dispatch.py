import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, cast

import anyio
import pytest

from inspect_ai import Task, eval
from inspect_ai._sentinel._config import resolve_sentinel_root, resolve_sentinel_spec
from inspect_ai._sentinel._context import init_sentinel
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import (
    agent_bridge,
    as_solver,
    as_tool,
    deepagent,
    handoff,
    react,
    subagent,
)
from inspect_ai.approval import Approval, ApprovalPolicy, Approver, approver
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
    ModelUsage,
    get_model,
)
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.review import Review, Reviewer, ReviewPolicy, reviewer
from inspect_ai.scorer import Reference, Score, Scorer, Target, scorer
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import (
    Tool,
    ToolCall,
    ToolCallView,
    ToolFunction,
    ToolInfo,
    ToolResult,
    tool,
)
from inspect_ai.util import StoreModel
from inspect_ai.util._limit import LimitExceededError

try:
    from inspect_sentinel import (
        AfterToolCall,
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
        observe_only,
        protocol,
        threshold,
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
def d3_asks_with(model: str | None = None, role: str | None = None) -> Monitor:
    async def ask(context: Context, step: BeforeToolCall) -> Observation | None:
        output = await context.host.generate(
            "How suspicious is this call?", model=model, role=role
        )
        return Observation.score(float(output.completion))

    return ask


@monitor
def d3_asks_with_tools() -> Monitor:
    async def ask(context: Context, step: BeforeToolCall) -> Observation | None:
        output = await context.host.generate(
            "How suspicious is this call?",
            tools=[ToolInfo(name="flag", description="Flag the call.")],
            tool_choice=ToolFunction(name="flag"),
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


def run(
    sentinel: Any,
    turns: int = 1,
    task_description: str | None = None,
    sample_description: str | None = None,
    **kwargs: Any,
) -> EvalLog:
    task = Task(
        dataset=[
            Sample(
                input="What is 1 + 1?",
                target="2",
                metadata={"s": 1},
                description=sample_description,
            )
        ],
        solver=[use_tools(addition()), generate()],
        metadata={"t": 1},
        sentinel=sentinel,
        description=task_description,
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

    # as with approval's modify, the ToolEvent shows the arguments that ran and the
    # ModelEvent keeps the model's proposal
    assert log.samples
    [tool_event] = [e for e in log.samples[0].events if isinstance(e, ToolEvent)]
    assert tool_event.arguments == {"x": 10, "y": 20}
    [model_event, *_] = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    [proposed] = model_event.output.message.tool_calls or []
    assert proposed.arguments == {"x": 1, "y": 1}


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


def run_handoff(sentinel: Any, via_tool: bool = False) -> EvalLog:
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
                "mockllm/model",
                tool_name="helper" if via_tool else "transfer_to_helper",
                tool_arguments={"input": "add 2 and 3"} if via_tool else {},
            ),
            ModelOutput.from_content("mockllm/model", content="done"),
        ],
        memoize=False,
    )
    task = Task(
        dataset=[Sample(input="What is 2 + 3?", target="5")],
        solver=[
            use_tools(as_tool(helper) if via_tool else handoff(helper)),
            generate(),
        ],
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
    log = run_handoff(observe_only([d3_recording(seen), d3_suspicion()]))
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
    log = run_handoff(observe_only([d3_trajectory()]))
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


@approver
def d3_approver(
    seen: list[ToolCall], decision: str = "approve", x: int | None = None
) -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        seen.append(call)
        if decision == "modify":
            return Approval(
                decision="modify",
                modified=replace(call, arguments={**call.arguments, "x": x}),
            )
        return Approval(decision="reject" if decision == "reject" else "approve")

    return approve


@reviewer
def d3_terminating_reviewer() -> Reviewer:
    async def review_(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        return Review(decision="terminate", explanation="reviewer stopped it")

    return review_


def run_with(sentinel: Any, **task_kwargs: Any) -> EvalLog:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[use_tools(addition()), generate()],
        sentinel=sentinel,
        **task_kwargs,
    )
    return eval(task, model=agent_model())[0]


def test_an_approvers_modify_reaches_the_sentinel() -> None:
    approved: list[ToolCall] = []
    seen: Seen = []
    log = run_with(
        observe_only([d3_recording(seen)]),
        approval=[ApprovalPolicy(d3_approver(approved, "modify", x=7), "*")],
    )
    assert log.status == "success", log.error
    assert [call.arguments for call in approved] == [{"x": 1, "y": 1}]
    assert [step.call.arguments for _, step in seen] == [{"x": 7, "y": 1}]
    [message] = tool_messages(log)
    assert message.text == "8"


def test_an_approval_reject_skips_the_sentinel() -> None:
    approved: list[ToolCall] = []
    seen: Seen = []
    log = run_with(
        observe_only([d3_recording(seen), d3_suspicion()]),
        approval=[ApprovalPolicy(d3_approver(approved, "reject"), "*")],
    )
    assert log.status == "success", log.error
    assert len(approved) == 1
    assert seen == []
    assert sentinel_events(log) == []
    [message] = tool_messages(log)
    assert message.error is not None and message.error.type == "approval"


def test_a_sentinel_modify_is_not_re_approved() -> None:
    approved: list[ToolCall] = []
    log = run_with(d3_modify(), approval=[ApprovalPolicy(d3_approver(approved), "*")])
    assert log.status == "success", log.error
    assert [call.arguments for call in approved] == [{"x": 1, "y": 1}]
    [message] = tool_messages(log)
    assert message.text == "30"


def test_a_review_terminate_skips_the_after_call_sentinel() -> None:
    log = run_with(
        observe_only([d3_trajectory()]),
        review=[ReviewPolicy(d3_terminating_reviewer(), "*")],
    )
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is not None and sample.limit.type == "operator"
    assert [e for e in sentinel_events(log) if e.stage == "tool_result"] == []
    # without the review, the after-call sentinel reports
    after = sentinel_events(run_with(observe_only([d3_trajectory()])))
    assert [e.stage for e in after] == ["tool_result"]


def test_observe_only_records_observations_without_effect() -> None:
    log = run(observe_only([d3_suspicion(score=0.4)]))
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


@solver
def bridged() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        async with agent_bridge():
            pass
        return state

    return solve


@pytest.mark.parametrize("sentinel", [True, False])
def test_bridged_agent_warns_once_that_sentinels_do_not_run(
    sentinel: bool,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._util import logger as logger_module

    monkeypatch.setattr(logger_module, "_warned", [])
    task = Task(
        dataset=[Sample(input="a"), Sample(input="b")],
        solver=bridged(),
        sentinel=d3_continue() if sentinel else None,
    )
    with caplog.at_level(logging.WARNING):
        [log] = eval(task, model="mockllm/model")
    assert log.status == "success", log.error
    warnings = [r for r in caplog.records if "bridged agents" in r.message]
    assert len(warnings) == (1 if sentinel else 0)
    if sentinel:
        assert "issues/5759" in warnings[0].message


def test_multi_function_monitor_shares_state_across_calls() -> None:
    log = run(observe_only([d3_trajectory()]), turns=2)
    assert log.status == "success", log.error

    events = sentinel_events(log)
    assert [(e.function, e.stage, e.suspicion) for e in events] == [
        ("report", "tool_result", 1.0),
        ("report", "tool_result", 2.0),
    ]
    assert log.samples
    assert log.samples[0].store["Trajectory:d3_trajectory:calls"] == 2


@pytest.mark.parametrize("role", [None, "monitor"])
def test_host_generate_uses_the_monitor_role(role: str | None) -> None:
    monitor_model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", content="0.75")],
        memoize=False,
    )
    log = run(
        observe_only([d3_asks_with(role=role)]),
        model_roles={"monitor": monitor_model},
    )
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
    log = run(observe_only([d3_asks_model()]), model_roles={"monitor": monitor_model})
    assert log.status == "success", log.error
    assert log.samples
    events = log.samples[0].events

    before, after = sentinel_span_ids(events)
    [monitor_call] = [
        e for e in events if isinstance(e, ModelEvent) and e.role == "monitor"
    ]
    assert monitor_call.span_id == before
    assert all(e.span_id == before for e in sentinel_events(log))
    agent_calls = [e for e in events if isinstance(e, ModelEvent) and e.role is None]
    assert agent_calls and all(e.span_id not in (before, after) for e in agent_calls)
    [tool_event] = [e for e in events if isinstance(e, ToolEvent)]
    assert tool_event.span_id not in (before, after)
    ended = [e.id for e in events if isinstance(e, SpanEndEvent)]
    assert ended.count(before) == 1 and ended.count(after) == 1


def test_each_stage_runs_in_its_own_sentinel_span() -> None:
    log = run(observe_only([d3_trajectory()]), turns=2)
    assert log.status == "success", log.error
    assert log.samples
    events = log.samples[0].events
    span_ids = sentinel_span_ids(events)
    assert len(span_ids) == 4
    ended = {e.id for e in events if isinstance(e, SpanEndEvent)}
    assert set(span_ids) <= ended
    assert {e.span_id for e in sentinel_events(log)} <= set(span_ids)


def test_a_raising_monitor_under_observe_only_is_recorded_and_the_sample_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        log = run(observe_only([d3_raises(), d3_suspicion()]))
    assert log.status == "success", log.error
    [message] = tool_messages(log)
    assert message.text == "2"
    failed, observed = sentinel_events(log)
    assert (failed.path, failed.function, failed.kind, failed.status) == (
        "d3_raises",
        "boom",
        "observation",
        "error",
    )
    assert failed.error == "RuntimeError: monitor exploded"
    assert failed.suspicion is None
    assert observed.status == "reported"
    assert any(
        "Monitor 'd3_raises'" in r.getMessage() and "monitor exploded" in r.getMessage()
        for r in caplog.records
    )


def test_a_raising_monitor_under_threshold_fails_the_sample() -> None:
    log = run(threshold(d3_raises(), reject_at=0.5))
    assert log.status == "error"
    assert log.samples
    error = log.samples[0].error
    assert error is not None
    assert "MonitorFailedError" in error.traceback
    assert "'d3_raises' (function 'boom'): RuntimeError: monitor exploded" in (
        error.message
    )
    assert tool_messages(log) == []
    [failed] = sentinel_events(log)
    assert (failed.path, failed.status, failed.error) == (
        "d3_raises",
        "error",
        "RuntimeError: monitor exploded",
    )


def test_context_and_step_come_from_the_sample(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: Seen = []
    with caplog.at_level(logging.WARNING):
        log = run(observe_only([d3_recording(seen)]))
    assert not [r for r in caplog.records if "sentinel step's input" in r.message]
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]

    [(context, step)] = seen
    assert context.path == "d3_recording"
    assert context.eval is not None
    assert context.eval.task == log.eval.task
    assert context.eval.sample_id == sample.id
    assert context.eval.epoch == 1
    assert context.eval.sample_input == "What is 1 + 1?"
    assert context.eval.metadata == {"t": 1, "s": 1}
    assert context.eval.task_description is None
    assert context.eval.sample_description is None

    assert step.conversation == sample.uuid
    assert step.call.function == "addition"
    assert step.view.call is not None
    assert step.history[-1].role == "assistant"
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert [m.text for m in step.input] == [m.text for m in model_events[0].input]


def test_context_has_the_task_and_sample_descriptions() -> None:
    seen: Seen = []
    log = run(
        observe_only([d3_recording(seen)]),
        task_description="Add numbers with the tool.",
        sample_description="Add one and one.",
    )
    assert log.status == "success", log.error

    [(context, _)] = seen
    assert context.eval is not None
    assert context.eval.task_description == "Add numbers with the tool."
    assert context.eval.sample_description == "Add one and one."


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

    with active(observe_only([d3_waiting(started, cleaned_up)])):
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
    log = run(observe_only([d3_waiting(started, cleaned_up)]), time_limit=1)
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

    with active(observe_only([d3_waiting(started, cleaned_up, after=True)])):
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
    with active(observe_only([d3_rendezvous()])):
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
        sentinel=observe_only([d3_recording(seen)]),
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


@protocol
def d3_raising(error: Any, after: bool = False) -> ProtocolGroup:
    async def before(context: Context, step: BeforeToolCall) -> Decision | None:
        if not after:
            raise error
        return None

    async def later(context: Context, step: AfterToolCall) -> Decision | None:
        if after:
            raise error
        return None

    return ProtocolGroup(before, later)


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


@protocol
def d3_raising_in_helper(error: Any, after: bool = False) -> ProtocolGroup:
    async def before(context: Context, step: BeforeToolCall) -> Decision | None:
        if not after and step.call.function == "addition":
            raise error
        return None

    async def later(context: Context, step: AfterToolCall) -> Decision | None:
        if after and step.call.function == "addition":
            raise error
        return None

    return ProtocolGroup(before, later)


@pytest.mark.parametrize("via_tool", [False, True])
@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("sentinel config missing"), PermissionError("sentinel denied")],
)
def test_sentinel_errors_in_a_sub_agent_fail_the_sample(
    error: Exception, after: bool, via_tool: bool
) -> None:
    log = run_handoff([d3_raising_in_helper(error, after=after)], via_tool=via_tool)
    assert log.status == "error"
    assert log.samples
    sample_error = log.samples[0].error
    assert sample_error is not None
    assert sample_error.message == f"{type(error).__name__}('{error}')"
    assert "SentinelFailure" not in sample_error.message
    assert all(
        message.error is None
        for message in log.samples[0].messages
        if isinstance(message, ChatMessageTool)
    )


def test_sentinel_errors_in_a_background_sub_agent_fail_the_sample() -> None:
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
    helper = subagent(
        name="helper",
        description="A helper agent.",
        prompt="You are a helper.",
        model=helper_model,
        extra_tools=[addition()],
    )
    parent_model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="agent",
                tool_arguments={"prompt": "add 2 and 3", "background": True},
            ),
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="agent_wait",
                tool_arguments={"agent_ids": ["AGENT-1"]},
            ),
            ModelOutput.from_content("mockllm/model", content="done"),
        ],
        memoize=False,
    )
    error = PermissionError("sentinel denied")
    task = Task(
        dataset=[Sample(input="What is 2 + 3?", target="5")],
        solver=deepagent(subagents=[helper], background=True),
        sentinel=[d3_raising_in_helper(error)],
        message_limit=30,
    )
    log = eval(task, model=parent_model)[0]
    assert log.status == "error"
    assert log.samples
    sample_error = log.samples[0].error
    assert sample_error is not None
    assert sample_error.message == "PermissionError('sentinel denied')"


@scorer(metrics=[])
def adds_with_tools(grouped: bool = False) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        message = ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(
                    id="score_call", function="addition", arguments={"x": 1, "y": 2}
                )
            ],
        )

        async def run_tools() -> None:
            await execute_tools([message], [addition()])

        if grouped:
            async with anyio.create_task_group() as tg:
                tg.start_soon(run_tools)
        else:
            await run_tools()
        return Score(value=1)

    return score


@pytest.mark.parametrize("grouped", [False, True])
def test_sentinel_errors_in_a_scorer_report_the_original_exception(
    grouped: bool,
) -> None:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=generate(),
        scorer=adds_with_tools(grouped),
        sentinel=[d3_raising(PermissionError("sentinel denied"))],
    )
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "error"
    assert log.samples
    sample_error = log.samples[0].error
    assert sample_error is not None
    assert sample_error.message == "PermissionError('sentinel denied')"


@pytest.mark.parametrize("after", [False, True])
def test_a_sentinel_terminate_error_in_a_sub_agent_ends_the_sample(
    after: bool,
) -> None:
    log = run_handoff(
        [d3_raising_in_helper(TerminateSampleError("stop now"), after=after)]
    )
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    assert sample.error is None
    assert sample.limit is not None
    assert sample.limit.type == "operator"
    assert sample.limit.reason == "stop now"


@pytest.mark.parametrize("after", [False, True])
def test_a_sentinel_limit_in_a_sub_agent_stops_the_handoff(after: bool) -> None:
    error = LimitExceededError("working", value=10, limit=5, message="hit")
    log = run_handoff([d3_raising_in_helper(error, after=after)])
    assert log.status == "success", log.error
    assert log.samples
    assert any(
        "helper exceeded its working limit of 5" in message.text
        for message in log.samples[0].messages
    )


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
        sentinel=observe_only([d3_asks_model()]),
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
        observe_only([d3_asks_with(role="judge")]),
        model_roles={"judge": _scoring_model("0.25")},
    )
    assert log.status == "success", log.error
    [event] = sentinel_events(log)
    assert event.suspicion == 0.25
    assert log.samples
    roles = [e.role for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert roles.count("judge") == 1


def test_sentinel_inference_is_not_charged_to_the_sample_limits() -> None:
    expensive = ModelOutput.from_content("mockllm/model", content="0.25")
    expensive.usage = ModelUsage(
        input_tokens=50_000, output_tokens=50_000, total_tokens=100_000
    )
    judge = get_model("mockllm/model", custom_outputs=[expensive], memoize=False)
    log = run(
        observe_only([d3_asks_with(role="judge")]),
        model_roles={"judge": judge},
        token_limit=10_000,
        turn_limit=2,
    )
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    assert sample.limit is None
    [event] = sentinel_events(log)
    assert event.suspicion == 0.25
    assert [m.text for m in sample.messages][-1] == "done"


def monitor_calls(log: EvalLog) -> list[tuple[str, str | None]]:
    assert log.samples
    events = log.samples[0].events
    return [
        (e.model, e.role)
        for e in events
        if isinstance(e, ModelEvent) and e.span_id in sentinel_span_ids(events)
    ]


def test_host_generate_passes_tools_and_tool_choice() -> None:
    log = run(
        observe_only([d3_asks_with_tools()]),
        model_roles={"monitor": _scoring_model("0.25")},
    )
    assert log.status == "success", log.error
    assert log.samples
    events = log.samples[0].events
    [model_event] = [
        e
        for e in events
        if isinstance(e, ModelEvent) and e.span_id in sentinel_span_ids(events)
    ]
    assert [t.name for t in model_event.tools] == ["flag"]
    assert model_event.tool_choice == ToolFunction(name="flag")


def role_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if "sentinel role" in r.getMessage()]


def test_host_generate_with_only_a_model_labels_it_sentinel(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        log = run(
            observe_only([d3_asks_with(model="mockllm/model")]),
            model_roles={"monitor": _scoring_model("0.9")},
        )
    [event] = sentinel_events(log)
    assert event.error is not None
    assert "Default output from mockllm/model" in event.error
    assert monitor_calls(log) == [("mockllm/model", "sentinel")]
    assert not role_warnings(caplog)
    assert "sentinel" in log.stats.role_usage
    assert log.samples
    events = log.samples[0].events
    agent_calls = [
        e
        for e in events
        if isinstance(e, ModelEvent) and e.span_id not in sentinel_span_ids(events)
    ]
    assert agent_calls
    assert all(e.model == "mockllm/model" and e.role is None for e in agent_calls)
    assert get_model("mockllm/model").role is None


def test_host_generate_falls_back_to_the_model_for_an_unconfigured_role(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai._util.logger as logger_module

    monkeypatch.setattr(logger_module, "_warned", [])
    with caplog.at_level(logging.WARNING):
        log = run(observe_only([d3_asks_with(model="mockllm/model", role="judge")]))
    [event] = sentinel_events(log)
    assert event.error is not None
    assert "Default output from mockllm/model" in event.error
    assert monitor_calls(log) == [("mockllm/model", "judge")]
    assert not role_warnings(caplog)


def test_host_generate_prefers_a_configured_role_to_the_model() -> None:
    log = run(
        observe_only([d3_asks_with(model="mockllm/model", role="judge")]),
        model_roles={"judge": _scoring_model("0.25")},
    )
    assert log.status == "success", log.error
    [event] = sentinel_events(log)
    assert event.suspicion == 0.25
    assert monitor_calls(log) == [("mockllm/model", "judge")]


def test_host_generate_rejects_a_model_instance() -> None:
    log = run(observe_only([d3_asks_with(model=cast(str, _scoring_model("0.5")))]))
    [event] = sentinel_events(log)
    assert event.error is not None
    assert "TypeError" in event.error
    assert "not a Model" in event.error
    assert "model_roles" in event.error


@pytest.mark.parametrize("model,role", [("", None), (None, "")])
def test_host_generate_rejects_an_empty_model_or_role(
    model: str | None, role: str | None
) -> None:
    log = run(observe_only([d3_asks_with(model=model, role=role)]))
    [event] = sentinel_events(log)
    assert event.error is not None
    assert "ValueError" in event.error
    assert "not an empty string" in event.error


@pytest.mark.parametrize("given,role", [(None, "monitor"), ("judge", "judge")])
def test_host_generate_warns_once_without_the_role(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    given: str | None,
    role: str,
) -> None:
    import inspect_ai._util.logger as logger_module

    monkeypatch.setattr(logger_module, "_warned", [])
    with caplog.at_level(logging.WARNING):
        log = run(observe_only([d3_asks_with(role=given)]))
    warnings = [
        r.getMessage()
        for r in caplog.records
        if f"sentinel role '{role}'" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert f"--model-role {role}=" in warnings[0]
    assert [r for _, r in monitor_calls(log)] == [role]


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
    with active(observe_only([d3_recording(seen)])), caplog.at_level(logging.WARNING):
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
    from inspect_ai._sentinel._dispatch import _host_context, _Recorder

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
        _Recorder().record(
            replace(_host_context().context, path="p"), "p", step, reported
        )


def test_host_context_outside_a_sample_has_no_eval() -> None:
    from inspect_ai._sentinel._dispatch import _host_context

    assert _host_context().context.eval is None


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
    log = run(observe_only([d3_suspicion()]))
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
        log = run(observe_only([d3_recording(seen)]), turns=3)
    assert log.status == "success", log.error
    assert not [r for r in caplog.records if "sentinel step's input" in r.message]
    assert log.samples
    model_events = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert len(seen) == 3
    for (_, step), event in zip(seen, model_events, strict=False):
        assert [m.id for m in step.input] == [m.id for m in event.input]
    assert len({len(step.input) for _, step in seen}) == 3
