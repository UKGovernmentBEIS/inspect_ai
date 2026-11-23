"""Steps rebuilt from a log (`steps_from_events`) equal the steps live, field by field."""

import base64
import bisect
import dataclasses
import json
import logging
import random
import re
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, cast

import anyio
import pytest
import tenacity
from pydantic import BaseModel, TypeAdapter
from shortuuid import uuid
from test_helpers.utils import collide_murmur3

from inspect_ai import Task, eval
from inspect_ai._sentinel._integration import (
    EvalInfo,
    MalformedLogError,
    steps_from_events,
)
from inspect_ai._sentinel._steps import ListView, PoolView
from inspect_ai._util._async import tg_collect
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import (
    Agent,
    AgentState,
    agent,
    agent_bridge,
    as_solver,
    as_tool,
    handoff,
    react,
    run,
)
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.approval import (
    Approval,
    ApprovalPolicy,
    Approver,
    approver,
    auto_approver,
)
from inspect_ai.approval._approval import ApprovalDecision
from inspect_ai.approval._human import acp as acp_module
from inspect_ai.approval._human import approver as approver_module
from inspect_ai.dataset import Sample
from inspect_ai.event import (
    ApprovalEvent,
    Event,
    ModelEvent,
    SentinelEvent,
    SpanBeginEvent,
    SpanEndEvent,
    StepEvent,
    Timeline,
    TimelineEvent,
    TimelineSpan,
    ToolEvent,
)
from inspect_ai.event._pool import condense_model_event_inputs
from inspect_ai.event._sentinel import SentinelStage
from inspect_ai.log import (
    EvalLog,
    EvalSample,
    condense_events,
    read_eval_log,
    write_eval_log,
)
from inspect_ai.log._transcript import transcript
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    GenerateInput,
    Model,
    ModelAPI,
    ModelOutput,
    ModelRefusalError,
    get_model,
    model_origin,
    modelapi,
)
from inspect_ai.model._call_tools import TOOL_CALLS_FAIL_FAST, execute_tools
from inspect_ai.model._compaction import CompactionEdit
from inspect_ai.model._compaction.edit import TOOL_RESULT_REMOVED
from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.review import Review, Reviewer, ReviewPolicy, reviewer
from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import (
    Tool,
    ToolCall,
    ToolCallContent,
    ToolCallError,
    ToolCallView,
    ToolError,
    ToolInfo,
    ToolResult,
    tool,
)
from inspect_ai.tool._tool import ToolApprovalError, ToolParsingError
from inspect_ai.util import store
from inspect_ai.util._span import (
    current_agent_span_id,
    current_span_id,
    in_span,
    span,
    span_id_provider,
)

from .test_sentinel_bridge import (
    bridge_reject_nth,
    openai_scaffold,
    rejecting_approver,
)
from .test_sentinel_dispatch import (
    _RetriedError,
    _RetryingMockLLM,
    _StartingSink,
    addition,
    addition_call,
    addition_raising_viewer,
    agent_model,
    d3_approver,
    d3_attributes_a_call_to_a_sub_agent,
    d3_edits_a_sent_message_in_place,
    d3_generate_decides,
    d3_generate_raises,
    d3_generates_once,
    d3_memory_path_approver,
    d3_modify,
    d3_public_memory_only,
    d3_reject,
    returns,
)
from .test_sentinel_human import Panel, answered, h_ask

if TYPE_CHECKING:
    from inspect_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        Context,
        Decision,
        Escalations,
        HumanAnswer,
        MonitorGroup,
        Observation,
        Protocol,
        ProtocolGroup,
        ReplayStep,
        monitor,
        protocol,
    )
else:
    from test_helpers.fake_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        Context,
        Decision,
        Escalations,
        HumanAnswer,
        MonitorGroup,
        Observation,
        Protocol,
        ProtocolGroup,
        ReplayStep,
        monitor,
        protocol,
    )

pytestmark = pytest.mark.usefixtures("fake_sentinel")

Step = Any

# what replay cannot give: the untruncated output is not in the log, and a
# tool's viewer, which supplies a view's context, is not either
ABSENT: dict[str, set[str]] = {"AfterToolCall": {"output"}}


@monitor
def r7_probe(seen: dict[str, Step], copies: bool = False) -> MonitorGroup:
    """Record every step it is handed, under a token its observation carries, or with `copies` a copy of its messages as they were then (`as_seen`)."""

    def probe(step: Step) -> Observation:
        token = str(len(seen))
        seen[token] = as_seen(step) if copies else step
        return Observation.score(0.0, token)

    async def before_generate(
        context: Context, step: BeforeGenerate
    ) -> Observation | None:
        return probe(step)

    async def after_generate(
        context: Context, step: AfterGenerate
    ) -> Observation | None:
        return probe(step)

    async def before_call(context: Context, step: BeforeToolCall) -> Observation | None:
        return probe(step)

    async def after_call(context: Context, step: AfterToolCall) -> Observation | None:
        return probe(step)

    return MonitorGroup(before_generate, after_generate, before_call, after_call)


def as_seen(step: Step) -> Step:
    """The step as its monitor saw it: a message the scaffold edits in place afterwards (react's `submit`) keeps what it held then."""

    def copied(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_copy(deep=True)
        if isinstance(value, Sequence) and not isinstance(value, str):
            return [copied(item) for item in value]
        return value

    return dataclasses.replace(
        step,
        **{f.name: copied(getattr(step, f.name)) for f in dataclasses.fields(step)},
    )


def live_steps(
    sample: EvalSample, seen: dict[str, Step]
) -> dict[tuple[str, str], Step]:
    steps: dict[tuple[str, str], Step] = {}
    for event in sample.events:
        if isinstance(event, SentinelEvent) and event.path == "r7_probe":
            assert event.explanation is not None
            key = (event.stage, event.step_id)
            assert key not in steps, f"two live steps at {key}"
            steps[key] = seen[event.explanation]
    return steps


def replayed(log: EvalLog, **kwargs: Any) -> list["ReplayStep"]:
    assert log.location
    [sample] = read_eval_log(log.location, resolve_attachments="full").samples or []
    return steps_from_events(
        sample.messages,
        sample.events,
        [],
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
        **kwargs,
    )


def comparable(value: Any, ids: bool = True) -> Any:
    """A value as data, with message ids left out unless `ids`."""
    if isinstance(value, BaseModel) and hasattr(value, "role"):
        return (
            type(value).__name__,
            value.model_dump(exclude=None if ids else {"id"}),
        )
    if isinstance(value, BaseModel):
        return value.model_dump()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: comparable(getattr(value, f.name), ids)
            for f in dataclasses.fields(value)
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [comparable(item, ids) for item in value]
    if isinstance(value, dict):
        return {key: comparable(item, ids) for key, item in value.items()}
    return value


def assert_replay_equals_live(
    solver: Solver | list[Solver],
    model: Any,
    *,
    sentinel: Sequence[Any] = (),
    differences: Sequence[str] = (),
    sample: Sample | None = None,
    status: str = "success",
    inferred: str | None = None,
    **task_kwargs: Any,
) -> list["ReplayStep"]:
    """Run the eval with a probe watching every stage, rebuild its steps from the log, and compare; then compare those with the steps replayed with the log's origins removed and the turns inferred.

    Args:
        solver: The eval's solver.
        model: Its model.
        sentinel: Instances to run after the probe.
        differences: Fields known to differ, as `"stage.field"`, each a known difference of replay.
        sample: The sample to run.
        status: The status the eval ends with.
        inferred: Why the steps replayed with the turns inferred differ from those replayed with the recorded origins; None where they are equal.
        **task_kwargs: More `Task` arguments.
    """
    seen: dict[str, Step] = {}
    task = Task(
        dataset=[sample or Sample(input="What is 1 + 1?", target="2")],
        solver=solver,
        sentinel=[r7_probe(seen, copies=True), *sentinel],
        **task_kwargs,
    )
    log = eval(task, model=model)[0]
    assert log.status == status, log.error
    return assert_logged_replay_equals_live(log, seen, differences, inferred)


def assert_logged_replay_equals_live(
    log: EvalLog,
    seen: dict[str, Step],
    differences: Sequence[str] = (),
    inferred: str | None = None,
    old_log_differs: bool = False,
) -> list["ReplayStep"]:
    """Rebuild the steps of a log that `r7_probe(seen, copies=True)` watched, and compare; then compare those with the steps replayed with the log's origins removed and the turns inferred (`inferred` as for `assert_replay_equals_live`), and, unless `old_log_differs`, with those replayed from the log without its execution ids."""
    assert log.samples
    live = live_steps(log.samples[0], seen)
    replay = replayed(log)
    rebuilt: dict[tuple[str, str], ReplayStep] = {
        (step.stage, step.id): step for step in replay
    }
    assert len(rebuilt) == len(replay)
    assert set(rebuilt) == set(live)
    for key, step in live.items():
        assert_step_equals_live(key, rebuilt[key], step, differences)
    assert_inferred(log, replay, inferred)
    if not old_log_differs:
        old = replay_events(log, without_execution_ids(logged_sample(log).events))
        assert replay_record(old) == replay_record(replay)
    return replay


def without_execution_ids(events: Sequence[Event]) -> list[Event]:
    """The events as a log written before `execution_id` holds them."""
    return [
        event.model_copy(update={"execution_id": None})
        if isinstance(event, ToolEvent | ApprovalEvent | SentinelEvent)
        else event
        for event in events
    ]


def replay_record(replay: list["ReplayStep"]) -> list[Any]:
    return [
        (s.stage, s.id, s.segment, dict(s.recorded_answers), comparable(s.step))
        for s in replay
    ]


def assert_step_equals_live(
    key: tuple[str, str],
    rebuilt: "ReplayStep",
    step: Step,
    differences: Sequence[str] = (),
) -> None:
    again = rebuilt.step
    assert type(again) is type(step), key
    assert rebuilt.segment[0] == step.conversation
    stage = type(step).__name__
    for f in dataclasses.fields(step):
        if f.name in ABSENT.get(stage, set()):
            continue
        if f"{key[0]}.{f.name}" in differences:
            continue
        ours, theirs = getattr(again, f.name), getattr(step, f.name)
        if f.name == "agent_messages":
            # the log does not record the agent's own messages
            assert ours is None, key
            continue
        if f.name == "view":
            ours, theirs = ours.call, theirs.call
        assert comparable(ours) == comparable(theirs), f"{key} {f.name}"


class Disagreement(NamedTuple):
    """How the steps replayed with turns inferred differ from those replayed with the recorded origins."""

    steps: int
    # (stage, step id) of steps on one side only
    missing: list[tuple[str, str]]
    extra: list[tuple[str, str]]
    # (stage, step id, field) of fields that differ
    fields: list[tuple[str, str, str]]


def without_origins(events: Sequence[Event]) -> list[Event]:
    def stripped(event: Event) -> Event:
        if isinstance(event, ModelEvent):
            return event.model_copy(update={"origin": None})
        if isinstance(event, ToolEvent) and event.events:
            return event.model_copy(
                update={"events": [stripped(e) for e in event.events]}
            )
        return event

    return [stripped(event) for event in events]


def inferred_disagreement(
    log: EvalLog, recorded: Sequence["ReplayStep"]
) -> Disagreement:
    """Replay the log with every `ModelEvent.origin` removed and compare its steps with `recorded`, field by field."""
    sample = logged_sample(log)
    inferred = steps_from_events(
        sample.messages,
        without_origins(sample.events),
        [],
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
    )
    ours = {(s.stage, s.id): s for s in inferred}
    theirs = {(s.stage, s.id): s for s in recorded}
    fields: list[tuple[str, str, str]] = []
    for key in sorted(set(ours) & set(theirs)):
        a, b = ours[key], theirs[key]
        if a.segment != b.segment:
            fields.append((*key, "segment"))
        for f in dataclasses.fields(a.step):
            if comparable(getattr(a.step, f.name)) != comparable(
                getattr(b.step, f.name)
            ):
                fields.append((*key, f.name))
    return Disagreement(
        steps=len(theirs),
        missing=sorted(set(theirs) - set(ours)),
        extra=sorted(set(ours) - set(theirs)),
        fields=fields,
    )


def assert_inferred(
    log: EvalLog, recorded: Sequence["ReplayStep"], differs: str | None
) -> None:
    disagreement = inferred_disagreement(log, recorded)
    agrees = not (disagreement.missing or disagreement.extra or disagreement.fields)
    assert agrees == (differs is None), disagreement


@solver
def folding(turns: int) -> Solver:
    """Rebuild the input each turn: the task, then one user message folding in every earlier turn."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        tools = [addition()]
        folded: list[str] = []
        for _ in range(turns + 1):
            input: list[ChatMessage] = [
                ChatMessageSystem(content="Add numbers."),
                ChatMessageUser(content="\n".join([state.input_text, *folded])),
            ]
            output = await model.generate(input, tools)
            folded.append(f"assistant called {len(output.message.tool_calls or [])}")
            if not output.message.tool_calls:
                break
            result = await execute_tools([*input, output.message], tools)
            folded.extend(f"result {m.text}" for m in result.messages)
        return state

    return solve


@tool(parallel=True)
def ordered_addition() -> Tool:
    finished: dict[int, anyio.Event] = {}

    async def execute(x: int, y: int) -> str:
        """Add two numbers, finishing after the call that adds one more to x.

        Args:
            x: First number to add.
            y: Second number to add.
        """
        done = finished.setdefault(x, anyio.Event())
        if x < 3:
            await finished.setdefault(x + 1, anyio.Event()).wait()
        done.set()
        return str(x + y)

    return execute


def outputs(*outputs: ModelOutput) -> Any:
    return get_model("mockllm/model", custom_outputs=list(outputs), memoize=False)


def call(name: str, **arguments: Any) -> ModelOutput:
    return ModelOutput.for_tool_call(
        "mockllm/model", tool_name=name, tool_arguments=arguments
    )


def done(content: str = "done") -> ModelOutput:
    return ModelOutput.from_content("mockllm/model", content=content)


def test_a_tool_loop_replays_as_it_ran() -> None:
    assert_replay_equals_live(
        [use_tools(addition()), generate()],
        outputs(call("addition", x=1, y=1), call("addition", x=2, y=2), done()),
    )


def calls(*calls: tuple[str, dict[str, Any]], turn: int = 0) -> ModelOutput:
    """One assistant turn making several tool calls, with ids `t{turn}c{index}`."""
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content="",
                    model="mockllm/model",
                    tool_calls=[
                        ToolCall(
                            id=f"t{turn}c{index}",
                            function=function,
                            arguments=arguments,
                        )
                        for index, (function, arguments) in enumerate(calls)
                    ],
                ),
                stop_reason="tool_calls",
            )
        ],
    )


def tool_loop(*tools: Tool) -> list[Solver]:
    return [use_tools(*tools), generate()]


def test_react_with_a_summary_compaction_replays_as_it_ran() -> None:
    from inspect_ai.model._compaction.summary import CompactionSummary

    turns = [call("addition", x=turn, y=turn) for turn in range(6)]
    replay = assert_replay_equals_live(
        as_solver(
            react(
                tools=[addition()],
                compaction=CompactionSummary(threshold=300),
                submit=False,
            )
        ),
        outputs(*turns, *[done("summary")] * 3, *turns, done()),
    )
    assert any(step.segment[1] > 0 for step in replay)


def test_parallel_tool_calls_replay_as_they_ran() -> None:
    assert_replay_equals_live(
        tool_loop(ordered_addition()),
        outputs(
            calls(
                ("ordered_addition", {"x": 1, "y": 10}),
                ("ordered_addition", {"x": 2, "y": 10}),
                ("ordered_addition", {"x": 3, "y": 10}),
            ),
            done(),
        ),
    )


def test_a_messages_tool_steps_share_its_text() -> None:
    from inspect_ai._util.content import ContentText

    turn = calls(
        ("addition", {"x": 1, "y": 1}),
        ("addition", {"x": 2, "y": 2}),
        ("addition", {"x": 3, "y": 3}),
    )
    turn.message.content = [ContentText(text="Adding"), ContentText(text="three.")]
    log = run_logged([use_tools(addition()), generate()], outputs(turn, done()))

    steps = [
        replayed.step
        for replayed in replayed(log)
        if isinstance(replayed.step, BeforeToolCall | AfterToolCall)
    ]
    assert len(steps) == 6
    assert {step.message for step in steps} == {"Adding\nthree."}
    # replay keeps every step, so a copy per call grows with calls x text
    assert len({id(step.message) for step in steps}) == 1


def test_a_truncated_result_replays_as_it_ran() -> None:
    replay = assert_replay_equals_live(
        tool_loop(returns("x" * 100)),
        outputs(call("returns"), done()),
        config=GenerateConfig(max_tool_output=10),
    )
    [after] = [step for step in replay if step.stage == "tool_result"]
    assert isinstance(after.step, AfterToolCall) and after.step.truncated


def test_a_media_result_moved_out_of_the_tool_message_replays_as_it_ran() -> None:
    # mockllm takes no images in tool results, so the model's input holds an
    # edited copy of the tool message under its id
    image = ContentImage(image="data:image/png;base64,iVBORw0KGgo=")
    replay = assert_replay_equals_live(
        tool_loop(returns([ContentText(text="look"), image])),
        outputs(call("returns"), done()),
    )
    [after] = [step for step in replay if step.stage == "tool_result"]
    assert isinstance(after.step, AfterToolCall)
    assert image in after.step.result.content


@solver
def clears_the_result() -> Solver:
    """Run a tool, then clear its result in the conversation under the same id."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        tools = [returns("original result")]
        for turn in range(3):
            if turn == 2:
                [index] = [
                    i
                    for i, message in enumerate(state.messages)
                    if isinstance(message, ChatMessageTool)
                ]
                state.messages[index] = state.messages[index].model_copy(
                    update={"content": "[cleared]"}
                )
            output = await model.generate(state.messages, tools)
            state.messages.append(output.message)
            if output.message.tool_calls:
                messages, _ = await execute_tools(state.messages, tools)
                state.messages.extend(messages)
        return state

    return solve


def test_a_result_cleared_later_replays_as_it_ran() -> None:
    replay = assert_replay_equals_live(
        clears_the_result(), outputs(call("returns"), done(), done())
    )
    [after] = [step for step in replay if step.stage == "tool_result"]
    assert isinstance(after.step, AfterToolCall)
    assert after.step.result.text == "original result"


def helper(model: Any) -> Agent:
    return react(
        name="helper",
        description="A helper agent.",
        tools=[addition()],
        model=model,
        submit=False,
    )


@pytest.mark.parametrize("via_tool", [True, False])
def test_a_sub_agent_replays_as_it_ran(via_tool: bool) -> None:
    sub_agent = helper(outputs(call("addition", x=2, y=3), done("helper done")))
    replay = assert_replay_equals_live(
        tool_loop(as_tool(sub_agent) if via_tool else handoff(sub_agent)),
        outputs(
            call("helper", input="add 2 and 3")
            if via_tool
            else call("transfer_to_helper"),
            done(),
        ),
    )
    assert len({step.step.conversation for step in replay}) == 2


def test_a_retried_refusal_replays_as_it_ran() -> None:
    assert_replay_equals_live(
        as_solver(react(tools=[addition()], retry_refusals=2)),
        outputs(
            ModelOutput.from_content(
                "mockllm/model", "I refuse", stop_reason="content_filter"
            ),
            call("submit", answer="2"),
        ),
    )


def test_a_provider_error_retried_to_success_replays_as_it_ran() -> None:
    _RetryingMockLLM.failures = 1
    replay = assert_replay_equals_live(d3_generates_once(), "d3_retrying/model")
    assert [step.stage for step in replay] == ["model_input", "model_output"]


@solver
def r7_generates_twice_cached() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        for _ in range(2):
            state.output = await model.generate(
                [ChatMessageUser(content="Same question.")], cache=True
            )
        return state

    return solve


def test_a_cache_hit_replays_as_it_ran() -> None:
    replay = assert_replay_equals_live(r7_generates_twice_cached(), "mockllm/model")
    assert len([step for step in replay if step.stage == "model_input"]) == 2


@solver
def r7_runs_a_cached_call() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        tools = [addition()]
        messages: list[ChatMessage] = [ChatMessageUser(content="Same question.")]
        await model.generate(messages, tools=tools, cache=True)
        # the cache hit's call runs
        output = await model.generate(messages, tools=tools, cache=True)
        await execute_tools([*messages, output.message], tools)
        return state

    return solve


def test_a_call_from_a_cache_hit_replays_by_its_call_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a cache hit hands two model calls one output message id, so the call's
    # proposing message is ambiguous: replay finds its producer by its call
    # id and position, as it did before the ids
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    seen: dict[str, Step] = {}
    log = run_logged(
        r7_runs_a_cached_call(),
        outputs(call("addition", x=1, y=1)),
        sentinel=[r7_probe(seen, copies=True)],
    )
    turns = [e for e in logged_sample(log).events if isinstance(e, ModelEvent)]
    assert [e.cache for e in turns] == ["write", "read"]
    assert turns[0].output.message.id == turns[1].output.message.id
    replay = assert_logged_replay_equals_live(log, seen)
    tools = [s.stage for s in replay if s.stage.startswith("tool")]
    assert tools == ["tool_call", "tool_result"]


@pytest.mark.parametrize("report", [False, True])
def test_a_host_call_of_a_log_with_no_sentinel_is_rebuilt_without_a_warning(
    report: bool, caplog: pytest.LogCaptureFixture
) -> None:
    # a host call's tool steps are rebuilt from the conversation: the call as
    # the model wrote it, and its result where the scaffold's next request
    # carried it; with no live sentinel there is nothing to differ from
    log = run_logged(
        as_solver(r7_runs_a_bridged_host_tool(report=report)),
        outputs(call("mcp__host__addition", x=1, y=1), done()),
    )
    events = logged_sample(log).events
    [ran] = [e for e in events if isinstance(e, ToolEvent)]
    [turn, *_] = [e for e in events if isinstance(e, ModelEvent)]
    assert ran.call_message_id is not None
    assert (ran.message_id is not None) == report
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    assert [(s.stage, s.id) for s in replay] == [
        ("model_input", turn.uuid),
        ("model_output", turn.uuid),
        ("tool_call", f"{turn.uuid}/{ran.id}"),
        *(
            [
                ("tool_result", f"{turn.uuid}/{ran.id}"),
                ("model_input", replay[4].id),
                ("model_output", replay[4].id),
            ]
            if report
            else []
        ),
    ]
    assert [called(replay[2])] == turn.output.message.tool_calls
    if report:
        assert resulted(replay[3]).text == "2"
    assert replay_warnings(caplog) == []


def test_a_configured_system_message_replays_as_it_ran() -> None:
    assert_replay_equals_live(
        tool_loop(addition()),
        outputs(call("addition", x=1, y=1), call("addition", x=2, y=2), done()),
        config=GenerateConfig(system_message="Be brief."),
    )


def test_a_scaffold_that_rebuilds_its_input_replays_as_it_ran() -> None:
    assert_replay_equals_live(folding(2), agent_model(2))


def test_an_approvers_modify_replays_as_it_ran() -> None:
    assert_replay_equals_live(
        tool_loop(addition()),
        agent_model(),
        approval=[ApprovalPolicy(d3_approver([], "modify", x=5), "*")],
    )


def test_an_approvers_reject_replays_as_it_ran() -> None:
    replay = assert_replay_equals_live(
        tool_loop(addition()),
        agent_model(),
        approval=[ApprovalPolicy(d3_approver([], "reject"), "*")],
    )
    assert not [step for step in replay if step.stage.startswith("tool")]


def test_a_sentinel_modify_replays_as_it_ran() -> None:
    assert_replay_equals_live(
        tool_loop(addition()), agent_model(), sentinel=[d3_modify()]
    )


def test_a_sentinel_reject_replays_as_it_ran() -> None:
    replay = assert_replay_equals_live(
        tool_loop(addition()), agent_model(), sentinel=[d3_reject()]
    )
    assert [step.stage for step in replay if step.stage.startswith("tool")] == [
        "tool_call"
    ]


def test_an_unparsable_call_replays_as_it_ran() -> None:
    unparsable = call("addition", x=1, y=1)
    tool_calls = unparsable.message.tool_calls
    assert tool_calls
    tool_calls[0].parse_error = "bad json"
    replay = assert_replay_equals_live(
        tool_loop(addition()), outputs(unparsable, done())
    )
    assert not [step for step in replay if step.stage.startswith("tool")]


def test_a_call_that_fails_its_schema_has_no_tool_steps() -> None:
    replay = assert_replay_equals_live(
        tool_loop(addition()), outputs(call("addition", x="one", y=1), done())
    )
    assert not [step for step in replay if step.stage.startswith("tool")]


@solver
def r7_runs_a_prefilled_message() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        message = ChatMessageAssistant(content="", tool_calls=[addition_call("pre")])
        state.messages.append(message)
        result = await execute_tools(state.messages, [addition()])
        state.messages.extend(result.messages)
        state.output = await get_model().generate(state.messages)
        return state

    return solve


def test_a_prefilled_message_run_through_execute_tools_replays_as_it_ran() -> None:
    replay = assert_replay_equals_live(r7_runs_a_prefilled_message(), "mockllm/model")
    [before] = [step for step in replay if step.stage == "tool_call"]
    assert before.step.input is None
    assert before.step.assistant_message is None


def reasoned_calls(turn: int) -> ModelOutput:
    """One assistant turn with reasoning, text and two calls to `addition`, with ids `t{turn}c0` and `t{turn}c1`."""
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=[
                        ContentReasoning(reasoning=f"plan {turn}"),
                        ContentText(text=f"adding {turn}"),
                    ],
                    model="mockllm/model",
                    tool_calls=[
                        ToolCall(
                            id=f"t{turn}c{index}",
                            function="addition",
                            arguments={"x": turn, "y": index},
                        )
                        for index in range(2)
                    ],
                ),
                stop_reason="tool_calls",
            )
        ],
    )


@solver
def r7_own_generate_loop() -> Solver:
    """Call `generate()` and `execute_tools()` in the solver's own loop, outside any agent."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        tools = [addition()]
        while True:
            state.output = await model.generate(state.messages, tools)
            state.messages.append(state.output.message)
            if not state.output.message.tool_calls:
                return state
            result = await execute_tools(state.messages, tools)
            state.messages.extend(result.messages)

    return solve


@pytest.mark.parametrize("loop", ["react", "own_loop"])
@pytest.mark.parametrize("modified_by", [None, "sentinel", "approver"])
def test_tool_steps_carry_the_assistant_message_that_made_the_call(
    loop: str, modified_by: str | None
) -> None:
    seen: dict[str, Step] = {}
    task = Task(
        dataset=[Sample(input="Add.", target="2")],
        solver=(
            as_solver(react(tools=[addition()], submit=False))
            if loop == "react"
            else r7_own_generate_loop()
        ),
        sentinel=[
            r7_probe(seen),
            *([d3_modify()] if modified_by == "sentinel" else []),
        ],
        approval=(
            [ApprovalPolicy(d3_approver([], "modify", x=5), "*")]
            if modified_by == "approver"
            else None
        ),
    )
    model = outputs(reasoned_calls(1), reasoned_calls(2), done())
    log = eval(task, model=model, log_format="json")[0]
    assert log.status == "success", log.error
    assert log.location is not None and log.location.endswith(".json")
    replay = assert_logged_replay_equals_live(log, seen)

    [sample] = read_eval_log(log.location).samples or []
    produced = {
        event.output.message.id: event.output.message
        for event in sample.events
        if isinstance(event, ModelEvent) and event.output.choices
    }
    live = live_steps(sample, seen)
    for steps in (
        {key: step for key, step in live.items() if key[0].startswith("tool")},
        {(r.stage, r.id): r.step for r in replay if r.stage.startswith("tool")},
    ):
        assert len(steps) == 8
        by_turn: dict[str, list[Any]] = {}
        for step in steps.values():
            assert isinstance(step, BeforeToolCall | AfterToolCall)
            message = step.assistant_message
            assert message is not None
            # the turn that made this call, as the model returned it
            turn = step.call.id.split("c")[0][1:]
            assert message.id == step.message_id
            assert comparable(message) == comparable(produced[step.message_id])
            assert [call.id for call in message.tool_calls or []] == [
                f"t{turn}c0",
                f"t{turn}c1",
            ]
            assert message.content[0] == ContentReasoning(reasoning=f"plan {turn}")
            assert message.text == f"adding {turn}"
            proposed = next(c for c in message.tool_calls or [] if c.id == step.call.id)
            assert proposed.arguments == {"x": int(turn), "y": proposed.arguments["y"]}
            if isinstance(step, AfterToolCall) and modified_by is not None:
                # `call` is the call as it ran; the message keeps the proposal
                assert step.call.arguments != proposed.arguments
            by_turn.setdefault(turn, []).append(message)
        # a turn's steps share its message: nothing is copied per step
        assert sorted(by_turn) == ["1", "2"]
        for messages in by_turn.values():
            assert all(message is messages[0] for message in messages)

    if loop == "own_loop":
        assert all(step.agent_messages is None for step in live.values())


@solver
def r7_adds_a_call_to_the_model_s_message() -> Solver:
    """Run each turn from a copy under the model's id with a call of the scaffold's own added."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        tools = [addition()]
        while True:
            state.output = await model.generate(state.messages, tools)
            message = state.output.message
            if not message.tool_calls:
                return state
            added = ToolCall(
                id=f"{message.tool_calls[0].id}-added",
                function="addition",
                arguments={"x": 0, "y": 0},
            )
            state.messages.append(
                message.model_copy(update={"tool_calls": [*message.tool_calls, added]})
            )
            result = await execute_tools(state.messages, tools)
            state.messages.extend(result.messages)

    return solve


def test_a_call_the_scaffold_added_to_the_model_s_message_has_no_assistant_message() -> (
    None
):
    replay = assert_replay_equals_live(
        r7_adds_a_call_to_the_model_s_message(),
        outputs(reasoned_calls(1), done()),
    )
    by_id: dict[str, list[Any]] = {}
    for step in replay:
        if step.stage.startswith("tool"):
            by_id.setdefault(step.id, []).append(step.step)
    assert sorted(by_id) == ["t1c0", "t1c0-added", "t1c1"]
    # the model did not make the added call: no model call produced it
    assert all(
        step.assistant_message is None and step.input is None
        for step in by_id["t1c0-added"]
    )
    assert all(
        step.assistant_message is not None
        for id in ("t1c0", "t1c1")
        for step in by_id[id]
    )


@solver
def r7_runs_a_trimmed_message() -> Solver:
    """Run only the first call of each turn, from a copy of the turn under its id with its text changed and its other calls taken out."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        tools = [addition()]
        while True:
            state.output = await model.generate(state.messages, tools)
            message = state.output.message
            if not message.tool_calls:
                return state
            state.messages.append(
                message.model_copy(
                    update={"content": "trimmed", "tool_calls": message.tool_calls[:1]}
                )
            )
            result = await execute_tools(state.messages, tools)
            state.messages.extend(result.messages)

    return solve


def test_a_tool_step_s_assistant_message_is_the_model_s_not_the_scaffold_s_copy() -> (
    None
):
    seen: dict[str, Step] = {}
    task = Task(
        dataset=[Sample(input="Add.", target="2")],
        solver=r7_runs_a_trimmed_message(),
        sentinel=[r7_probe(seen)],
    )
    log = eval(task, model=outputs(reasoned_calls(1), reasoned_calls(2), done()))[0]
    assert log.status == "success", log.error
    # `message` is a known difference: live it is the text of the copy that
    # ran, in replay the model's
    replay = assert_logged_replay_equals_live(
        log, seen, differences=["tool_call.message", "tool_result.message"]
    )
    steps = [step for step in replay if step.stage.startswith("tool")]
    assert [step.id for step in steps] == ["t1c0", "t1c0", "t2c0", "t2c0"]
    assert log.samples
    live = live_steps(log.samples[0], seen)
    for step in steps:
        assert live[(step.stage, step.id)].message == "trimmed"
        assert isinstance(step.step, BeforeToolCall | AfterToolCall)
        message = step.step.assistant_message
        assert message is not None and message.text == f"adding {step.id[1]}"
        assert len(message.tool_calls or []) == 2


def test_a_log_without_message_ids_replays_its_tool_steps_by_call_id() -> None:
    # a log from before #6143 records no proposing message on its tool events:
    # replay finds each call's producer by its call id and gives the same steps
    seen: dict[str, Step] = {}
    log = run_logged(
        tool_loop(addition()),
        outputs(call("addition", x=1, y=1), call("addition", x=2, y=2), done()),
        sentinel=[r7_probe(seen, copies=True)],
    )
    exact = assert_logged_replay_equals_live(log, seen)
    older = replay_events(log, without_message_ids(logged_sample(log).events))
    assert [(s.stage, s.id) for s in older] == [(s.stage, s.id) for s in exact]
    for ours, theirs in zip(older, exact, strict=True):
        assert comparable(ours.step) == comparable(theirs.step)
    assert [s.stage for s in exact if s.stage.startswith("tool")] == [
        "tool_call",
        "tool_result",
    ] * 2


def test_a_tool_call_s_producer_is_the_model_call_its_event_names() -> None:
    # a later model call in the conversation proposes the same call id with
    # another input: the event's message id names the earlier one, which the
    # latest proposal of the call id would not be
    task = ChatMessageUser(content="Look up one.")
    offered = [ToolInfo(name="lookup", description="Look up an item.")]
    first = linked_call(
        "first",
        None,
        [task],
        "Looking.",
        "agent",
        ToolCall(id="call-1", function="lookup", arguments={"n": 1}),
    )
    first.output.choices[0].message.id = "m1"
    second = linked_call(
        "second",
        None,
        [task, first.output.message, ChatMessageUser(content="Look up two.")],
        "Looking again.",
        "agent",
        ToolCall(id="call-1", function="lookup", arguments={"n": 2}),
    )
    second.output.choices[0].message.id = "m2"
    events: list[Event] = [
        first.model_copy(update={"tools": offered}),
        second.model_copy(update={"tools": offered}),
        SpanBeginEvent(id="tool", name="lookup", type="tool"),
        ToolEvent(
            id="call-1",
            function="lookup",
            arguments={"n": 1},
            result="found",
            call_message_id="m1",
            span_id="tool",
        ),
        SpanEndEvent(id="tool"),
    ]
    replay = steps_from_events(
        [],
        solving(events),
        [],
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version="0.3.300", sentinel=False),
    )
    tools = [s for s in replay if s.stage.startswith("tool")]
    assert [s.stage for s in tools] == ["tool_call", "tool_result"]
    for step in tools:
        assert step.step.input == first.input


@solver
def r7_prefills_a_call_under_a_bridged_id(call_id: str) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        message = ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(id=call_id, function="addition", arguments={"x": 5, "y": 5})
            ],
        )
        state.messages.append(message)
        result = await execute_tools(state.messages, [addition()])
        state.messages.extend(result.messages)
        return state

    return solve


def test_a_prefilled_native_call_under_a_bridged_call_s_id_has_no_producer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # #5765's known limit: a native call run under an id a bridge generation
    # proposed before it was given that generation's input. Its event names
    # the message that holds it, which no model call produced.
    seen: dict[str, Step] = {}
    log = run_logged(
        [
            as_solver(r7_runs_a_bridged_host_tool()),
            r7_prefills_a_call_under_a_bridged_id("shared"),
        ],
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
        ),
        sentinel=[r7_probe(seen, copies=True)],
    )
    native = [
        s
        for s in replayed(log)
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
        and s.step.call.function == "addition"
        and s.step.call.arguments == {"x": 5, "y": 5}
    ]
    assert [(s.stage, s.step.input) for s in native] == [
        ("tool_call", None),
        ("tool_result", None),
    ]
    live = [
        step
        for step in seen.values()
        if isinstance(step, BeforeToolCall | AfterToolCall)
        and step.call.arguments == {"x": 5, "y": 5}
    ]
    assert [step.input for step in live] == [None, None]
    # without the id, the bridge's generation is taken for its producer
    older = [
        s
        for s in replay_events(log, without_message_ids(logged_sample(log).events))
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
        and s.step.call.arguments == {"x": 5, "y": 5}
    ]
    assert [s.step.input is not None for s in older] == [True, True]


def as_imported(events: Sequence[Event]) -> list[Event]:
    """The events as an importer from another framework records them: no origins, no tool events, and no sentinel."""
    checks = {
        e.id for e in events if isinstance(e, SpanBeginEvent) and e.type == "sentinel"
    }
    return [
        e.model_copy(update={"origin": None}) if isinstance(e, ModelEvent) else e
        for e in events
        if not isinstance(e, ToolEvent | SentinelEvent)
        and not (isinstance(e, SpanBeginEvent | SpanEndEvent) and e.id in checks)
        and e.span_id not in checks
    ]


def replay_imported(
    sample: EvalSample, messages: Sequence[ChatMessage] | None = None
) -> list["ReplayStep"]:
    events = as_imported(sample.events)
    [*_, last] = [e for e in events if isinstance(e, ModelEvent)]
    return steps_from_events(
        sample.messages if messages is None else messages,
        events,
        [],
        sample_uuid=sample.uuid or "",
        eval_info=None,
        messages_from=[last.uuid or ""],
    )


def test_an_imported_transcript_joins_its_tool_steps_to_their_turns_by_id() -> None:
    seen: dict[str, Step] = {}
    log = run_logged(
        tool_loop(addition()),
        outputs(call("addition", x=1, y=1), call("addition", x=2, y=2), done()),
        sentinel=[r7_probe(seen, copies=True)],
    )
    sample = logged_sample(log)
    live = live_steps(sample, seen)
    replay = replay_imported(sample)
    assert [(s.stage, s.id) for s in replay] == list(live)
    # each tool step is the turn's that made its call, with its input and
    # tools, from the messages; an import records no truncation, and a
    # message holds no view
    for step in replay:
        assert_step_equals_live(
            (step.stage, step.id),
            step,
            live[(step.stage, step.id)],
            differences=[
                "tool_call.view",
                "tool_result.view",
                "tool_result.truncated",
            ],
        )


def test_an_imported_message_no_turn_made_has_tool_steps_without_input() -> None:
    # an importer that gave its messages other ids than its model calls' (a
    # Scout before #753): no turn made them, so they follow the turns by
    # position, with no input
    log = run_logged(
        tool_loop(addition()),
        outputs(call("addition", x=1, y=1), done()),
    )
    sample = logged_sample(log)
    renamed = [
        m.model_copy(update={"id": f"other-{i}"}) for i, m in enumerate(sample.messages)
    ]
    replay = replay_imported(sample, renamed)
    tools = [s for s in replay if isinstance(s.step, BeforeToolCall | AfterToolCall)]
    assert [(s.stage, s.step.input) for s in tools] == [
        ("tool_call", None),
        ("tool_result", None),
    ]
    assert [s.stage for s in replay] == [
        "model_input",
        "model_output",
        "tool_call",
        "tool_result",
        "model_input",
        "model_output",
    ]


def test_an_imported_call_id_repeated_across_messages_replays_its_first_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # a provider that reuses call ids: two assistant messages each carry call_0
    def turn(n: int) -> list[ChatMessage]:
        return [
            ChatMessageAssistant(
                id=f"assistant-{n}",
                content="",
                tool_calls=[
                    ToolCall(id="call_0", function="addition", arguments={"x": n})
                ],
            ),
            ChatMessageTool(id=f"tool-{n}", content=str(n), tool_call_id="call_0"),
        ]

    messages = [ChatMessageUser(content="add"), *turn(1), *turn(2)]
    with caplog.at_level(logging.WARNING):
        replay = steps_from_events(
            messages, [], [], sample_uuid="s", eval_info=None, messages_from=[]
        )
    assert [(s.stage, s.id) for s in replay] == [
        ("tool_call", "call_0"),
        ("tool_result", "call_0"),
    ]
    before, after = (s.step for s in replay)
    assert isinstance(before, BeforeToolCall) and isinstance(after, AfterToolCall)
    assert [before.message_id, after.message_id] == ["assistant-1", "assistant-1"]
    assert after.result.id == "tool-1"
    assert any("imported call(s) 'call_0'" in r.getMessage() for r in caplog.records)


def test_a_transcript_with_no_header_or_messages_from_is_refused() -> None:
    log = run_logged(tool_loop(addition()), outputs(done()))
    sample = logged_sample(log)
    with pytest.raises(ValueError, match="messages_from"):
        steps_from_events(
            sample.messages,
            as_imported(sample.events),
            [],
            sample_uuid=sample.uuid or "",
            eval_info=None,
        )


@tool
def explodes() -> Tool:
    async def execute() -> str:
        """Fail in a way no tool error describes."""
        raise RuntimeError("boom")

    return execute


def test_a_batch_that_raises_replays_as_it_ran() -> None:
    assert_replay_equals_live(
        tool_loop(explodes()), outputs(call("explodes"), done()), status="error"
    )


@tool(parallel=True)
def explodes_after(event: Any) -> Tool:
    async def execute() -> str:
        """Fail once the other call has finished."""
        await event.wait()
        raise RuntimeError("boom")

    return execute


@tool(parallel=True)
def finishes_first(event: Any) -> Tool:
    async def execute() -> str:
        """Finish, then let the other call fail."""
        event.set()
        return "finished"

    return execute


def test_a_parallel_batch_in_which_one_call_finishes_before_another_raises() -> None:
    event = anyio.Event()
    replay = assert_replay_equals_live(
        tool_loop(finishes_first(event), explodes_after(event)),
        outputs(calls(("finishes_first", {}), ("explodes_after", {})), done()),
        status="error",
    )
    assert ("tool_result", "t0c0") in {(step.stage, step.id) for step in replay}


def test_a_person_s_answer_replays_with_its_decision_and_recorded_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve", "addition is expected here").install(monkeypatch)
    replay = assert_replay_equals_live(
        tool_loop(addition()),
        agent_model(2),
        sentinel=[h_ask("tool_call", ["approve", "reject"])],
    )
    first, second = [step for step in replay if step.stage == "tool_call"]
    assert dict(first.recorded_answers) == {
        "human": HumanAnswer(decision="approve", reason="addition is expected here")
    }
    assert first.step.human_decisions == ()
    assert [d.step_id for d in second.step.human_decisions or []] == [first.id]


@monitor
def r7_abstains_after() -> MonitorGroup:
    async def after_call(context: Context, step: AfterToolCall) -> Observation | None:
        return None

    return MonitorGroup(after_call)


def test_a_person_s_approval_reaches_the_call_s_result_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve").install(monkeypatch)
    replay = assert_replay_equals_live(
        tool_loop(addition()),
        agent_model(),
        sentinel=[h_ask("tool_call", ["approve", "reject"]), r7_abstains_after()],
    )
    [after] = [step for step in replay if step.stage == "tool_result"]
    assert [d.stage for d in after.step.human_decisions or []] == ["tool_call"]


def h_choices(stage: str) -> list[str]:
    # a turn can only proceed or be terminated
    return ["approve", "terminate" if stage == "model_output" else "reject"]


@protocol
def r7_fails_after_the_person(stage: str) -> ProtocolGroup:
    async def tool_call(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        raise PermissionError("sentinel denied")

    async def tool_result(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        raise PermissionError("sentinel denied")

    async def model_output(
        context: Context, step: AfterGenerate, escalations: Escalations
    ) -> Decision | None:
        if not step.output.message.tool_calls:
            return None
        raise PermissionError("sentinel denied")

    stages: dict[str, Protocol] = {
        "tool_call": tool_call,
        "tool_result": tool_result,
        "model_output": model_output,
    }
    return ProtocolGroup(stages[stage])


@solver
def r7_carries_on_after_a_failed_turn() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        try:
            output = await get_model().generate(state.messages, tools=[addition()])
            state.messages.append(output.message)
            result = await execute_tools(state.messages, [addition()])
            state.messages.extend(result.messages)
        except Exception:
            pass
        state.output = await get_model().generate(state.messages, tools=[addition()])
        return state

    return solve


def root_errors(log: EvalLog) -> list[SentinelEvent]:
    return [
        e
        for e in logged_sample(log).events
        if isinstance(e, SentinelEvent) and e.status == "error" and e.path == ""
    ]


@pytest.mark.parametrize("stage", ["tool_call", "tool_result", "model_output"])
def test_a_person_s_answer_reaches_the_conversation_s_next_turn(
    stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    Panel("approve").install(monkeypatch)
    seen: dict[str, Step] = {}
    log = run_logged(
        tool_loop(addition()),
        agent_model(),
        sentinel=[r7_probe(seen, copies=True), h_ask(stage, h_choices(stage))],
    )
    replay = assert_logged_replay_equals_live(log, seen)
    last = [step for step in replay if step.stage == "model_input"][-1]
    assert [d.stage for d in last.step.human_decisions or []] == [stage]
    assert root_errors(log) == []


@pytest.mark.parametrize("stage", ["tool_call", "tool_result", "model_output"])
def test_a_person_s_answer_before_a_sentinel_failure_the_scaffold_caught_is_not_published(
    stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    Panel("approve").install(monkeypatch)
    seen: dict[str, Step] = {}
    log = run_logged(
        r7_carries_on_after_a_failed_turn(),
        agent_model(),
        sentinel=[
            r7_probe(seen, copies=True),
            h_ask(stage, h_choices(stage)),
            r7_fails_after_the_person(stage),
        ],
    )
    [answered] = [
        e
        for e in logged_sample(log).events
        if isinstance(e, SentinelEvent) and e.factory == "inspect_sentinel/human"
    ]
    [failed] = root_errors(log)
    assert (failed.stage, failed.step_id) == (stage, answered.step_id)
    assert failed.kind == "observation"
    assert failed.error == "PermissionError: sentinel denied"
    replay = assert_logged_replay_equals_live(log, seen)
    last = [step for step in replay if step.stage == "model_input"][-1]
    assert last.step.human_decisions == ()


@protocol
def r7_cancelled_by_its_operator(started: list[ToolEvent]) -> Protocol:
    async def check(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        [event] = [e for e in started if e.id == step.call.id]
        event._cancel()
        await anyio.sleep(10)
        return None

    return check


def test_a_person_s_answer_before_an_operator_cancel_is_not_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve").install(monkeypatch)
    # the call's event, which is logged only once its review is done
    started: list[ToolEvent] = []
    set_cancel_fn = ToolEvent._set_cancel_fn

    def capture(event: ToolEvent, cancel_fn: Callable[[], None]) -> None:
        started.append(event)
        set_cancel_fn(event, cancel_fn)

    monkeypatch.setattr(ToolEvent, "_set_cancel_fn", capture)
    seen: dict[str, Step] = {}
    log = run_logged(
        tool_loop(addition()),
        agent_model(),
        sentinel=[
            r7_probe(seen, copies=True),
            h_ask("tool_call", h_choices("tool_call")),
            r7_cancelled_by_its_operator(started),
        ],
    )
    sample = logged_sample(log)
    roots = [e for e in sample.events if isinstance(e, SentinelEvent) and e.path == ""]
    assert [e.status for e in roots] == ["cancelled"]
    # the cancelled call's after-stage step is a known difference (design call
    # 2); what the steps were handed of the person's answer is not
    live = live_steps(sample, seen)
    replay: dict[tuple[str, str], Step] = {
        (step.stage, step.id): step.step for step in replayed(log)
    }
    assert any(stage == "model_input" for stage, _ in live)
    for key, step in live.items():
        ours, theirs = replay[key].human_decisions, step.human_decisions
        assert list(ours or []) == list(theirs or []) == [], key


def test_a_person_s_answer_before_a_failure_that_ends_the_sample_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve").install(monkeypatch)
    replay = assert_replay_equals_live(
        tool_loop(explodes()),
        outputs(call("explodes"), done()),
        sentinel=[h_ask("tool_call", h_choices("tool_call"))],
        status="error",
    )
    assert [s.stage for s in replay][-1] == "tool_call"


def test_a_hook_that_rewrites_the_input_is_a_known_difference() -> None:
    from inspect_ai._util.registry import _registry
    from inspect_ai.hooks import BeforeModelGenerate, Hooks, hooks

    @hooks(name="r7_rewrites_the_input", description="rewrites the first input")
    class RewritesTheInput(Hooks):
        async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
            if data.input and data.input[0].text == "What is 1 + 1?":
                data.input[:] = [ChatMessageUser(content="actually sent")]

    try:
        assert_replay_equals_live(
            tool_loop(addition()),
            agent_model(),
            # known difference (P4-F1): live BeforeGenerate sees the input before
            # the hook; the log has it as sent
            differences=["model_input.input"],
        )
    finally:
        _registry.pop("hooks:r7_rewrites_the_input", None)


def test_a_message_edited_in_place_after_it_was_sent_replays_as_it_ran() -> None:
    assert_replay_equals_live(d3_edits_a_sent_message_in_place(), "mockllm/model")


def memory_call(path: str) -> ModelOutput:
    return call("memory", command="create", path=path, file_text="x")


def test_an_approvers_non_canonical_memory_path_is_refused() -> None:
    """The log cannot show that the built-in memory tool, not a custom tool of its name, resolved the path."""
    from inspect_ai.tool import memory

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=tool_loop(memory()),
        sentinel=[d3_public_memory_only()],
        approval=[
            ApprovalPolicy(
                d3_memory_path_approver("/memories/public/../secret.txt"), "*"
            )
        ],
    )
    log = eval(task, model=outputs(memory_call("/memories/public/note.txt"), done()))[0]
    assert log.status == "success", log.error
    tool_event = next(e for e in logged_sample(log).events if isinstance(e, ToolEvent))
    assert tool_event.arguments["path"] == "/memories/secret.txt"
    with pytest.raises(
        ValueError,
        match=r"approved call does not match the ToolEvent that ran.*Replay this transcript from its messages instead",
    ):
        replayed(log)


def test_an_approvers_canonical_memory_path_replays() -> None:
    from inspect_ai.tool import memory

    replay = assert_replay_equals_live(
        tool_loop(memory()),
        outputs(memory_call("/memories/public/note.txt"), done()),
        sentinel=[d3_public_memory_only()],
        approval=[ApprovalPolicy(d3_memory_path_approver("/memories/secret.txt"), "*")],
    )
    [before] = [step for step in replay if step.stage == "tool_call"]
    assert isinstance(before.step, BeforeToolCall)
    assert before.step.call.arguments["path"] == "/memories/secret.txt"


def test_a_memory_path_replays_canonical_without_approval() -> None:
    from inspect_ai.tool import memory

    replay = assert_replay_equals_live(
        tool_loop(memory()),
        outputs(memory_call("/memories/x/../public/note.txt"), done()),
    )
    canonical = "/memories/public/note.txt"
    assert [
        step.step.call.arguments["path"]
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ] == [canonical, canonical]


@pytest.mark.parametrize("readonly", [False, True], ids=["writable", "readonly"])
def test_an_unmonitored_log_replays_memory_paths_canonical(readonly: bool) -> None:
    from inspect_ai.tool import memory

    if readonly:
        tool = memory(initial_data={"/memories/seed.txt": "seed"}, readonly=True)
        given = [{"command": "view", "path": "/memories/x/../seed.txt"}]
        canonical = [{"command": "view", "path": "/memories/seed.txt"}]
    else:
        tool = memory()
        given = [
            {"command": "create", "path": "/memories/a/../b.txt", "file_text": "x"},
            {
                "command": "rename",
                "old_path": "/memories/a/../b.txt",
                "new_path": "/memories/c/../d.txt",
            },
        ]
        canonical = [
            {"command": "create", "path": "/memories/b.txt", "file_text": "x"},
            {
                "command": "rename",
                "old_path": "/memories/b.txt",
                "new_path": "/memories/d.txt",
            },
        ]
    # no sentinel or approver: the log is written without oversight
    log = run_logged(
        tool_loop(tool), outputs(*(call("memory", **args) for args in given), done())
    )
    replay = replayed(log)
    for stage in (BeforeToolCall, AfterToolCall):
        steps = [step.step for step in replay if isinstance(step.step, stage)]
        assert [step.call.arguments for step in steps] == canonical
    assert all(
        step.step.result.error is None
        for step in replay
        if isinstance(step.step, AfterToolCall)
    )


@tool(name="memory")
def r7_own_memory() -> Tool:
    async def execute(command: str, path: str, file_text: str) -> str:
        """A memory tool of the scaffold's own, with no canonical form for its paths.

        Args:
            command: The command.
            path: The path.
            file_text: The text.
        """
        return "ok"

    return execute


def test_a_custom_memory_tool_replays_its_path_as_given() -> None:
    path = "/memories/x/../public/note.txt"
    replay = assert_replay_equals_live(
        tool_loop(r7_own_memory()), outputs(memory_call(path), done())
    )
    assert [
        step.step.call.arguments["path"]
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ] == [path, path]


def test_an_approvers_path_for_a_custom_memory_tool_replays_as_given() -> None:
    path = "/memories/x/../public/note.txt"
    replay = assert_replay_equals_live(
        tool_loop(r7_own_memory()),
        outputs(memory_call("/memories/public/note.txt"), done()),
        approval=[ApprovalPolicy(d3_memory_path_approver(path), "*")],
    )
    assert [
        step.step.call.arguments["path"]
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ] == [path, path]


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("version", ["0.3.100", "0.3.300", None])
def test_an_older_custom_memory_tools_modified_path_is_refused(
    inputs: str, version: str | None
) -> None:
    """Inspect 0.3.276 recorded the proposed path while the custom tool ran the approver's, which canonicalizes to the proposal."""
    from inspect_ai._sentinel import _replay

    path = Path(__file__).parent / "fixtures" / "custom_memory_modified_0.3.276.json"
    log = read_eval_log(str(path), resolve_attachments="full")
    [sample] = log.samples or []
    approval = next(e for e in sample.events if isinstance(e, ApprovalEvent))
    tool_event = next(e for e in sample.events if isinstance(e, ToolEvent))
    assert approval.modified is not None
    assert approval.modified.arguments == {"path": "/memories/x/../note.txt"}
    assert tool_event.arguments == {"path": "/memories/note.txt"}
    assert tool_event.result == "/memories/x/../note.txt"
    events: list[Event] = list(sample.events)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    with pytest.raises(
        ValueError,
        match=r"approved call does not match the ToolEvent that ran.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            sample.messages,
            events,
            pool,
            sample_uuid=sample.uuid or "sample",
            eval_info=EvalInfo(version, False),
        )


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("version", ["0.3.276", "0.3.300", None])
@pytest.mark.parametrize("decision", ["approve", "modify", "escalate"])
def test_an_older_approval_that_changed_the_call_in_place_is_refused(
    inputs: str, version: str | None, decision: str
) -> None:
    """Inspect 0.3.276 ran the call an approver changed in place, which its ApprovalEvent records and its ToolEvent does not."""
    from inspect_ai._sentinel import _replay

    path = (
        Path(__file__).parent
        / "fixtures"
        / f"approval_changed_in_place_{decision}_0.3.276.json"
    )
    log = read_eval_log(str(path), resolve_attachments="full")
    [sample] = log.samples or []
    approvals = [e for e in sample.events if isinstance(e, ApprovalEvent)]
    tool_event = next(e for e in sample.events if isinstance(e, ToolEvent))
    assert [approval.decision for approval in approvals] == (
        ["escalate", "approve"] if decision == "escalate" else [decision]
    )
    assert all(approval.modified is None for approval in approvals)
    assert approvals[-1].call.arguments == {"path": "/memories/x/../note.txt"}
    assert tool_event.arguments == {"path": "/memories/note.txt"}
    assert tool_event.result == "/memories/x/../note.txt"
    events: list[Event] = list(sample.events)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    with pytest.raises(
        ValueError,
        match=r"approved call does not match the ToolEvent that ran.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            sample.messages,
            events,
            pool,
            sample_uuid=sample.uuid or "sample",
            eval_info=EvalInfo(version, False),
        )


UNVERIFIED_CALL_WARNING = (
    "Skipped the tool steps of call(s) {}: each ended in a parsing or approval "
    "error, and its approved call differs from its ToolEvent, so the log cannot "
    "show whether or with which arguments it ran."
)


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("version", ["0.3.276", "0.3.300", None])
@pytest.mark.parametrize("decision", ["approve", "modify"])
@pytest.mark.parametrize("error", ["parsing", "approval"])
def test_an_older_approved_call_that_raised_a_parsing_or_approval_error_is_skipped_with_warning(
    inputs: str,
    version: str | None,
    decision: str,
    error: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Inspect 0.3.276 ran the approved call, whose tool body raised the error, and its ToolEvent records the proposal."""
    from inspect_ai._sentinel import _replay

    path = (
        Path(__file__).parent
        / "fixtures"
        / f"approval_error_{error}_{decision}_0.3.276.json"
    )
    log = read_eval_log(str(path), resolve_attachments="full")
    [sample] = log.samples or []
    approval = next(e for e in sample.events if isinstance(e, ApprovalEvent))
    tool_event = next(e for e in sample.events if isinstance(e, ToolEvent))
    assert approval.decision == decision
    approved = approval.modified or approval.call
    assert approved.arguments == {"path": "changed"}
    assert tool_event.arguments == {"path": "proposed"}
    assert tool_event.error is not None
    assert tool_event.error.type == error
    assert tool_event.error.message == "body ran with changed"
    events: list[Event] = list(sample.events)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    replay = steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "sample",
        eval_info=EvalInfo(version, False),
    )
    assert not [step for step in replay if step.stage.startswith("tool")]
    assert [r.message for r in caplog.records if "Skipped the tool" in r.message] == [
        UNVERIFIED_CALL_WARNING.format("'c1'")
    ]


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("version", ["0.3.276", "0.3.300", None])
@pytest.mark.parametrize("decision", ["approve", "modify"])
@pytest.mark.parametrize("error", ["parsing", "approval"])
@pytest.mark.parametrize("successful", ["before", "after"])
def test_a_skipped_call_does_not_skip_a_successful_call_sharing_its_id(
    successful: str,
    inputs: str,
    version: str | None,
    decision: str,
    error: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Inspect 0.3.276 runs a successful call before or after a skipped call `c1`, with id `c1` (`same_*` samples) or another id (`distinct_*` samples)."""
    from inspect_ai._sentinel import _replay

    path = (
        Path(__file__).parent
        / "fixtures"
        / f"approval_error_{error}_{decision}_shared_id_0.3.276.json"
    )
    log = read_eval_log(str(path), resolve_attachments="full")
    samples = {sample.id: sample for sample in log.samples or []}

    def replay_tool_steps(ids: str) -> list[tuple[str, dict[str, Any]]]:
        sample = samples[f"{ids}_{successful}"]
        tool_events = [e for e in sample.events if isinstance(e, ToolEvent)]
        other = "c1" if ids == "same" else "c0" if successful == "before" else "c2"
        layout = [(other, successful), ("c1", "proposed")]
        if successful == "after":
            layout.reverse()
        assert [(e.id, e.arguments["path"]) for e in tool_events] == layout
        assert [e.error.type if e.error else None for e in tool_events] == [
            error if path == "proposed" else None for _, path in layout
        ]
        events: list[Event] = list(sample.events)
        pool: list[ChatMessage] = []
        if inputs == "pooled":
            events, pool = _replay._condensed(events, [])
        caplog.clear()
        replay = steps_from_events(
            sample.messages,
            events,
            pool,
            sample_uuid=sample.uuid or "sample",
            eval_info=EvalInfo(version, False),
        )
        assert [
            r.message for r in caplog.records if "Skipped the tool" in r.message
        ] == [UNVERIFIED_CALL_WARNING.format("'c1'")]
        return [
            (step.stage, step.step.call.arguments)
            for step in replay
            if isinstance(step.step, BeforeToolCall | AfterToolCall)
        ]

    expected = [
        ("tool_call", {"path": successful}),
        ("tool_result", {"path": successful}),
    ]
    assert replay_tool_steps("distinct") == expected
    assert replay_tool_steps("same") == expected


@approver
def r7_changes_the_call_and_escalates() -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        call.arguments = {"x": 7, "y": 1}
        return Approval(decision="escalate")

    return approve


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_an_approval_of_a_call_changed_in_place_that_did_not_run_replays(
    inputs: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Current Inspect refuses to run a call an earlier approver changed in place; the log reads the same as a tool body that raised, so the call's steps are skipped with a warning."""
    from inspect_ai._sentinel import _replay
    from inspect_ai.approval import auto_approver

    log = run_logged(
        tool_loop(addition()),
        outputs(call("addition", x=1, y=1), done()),
        approval=[
            ApprovalPolicy(r7_changes_the_call_and_escalates(), "*"),
            ApprovalPolicy(auto_approver(), "*"),
        ],
    )
    sample = logged_sample(log)
    approval = [e for e in sample.events if isinstance(e, ApprovalEvent)][-1]
    tool_event = next(e for e in sample.events if isinstance(e, ToolEvent))
    assert approval.decision == "approve"
    assert approval.call.arguments == {"x": 7, "y": 1}
    assert tool_event.arguments == {"x": 1, "y": 1}
    assert tool_event.error is not None and tool_event.error.type == "approval"
    events: list[Event] = list(sample.events)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    caplog.clear()
    replay = steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "sample",
        eval_info=EvalInfo.from_eval(log.eval),
    )
    assert not [step for step in replay if step.stage.startswith("tool")]
    assert [r.message for r in caplog.records if "Skipped the tool" in r.message] == [
        UNVERIFIED_CALL_WARNING.format(repr(tool_event.id))
    ]


def test_an_approvers_approve_replays_as_it_ran() -> None:
    replay = assert_replay_equals_live(
        tool_loop(addition()),
        agent_model(),
        approval=[ApprovalPolicy(d3_approver([], "approve"), "*")],
    )
    assert [step.stage for step in replay if step.stage.startswith("tool")] == [
        "tool_call",
        "tool_result",
    ]


@monitor
def r7_runs_an_approved_helper_call(call_id: str) -> MonitorGroup:
    async def before_call(context: Context, step: BeforeToolCall) -> Observation | None:
        helper = ToolCall(id=call_id, function="addition", arguments={"x": 9, "y": 1})
        await execute_tools(
            [ChatMessageAssistant(content="", tool_calls=[helper])], [addition()]
        )
        return None

    return MonitorGroup(before_call)


@pytest.mark.parametrize("helper_id", ["shared", "helper"])
def test_a_monitor_s_approved_call_under_the_agent_s_id_replays(
    helper_id: str,
) -> None:
    # after Ransom's 41st review: an approval inside a sentinel span took the
    # agent's call's place
    log = run_logged(
        tool_loop(addition()),
        outputs(
            ModelOutput.for_tool_call(
                "mockllm/model", "addition", {"x": 1, "y": 1}, tool_call_id="shared"
            ),
            done(),
        ),
        approval=[ApprovalPolicy(d3_approver([], "approve"), "*")],
        sentinel=[r7_runs_an_approved_helper_call(helper_id)],
    )
    events = logged_sample(log).events
    approvals = [e for e in events if isinstance(e, ApprovalEvent)]
    ran = [e for e in events if isinstance(e, ToolEvent)]
    assert [(a.call.id, a.call.arguments, a.decision) for a in approvals] == [
        ("shared", {"x": 1, "y": 1}, "approve"),
        (helper_id, {"x": 9, "y": 1}, "approve"),
    ]
    assert [(e.id, e.arguments, e.error) for e in ran] == [
        (helper_id, {"x": 9, "y": 1}, None),
        ("shared", {"x": 1, "y": 1}, None),
    ]
    for inputs in ["expanded", "pooled"]:
        for recorded in [events, without_origins(events)]:
            replay = replay_inputs(log, recorded, inputs)
            assert [
                (s.stage, s.id, s.step.call.arguments)
                for s in replay
                if isinstance(s.step, BeforeToolCall | AfterToolCall)
            ] == [
                ("tool_call", "shared", {"x": 1, "y": 1}),
                ("tool_result", "shared", {"x": 1, "y": 1}),
            ], (inputs, recorded is events)


@agent
def r7_runs_a_bridged_host_tool(
    name: str = "mcp__host__addition",
    approval: list[ApprovalPolicy] | None = None,
    request_before_running: bool = False,
    report: bool = False,
) -> Agent:
    """A scaffold that declares the host tool as `name` (or calls it through Antigravity's `call_mcp_tool` dispatcher) and runs the call the bridge hands it, after one more model request if `request_before_running`.

    With `report`, it then sends the result in its next request, which is when the bridge checks it.
    """

    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )
        from inspect_ai.agent._bridge.sandbox.service import call_tool
        from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge

        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=8080,
            model=None,
            bridged_tools={"host": {"addition": addition()}},
            approval=approval,
        )
        [served] = bridge.served_tools.values()
        # the scaffold declares the tool under its own name, with the
        # description the bridge served
        declared = (
            {
                "name": name,
                "description": "Call a tool on an MCP server.",
                "parameters": {"type": "object"},
            }
            if name == "call_mcp_tool"
            else {
                "name": name,
                "description": served.description,
                "parameters": served.parameters.model_dump(exclude_none=True),
            }
        )
        completion = await inspect_completions_api_request(
            {
                "model": "inspect",
                "messages": [{"role": "user", "content": "What is 1 + 1?"}],
                "tools": [{"type": "function", "function": declared}],
            },
            None,
            bridge,
        )
        [proposed] = completion.choices[0].message.tool_calls or []
        assert proposed.type == "function"
        if request_before_running:
            await inspect_completions_api_request(
                {
                    "model": "inspect",
                    "messages": [
                        {"role": "user", "content": "What is 1 + 1?"},
                        completion.choices[0].message.model_dump(exclude_none=True),
                        {"role": "user", "content": "Go ahead."},
                    ],
                    "tools": [{"type": "function", "function": declared}],
                },
                None,
                bridge,
            )
        arguments = json.loads(proposed.function.arguments)
        if name == "call_mcp_tool":
            arguments = arguments["Arguments"]
        result = await call_tool(bridge)("host", "addition", arguments)
        if report:
            await inspect_completions_api_request(
                {
                    "model": "inspect",
                    "messages": [
                        {"role": "user", "content": "What is 1 + 1?"},
                        completion.choices[0].message.model_dump(exclude_none=True),
                        {
                            "role": "tool",
                            "tool_call_id": proposed.id,
                            "content": str(result),
                        },
                    ],
                    "tools": [{"type": "function", "function": declared}],
                },
                None,
                bridge,
            )
        return state

    return execute


HOST_DIFFERENCES = [
    "tool_call.call",
    "tool_call.view",
    "tool_result.call",
    "tool_result.view",
]
"""Where a host call's rebuilt steps differ from live: replay shows the call as the model wrote it, under the name the scaffold declared the tool by (`mcp__host__addition`), and live the call as the host tool it runs (`addition`)."""


def test_a_bridged_host_tool_call_s_steps_equal_live(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, Step] = {}
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log = run_logged(
            as_solver(r7_runs_a_bridged_host_tool(report=True)),
            outputs(call("mcp__host__addition", x=1, y=1), done()),
            sentinel=[r7_probe(seen, copies=True)],
        )
    events = logged_sample(log).events
    [turn, _] = [e for e in events if isinstance(e, ModelEvent)]
    [ran] = [e for e in events if isinstance(e, ToolEvent)]
    # the host tool ran the model's call, as a native call would
    assert ran.metadata is not None and "bridge" in ran.metadata
    assert [c.id for c in turn.output.message.tool_calls or []] == [ran.id]
    assert ran.error is None
    # live checked the call in the bridge, and its result when the scaffold's
    # next request carried it
    live = [e.stage for e in events if isinstance(e, SentinelEvent)]
    assert live == [
        "model_input",
        "model_output",
        "tool_call",
        "tool_result",
        "model_input",
        "model_output",
    ]
    # replay shows the call as the model wrote it, under the scaffold's name
    # for the host tool, where live showed the host tool's; the rest equals live
    replay = assert_replay_rebuilds_bridge_steps(
        log, seen, bridge_differences=HOST_DIFFERENCES
    )
    [call_step, result_step] = bridged_steps(log, replay)
    assert [called(call_step)] == turn.output.message.tool_calls
    assert called(result_step) == called(call_step)
    assert called(call_step).function == "mcp__host__addition"
    assert ran.function == "addition"
    assert resulted(result_step).text == "2"
    assert replay_warnings(caplog) == []


# A bridged scaffold's own tools (as Claude Code runs its own): replay shows
# each call as the model wrote it, and each result as the model next received
# it.


def read(path: str, id: str) -> ToolCall:
    return ToolCall(id=id, function="read_file", arguments={"path": path})


@agent(name="anthropic_scaffold")
def anthropic_scaffold() -> Agent:
    """A Claude Code-style tool loop over the Anthropic client: it runs `Read` and `Bash` itself, and sends each result as a `tool_result` block."""

    async def execute(state: AgentState) -> AgentState:
        from anthropic import AsyncAnthropic

        tools: list[Any] = [
            {
                "name": name,
                "description": f"The {name} tool.",
                "input_schema": {
                    "type": "object",
                    "properties": {argument: {"type": "string"}},
                },
            }
            for name, argument in [("Read", "file_path"), ("Bash", "command")]
        ]
        async with agent_bridge(state) as bridge:
            messages: list[Any] = [{"role": "user", "content": "What is 1 + 1?"}]
            async with AsyncAnthropic(api_key="sk-test") as client:
                for _ in range(3):
                    response = await client.messages.create(
                        model="inspect", max_tokens=1024, messages=messages, tools=tools
                    )
                    messages.append(
                        {
                            "role": "assistant",
                            "content": [
                                block.model_dump(exclude_none=True)
                                for block in response.content
                            ],
                        }
                    )
                    uses = [b for b in response.content if b.type == "tool_use"]
                    if not uses:
                        break
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": use.id,
                                    "content": f"{use.name} output",
                                }
                                for use in uses
                            ],
                        }
                    )
            return bridge.state

    return execute


def scaffold_log(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    *turns: ModelOutput,
    scaffold: Agent | None = None,
    sentinel: Sequence[Any] | None = (),
    **task_kwargs: Any,
) -> tuple[EvalLog, dict[str, Step]]:
    """Run `scaffold` (`openai_scaffold()` by default) on the `turns` under `backend`, with a probe watching every stage and then the instances `sentinel`, or no sentinel where it is None."""
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    if sentinel is not None:
        task_kwargs["sentinel"] = [r7_probe(seen, copies=True), *sentinel]
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(scaffold or openai_scaffold()),
        **task_kwargs,
    )
    log = eval(task, model=outputs(*turns, done()))[0]
    assert log.status == "success", log.error
    return log, seen


def assert_bridged_steps_follow_the_conversation(
    log: EvalLog, replay: Sequence["ReplayStep"]
) -> list["ReplayStep"]:
    """Assert each of a bridge's rebuilt tool steps shows its call as its model call's output has it, under the id the agent received it under (`agent_tool_call_ids`, else the model's), with that model call's input and output message as the agent received it (`assistant_message`, one object for the model call's steps, holding the step's call, with the step's `message_id`), and its result as the first later bridged request that carries the call's id has it; return those steps."""
    events = logged_sample(log).events
    turns = [
        (index, e)
        for index, e in enumerate(events)
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    rebuilt = bridged_steps(log, replay)
    shared: dict[str, ChatMessageAssistant] = {}
    for step in rebuilt:
        made_by, _, call_id = step.id.partition("/")
        [(at, turn)] = [(i, e) for i, e in turns if e.uuid == made_by]
        calls = turn.output.message.tool_calls or []
        ids = turn.agent_tool_call_ids or [c.id for c in calls]
        [proposed] = [replace(c, id=id) for c, id in zip(calls, ids) if id == call_id]
        assert called(step) == proposed
        assert comparable(step.step.input) == comparable(turn.input)
        message = tool_step(step).assistant_message
        assert message is not None
        assert [c.id for c in message.tool_calls or []] == ids
        # the agent's message differs from the model's only in its call ids,
        # their Google reasoning anchors, and, where they differ, its own
        # message id
        ids_left_out = {"id": None, "tool_calls": None, "content": None}
        assert comparable(message.model_copy(update=ids_left_out)) == comparable(
            turn.output.message.model_copy(update=ids_left_out)
        )
        assert message.text == turn.output.message.text
        assert [replace(c, id="") for c in message.tool_calls or []] == [
            replace(c, id="") for c in calls
        ]
        assert (message.id == turn.output.message.id) == (
            turn.agent_tool_call_ids is None
        )
        assert message.id == tool_step(step).message_id
        assert proposed in (message.tool_calls or [])
        assert message is shared.setdefault(made_by, message)
        if step.stage == "tool_result":
            received = next(
                m
                for i, e in turns
                if i > at
                for m in e.input
                if isinstance(m, ChatMessageTool) and m.tool_call_id == call_id
            )
            assert comparable(resulted(step)) == comparable(received)
    return rebuilt


@pytest.mark.parametrize("client", ["openai", "anthropic"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_scaffold_s_own_tool_calls_steps_equal_live(
    client: str,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # two calls in one response, then one more
    if client == "openai":
        turns = [
            r7_tool_calls(read("a.txt", "read_1"), read("b.txt", "read_2")),
            r7_tool_calls(read("c.txt", "read_3")),
        ]
    else:
        turns = [
            r7_tool_calls(
                ToolCall(id="toolu_1", function="Read", arguments={"file_path": "a"}),
                ToolCall(id="toolu_2", function="Bash", arguments={"command": "ls"}),
            ),
            r7_tool_calls(
                ToolCall(id="toolu_3", function="Bash", arguments={"command": "pwd"})
            ),
        ]
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log, seen = scaffold_log(
            backend,
            monkeypatch,
            *turns,
            scaffold=anthropic_scaffold() if client == "anthropic" else None,
        )
        # the scaffold ran its calls itself: the log records no ToolEvent
        assert not any(isinstance(e, ToolEvent) for e in logged_sample(log).events)
        replay = assert_replay_rebuilds_bridge_steps(log, seen)
    rebuilt = assert_bridged_steps_follow_the_conversation(log, replay)
    ids = [c.id for turn in turns for c in turn.message.tool_calls or []]
    assert in_order(
        [("bridge", s.stage, s.id.split("/")[1]) for s in rebuilt]
    ) == in_order(
        [
            ("bridge", stage, id)
            for stage, id in [
                ("tool_call", ids[0]),
                ("tool_call", ids[1]),
                ("tool_result", ids[0]),
                ("tool_result", ids[1]),
                ("tool_call", ids[2]),
                ("tool_result", ids[2]),
            ]
        ]
    )
    assert replay_warnings(caplog) == []


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_bridged_call_under_a_reused_id_carries_the_message_the_agent_received(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the model reuses read_1 for another call: the bridge hands it over under
    # a fresh id and records it. Replay shows the call under that id, with
    # its own result and the message the bridge handed over, as live does.
    # The first call's result under read_1 has no step: two calls were
    # proposed under read_1, and the log doesn't show which one a result
    # under it answers
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log, seen = scaffold_log(
            backend,
            monkeypatch,
            r7_tool_calls(read("a.txt", "read_1")),
            r7_tool_calls(read("b.txt", "read_1")),
        )
        replay = replayed(log)
    rebuilt = assert_bridged_steps_follow_the_conversation(log, replay)
    live = [s for s in seen.values() if isinstance(s, BeforeToolCall | AfterToolCall)]
    fresh = live[2].call.id
    assert fresh != "read_1"
    assert [(s.stage, s.id.split("/")[1]) for s in rebuilt] == [
        ("tool_call", "read_1"),
        ("tool_call", fresh),
        ("tool_result", fresh),
    ]
    assert isinstance(live[1], AfterToolCall) and live[1].call.id == "read_1"
    paired = [live[0], live[2], live[3]]
    assert [(type(s).__name__, s.call) for s in paired] == [
        (type(s.step).__name__, called(s)) for s in rebuilt
    ]
    assert [comparable(s.result) for s in paired if isinstance(s, AfterToolCall)] == [
        comparable(resulted(s)) for s in rebuilt if s.stage == "tool_result"
    ]
    # each step carries the message live's does: for the second call, the
    # message the bridge handed over, with the fresh call id and its own
    # message id
    handed = live[2].assistant_message
    assert handed is not None and handed.id == live[2].message_id
    assert [c.id for c in handed.tool_calls or []] == [fresh]
    for step, check in zip(rebuilt, paired):
        written = tool_step(step).assistant_message
        assert written is not None and check.assistant_message is not None
        assert written.id == check.assistant_message.id
        assert tool_step(step).message_id == check.message_id
        assert comparable(written) == comparable(check.assistant_message)
    model_message = next(
        e.output.message
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.agent_tool_call_ids == [fresh]
    )
    assert handed.id != model_message.id
    assert replay_warnings(caplog) == []


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_bridged_log_with_no_sentinel_replays_without_a_warning(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    turns = [
        r7_tool_calls(read("a.txt", "read_1"), read("b.txt", "read_2")),
        r7_tool_calls(read("c.txt", "read_3")),
    ]
    log, _ = scaffold_log(backend, monkeypatch, *turns, sentinel=None)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    rebuilt = assert_bridged_steps_follow_the_conversation(log, replay)
    assert [(s.stage, s.id.split("/")[1]) for s in rebuilt] == [
        ("tool_call", "read_1"),
        ("tool_call", "read_2"),
        ("tool_result", "read_1"),
        ("tool_result", "read_2"),
        ("tool_call", "read_3"),
        ("tool_result", "read_3"),
    ]
    assert replay_warnings(caplog) == []


@agent(name="resending_scaffold")
def resending_scaffold() -> Agent:
    """An OpenAI-client tool loop that sends its first request twice and uses the second response, then answers each turn's calls with `t<turn>:<call id>`."""

    async def execute(state: AgentState) -> AgentState:
        from openai import AsyncOpenAI

        tools: list[Any] = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            }
        ]
        async with agent_bridge(state) as bridge:
            messages: list[Any] = [{"role": "user", "content": "What is 1 + 1?"}]
            async with AsyncOpenAI(api_key="sk-test") as client:
                await client.chat.completions.create(
                    model="inspect", messages=messages, tools=tools
                )
                for turn in range(4):
                    completion = await client.chat.completions.create(
                        model="inspect", messages=messages, tools=tools
                    )
                    message = completion.choices[0].message
                    messages.append(message.model_dump(exclude_none=True))
                    if not message.tool_calls:
                        break
                    for call in message.tool_calls:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": f"t{turn}:{call.id}",
                            }
                        )
            return bridge.state

    return execute


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_bridged_calls_under_an_id_proposed_again_get_no_result(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the first two model calls answer one request (the agent uses the
    # second's), and the model reuses the call id for the same call over the
    # next two turns
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log, _ = scaffold_log(
            backend,
            monkeypatch,
            *[r7_tool_calls(read("a.txt", "read_1"))] * 4,
            scaffold=resending_scaffold(),
        )
        replay = replayed(log)
    events = logged_sample(log).events
    made = [
        e.uuid
        for e in events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    assert len(made) == 5
    # the conversation proposed four calls under read_1, so none has a result
    rebuilt = bridged_steps(log, replay)
    assert [
        (s.stage, made.index(s.id.split("/")[0]), s.id.split("/")[1]) for s in rebuilt
    ] == [
        ("tool_call", 0, "read_1"),
        ("tool_call", 1, "read_1"),
        ("tool_call", 2, "read_1"),
        ("tool_call", 3, "read_1"),
    ]
    assert replay_warnings(caplog) == []


@agent(name="retrying_scaffold")
def retrying_scaffold(
    client: str,
    retry: bool = True,
    compaction: CompactionStrategy | None = None,
    padding: str = "",
    side: Literal["agent", "helper"] | None = None,
    turns: int = 10,
    nudge: bool = False,
) -> Agent:
    """A tool loop over the OpenAI or the Anthropic client, bridged with `compaction`, that loses its first response to each request and sends the request again (unless not `retry`), as a client does after a timeout or a dropped connection; it answers each call with `t<turn>:<call id>` and `padding`, until a response has none or it has sent `turns` requests.

    With `side`, it sends a request with its own history and no tools before each of those requests, as Claude Code's permission classifier or opencode's title request does: from the agent, or under `model_origin("helper")`. With `nudge`, it follows each turn's results with the same reminder, as a scaffold nudges the model to keep working.
    """

    async def execute(state: AgentState) -> AgentState:
        from anthropic import AsyncAnthropic
        from openai import AsyncOpenAI

        title: list[Any] = [{"role": "user", "content": "Name this conversation."}]
        reminder = "Continue working until the task is complete."

        async def side_request(create: Callable[[], Awaitable[object]]) -> None:
            if side == "helper":
                with model_origin("helper"):
                    await create()
            elif side is not None:
                await create()

        async with agent_bridge(state, compaction=compaction) as bridge:
            messages: list[Any] = [{"role": "user", "content": "What is 1 + 1?"}]
            if client == "openai":
                tools: list[Any] = [
                    {
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "description": "Read a file.",
                            "parameters": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                            },
                        },
                    }
                ]
                async with AsyncOpenAI(api_key="sk-test") as openai:

                    async def openai_title() -> object:
                        return await openai.chat.completions.create(
                            model="inspect", messages=title
                        )

                    for turn in range(turns):
                        if retry:
                            await side_request(openai_title)
                            await openai.chat.completions.create(
                                model="inspect", messages=messages, tools=tools
                            )
                        await side_request(openai_title)
                        completion = await openai.chat.completions.create(
                            model="inspect", messages=messages, tools=tools
                        )
                        message = completion.choices[0].message
                        messages.append(message.model_dump(exclude_none=True))
                        if not message.tool_calls:
                            break
                        for call in message.tool_calls:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call.id,
                                    "content": f"t{turn}:{call.id}{padding}",
                                }
                            )
                        if nudge:
                            messages.append({"role": "user", "content": reminder})
            else:
                tools = [
                    {
                        "name": "read_file",
                        "description": "Read a file.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    }
                ]
                async with AsyncAnthropic(api_key="sk-test") as anthropic:

                    async def anthropic_title() -> object:
                        return await anthropic.messages.create(
                            model="inspect", max_tokens=1024, messages=title
                        )

                    for turn in range(turns):
                        if retry:
                            await side_request(anthropic_title)
                            await anthropic.messages.create(
                                model="inspect",
                                max_tokens=1024,
                                messages=messages,
                                tools=tools,
                            )
                        await side_request(anthropic_title)
                        response = await anthropic.messages.create(
                            model="inspect",
                            max_tokens=1024,
                            messages=messages,
                            tools=tools,
                        )
                        messages.append(
                            {
                                "role": "assistant",
                                "content": [
                                    block.model_dump(exclude_none=True)
                                    for block in response.content
                                ],
                            }
                        )
                        uses = [b for b in response.content if b.type == "tool_use"]
                        if not uses:
                            break
                        messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": use.id,
                                        "content": f"t{turn}:{use.id}{padding}",
                                    }
                                    for use in uses
                                ]
                                + (
                                    [{"type": "text", "text": reminder}]
                                    if nudge
                                    else []
                                ),
                            }
                        )
            return bridge.state

    return execute


def generated_ids(prefix: str | None, *turns: ModelOutput) -> Any:
    """A mock model answering with `turns` in order, giving each call a new id, as a provider generates one per response (unless `prefix` is None, keeping the turns' ids); it answers a request without tools with a title."""
    ids = iter(range(1, 100))
    remaining = iter(turns)

    def generate(_: Any, tools: list[ToolInfo], *__: Any) -> ModelOutput:
        if not tools:
            return done("A title")
        output = next(remaining).model_copy(deep=True)
        for call in output.message.tool_calls or []:
            if prefix is not None:
                call.id = f"{prefix}{next(ids)}"
        return output

    return get_model("mockllm/model", custom_outputs=generate, memoize=False)


@pytest.mark.parametrize("side", [None, "agent", "helper"])
@pytest.mark.parametrize("client", ["openai", "anthropic"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_cached_retry_s_call_gets_no_result(
    side: Literal["agent", "helper"] | None,
    client: str,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the agent loses each response and sends its request again: the model
    # cache answers the retry with the lost response, under the same call ids;
    # with `side`, a request with its own history comes before each request.
    # Each id is proposed twice, so its calls have no result step; live checked
    # the two results the agent sent
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    prefix = "call_" if client == "openai" else "toolu_"
    seen: dict[str, Step] = {}
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(retrying_scaffold(client, side=side)),
        sentinel=[r7_probe(seen, copies=True)],
        config=GenerateConfig(cache=True),
    )
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        [log] = eval(
            task,
            model=generated_ids(
                prefix,
                r7_tool_calls(read("a.txt", "")),
                r7_tool_calls(read("b.txt", "")),
                done(),
            ),
        )
        assert log.status == "success", log.error
        assert_replay_rebuilds_bridge_steps(log, seen, unbuilt=2)
    assert replay_warnings(caplog) == []
    events = logged_sample(log).events
    made = [
        e for e in events if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    sides = [e for e in made if not e.tools]
    assert [e.origin for e in sides] == ([side] * 6 if side is not None else [])
    made = [e for e in made if e.tools]
    assert [e.cache for e in made] == ["write", "read"] * 3
    assert [[c.id for c in e.output.message.tool_calls or []] for e in made] == [
        [f"{prefix}1"],
        [f"{prefix}1"],
        [f"{prefix}2"],
        [f"{prefix}2"],
        [],
        [],
    ]
    uuids = [e.uuid for e in made]
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_inputs(log, inputs)
        rebuilt = bridged_steps(log, replay)
        assert [
            (s.stage, uuids.index(s.id.split("/")[0]), s.id.split("/")[1])
            for s in rebuilt
        ] == [
            ("tool_call", 0, f"{prefix}1"),
            ("tool_call", 1, f"{prefix}1"),
            ("tool_call", 2, f"{prefix}2"),
            ("tool_call", 3, f"{prefix}2"),
        ], inputs
        assert replay_warnings(caplog) == []


@pytest.mark.parametrize("nudge", [False, True], ids=["plain", "nudged"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_side_requests_keep_finding_bridged_results_linear(
    backend: str, nudge: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    # after Ransom's review of #6624: a request with its own history before
    # each turn, as Claude Code's permission classifier sends, is the request
    # the next turn's results are found against, which made replay read the
    # agent's whole history again at each turn. `nudged` follows each turn's
    # results with the same reminder under a new message id, which kept the
    # lookup reading the history in 391c4072a
    from inspect_ai._sentinel._steps import PoolView

    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    reads = 0
    row, getitem = PoolView.row, PoolView.__getitem__

    def counting_row(self: PoolView, position: int) -> int:
        nonlocal reads
        reads += 1
        return row(self, position)

    def counting_getitem(self: PoolView, index: Any) -> Any:
        nonlocal reads
        reads += 1
        return getitem(self, index)

    work: list[int] = []
    for turns in (20, 40):
        task = Task(
            dataset=[Sample(input="What is 1 + 1?", target="2")],
            solver=as_solver(
                retrying_scaffold(
                    "anthropic",
                    retry=False,
                    side="helper",
                    turns=turns + 1,
                    nudge=nudge,
                )
            ),
        )
        calls = [r7_tool_calls(read(f"{n}.txt", "")) for n in range(turns)]
        [log] = eval(task, model=generated_ids("toolu_", *calls, done()))
        assert log.status == "success", log.error
        for inputs in ["expanded", "pooled"]:
            reads = 0
            with monkeypatch.context() as patch:
                patch.setattr(PoolView, "row", counting_row)
                patch.setattr(PoolView, "__getitem__", counting_getitem)
                replay = replayed_inputs(log, inputs)
            results = [
                s for s in bridged_steps(log, replay) if s.stage == "tool_result"
            ]
            assert len(results) == turns, inputs
            work.append(reads)
    assert work[2] <= 2.2 * work[0] and work[3] <= 2.2 * work[1], work


@agent
def classified_batch_scaffold(
    shown: Literal["own", "latest", "history"] = "own",
) -> Agent:
    """A bridged OpenAI client loop that runs the calls of one response one at a time, sending a request before each call, as Claude Code's permission classifier does in auto mode, and then the results.

    The request before each call has its own one-message history (`own`), or also the proposing response and the latest result (`latest`), or the agent's messages so far (`history`).
    """

    async def execute(state: AgentState) -> AgentState:
        from openai import AsyncOpenAI

        tools: list[Any] = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            }
        ]
        async with agent_bridge(state) as bridge:
            async with AsyncOpenAI(api_key="sk-test") as client:
                messages: list[Any] = [{"role": "user", "content": "Read the files."}]
                completion = await client.chat.completions.create(
                    model="inspect", messages=messages, tools=tools
                )
                message = completion.choices[0].message
                messages.append(message.model_dump(exclude_none=True))
                for call in message.tool_calls or []:
                    question = f"Is call {call.id} safe to run?"
                    asked: list[Any] = [{"role": "user", "content": question}]
                    if shown == "history":
                        asked = [*messages, *asked]
                    elif shown == "latest" and len(messages) > 2:
                        asked = [messages[1], messages[-1], *asked]
                    with model_origin("helper"):
                        await client.chat.completions.create(
                            model="inspect", messages=asked
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": f"result:{call.id}",
                        }
                    )
                await client.chat.completions.create(
                    model="inspect", messages=messages, tools=tools
                )
            return bridge.state

    return execute


@pytest.mark.parametrize("shown", ["own", "latest", "history"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_classifier_request_per_parallel_call_keeps_finding_results_linear(
    backend: str,
    shown: Literal["own", "latest", "history"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # after the pre-push review of 95a93d974: a response proposes many calls
    # and a request comes before each one runs; each of those requests looked
    # up every awaiting call id, so replay was quadratic in the calls of one
    # response. Counts each id looked up, each scan of an input's tool rows
    # and each tool row that scan reads
    from inspect_ai._sentinel import _replay

    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    last_held = _replay._PooledInput.last_held
    held_from = _replay._PooledInput.held_from
    attempts = 0

    def counting(self: Any, *args: Any) -> int | None:
        nonlocal attempts
        attempts += 1
        return last_held(self, *args)

    def counting_held(self: Any, *args: Any) -> list[tuple[int, int, int]] | None:
        nonlocal attempts
        held = held_from(self, *args)
        attempts += 1 + sum(end - first for _, first, end in held or [])
        return held

    work: list[int] = []
    for calls in (20, 40):
        task = Task(
            dataset=[Sample(input="Read the files.")],
            solver=as_solver(classified_batch_scaffold(shown)),
        )
        output = r7_tool_calls(*(read(f"{n}.py", f"call_{n}") for n in range(calls)))
        [log] = eval(task, model=generated_ids(None, output, done()))
        assert log.status == "success", log.error
        for inputs in ["expanded", "pooled"]:
            attempts = 0
            with monkeypatch.context() as patch:
                patch.setattr(_replay._PooledInput, "last_held", counting)
                patch.setattr(_replay._PooledInput, "held_from", counting_held)
                replay = replayed_inputs(log, inputs)
            results = [
                s for s in bridged_steps(log, replay) if s.stage == "tool_result"
            ]
            assert [(s.id.partition("/")[2], resulted(s).text) for s in results] == [
                (f"call_{n}", f"result:call_{n}") for n in range(calls)
            ], inputs
            work.append(attempts)
    assert work[2] <= 2.2 * work[0] and work[3] <= 2.2 * work[1], work


@pytest.mark.parametrize("side", ["agent", "helper"])
@pytest.mark.parametrize("client", ["openai", "anthropic"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_side_request_before_a_retry_of_a_reused_id_gives_the_lost_call_no_result(
    side: Literal["agent", "helper"],
    client: str,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the model reuses the call id for the same call, the agent loses each
    # response and sends its request again, and a request with its own
    # history comes between. The previous turn's result looks new against the
    # side request, but the id was proposed more than once, so no call under
    # it takes a result
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(retrying_scaffold(client, side=side)),
        config=GenerateConfig(cache=True),
    )
    [log] = eval(
        task,
        model=generated_ids(
            None, *[r7_tool_calls(read("a.txt", "read_1"))] * 3, done()
        ),
    )
    assert log.status == "success", log.error
    events = logged_sample(log).events
    made = [
        e for e in events if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    assert [(e.origin, bool(e.tools)) for e in made] == [
        (side, False),
        ("agent", True),
    ] * 8
    assert [e.cache for e in made if e.tools] == ["write", "read"] * 4
    uuids = [e.uuid for e in made]
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_inputs(log, inputs)
        results = [
            (uuids.index(s.id.split("/")[0]), resulted(s).text)
            for s in bridged_steps(log, replay)
            if s.stage == "tool_result"
        ]
        assert results == [], inputs
        assert replay_warnings(caplog) == []


@agent(name="gemini_scaffold")
def gemini_scaffold(
    retry: bool = False,
    side: bool = False,
    gemini_cli: bool = False,
    loop_check: int | None = None,
    compaction: CompactionStrategy | None = None,
    padding: str = "",
    turns: int = 10,
) -> Agent:
    """A Gemini CLI-style tool loop over the Google client, bridged with `compaction`: it keeps each response's content as history and answers each call with a `functionResponse` carrying the call's id, `t<turn>:<index>` and `padding`, until a response has no calls or it has had `turns` responses.

    With `retry`, it loses its first response to each request and sends the request again. With `side`, it sends a request with its own history and no tools before each of its requests. With `gemini_cli`, it records each response as Gemini CLI does (`geminiChat.ts`), with adjacent text parts merged. With `loop_check`, before the request of that turn it sends a request with its own history (as Gemini CLI's `web_fetch` does), then a request as Gemini CLI's LLM loop check builds it (`loopDetectionService.ts`): the original request in a wrapper, the last 20 history entries without the trailing call turn and its results, and the check's prompt.
    """

    async def execute(state: AgentState) -> AgentState:
        from google import genai
        from google.genai import types

        def recorded(content: types.Content) -> types.Content:
            if not gemini_cli:
                return content
            parts: list[types.Part] = []
            for part in content.parts or []:
                if parts and text_only(parts[-1]) and text_only(part):
                    parts[-1] = types.Part(
                        text=(parts[-1].text or "") + (part.text or "")
                    )
                else:
                    parts.append(part)
            return types.Content(role=content.role, parts=parts)

        def text_only(part: types.Part) -> bool:
            return (
                part.text is not None
                and not part.thought
                and part.function_call is None
            )

        config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name="read_file",
                            description="Read a file.",
                            parameters_json_schema={
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                            },
                        )
                    ]
                )
            ]
        )
        async with agent_bridge(state, compaction=compaction) as bridge:
            client = genai.Client(api_key="inspect")
            contents: list[types.Content] = [
                types.Content(role="user", parts=[types.Part(text="What is 1 + 1?")])
            ]
            title = [types.Content(role="user", parts=[types.Part(text="Title?")])]

            async def side_request() -> None:
                if side:
                    await client.aio.models.generate_content(
                        model="inspect", contents=title
                    )

            for turn in range(turns):
                if turn == loop_check:
                    await client.aio.models.generate_content(
                        model="inspect",
                        contents=[
                            types.Content(
                                role="user", parts=[types.Part(text="Fetch?")]
                            )
                        ],
                    )
                    await client.aio.models.generate_content(
                        model="inspect",
                        contents=[
                            types.Content(
                                role="user",
                                parts=[
                                    types.Part(
                                        text="<original_user_request>What is 1 + 1?</original_user_request>"
                                    )
                                ],
                            ),
                            *contents[1:-2][-20:],
                            types.Content(
                                role="user", parts=[types.Part(text="Loop?")]
                            ),
                        ],
                    )
                if retry:
                    await side_request()
                    await client.aio.models.generate_content(
                        model="inspect", contents=contents, config=config
                    )
                await side_request()
                response = await client.aio.models.generate_content(
                    model="inspect",
                    contents=contents,
                    config=config,
                )
                assert response.candidates and response.candidates[0].content
                contents.append(recorded(response.candidates[0].content))
                calls = response.function_calls or []
                if not calls:
                    break
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    id=call.id,
                                    name=call.name,
                                    response={"output": f"t{turn}:{index}{padding}"},
                                )
                            )
                            for index, call in enumerate(calls)
                        ],
                    )
                )
            return bridge.state

    return execute


def gemini_turns() -> list[ModelOutput]:
    """Gemini's turns for `gemini_scaffold`: a text part and signed reasoning (the bridge's `<think>` part, next to the text) before the second turn's calls move their parts, and the third reads `a.txt` again at the first part, as the first turn did."""
    return [
        r7_tool_calls(read("a.txt", "read_1"), read("b.txt", "read_2")),
        ModelOutput(
            model="mockllm/model",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=[
                            ContentText(text="Reading again."),
                            ContentReasoning(reasoning="c2lnbmF0dXJl", redacted=True),
                        ],
                        tool_calls=[read("a.txt", "read_3"), read("c.txt", "read_4")],
                    ),
                    stop_reason="tool_calls",
                )
            ],
        ),
        r7_tool_calls(read("a.txt", "read_5")),
        done(),
    ]


@pytest.mark.parametrize("gemini_cli", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_google_bridge_result_goes_to_its_call_with_a_sentinel(
    gemini_cli: bool,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # with a sentinel, the Google bridge hands each call over under its id and
    # reads its result back under it; with `gemini_cli`, the second turn's text
    # and `<think>` parts are merged, which moves its calls' parts
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(gemini_scaffold(gemini_cli=gemini_cli)),
        sentinel=[r7_probe(seen, copies=True)],
    )
    [log] = eval(task, model=get_model("mockllm/model", custom_outputs=gemini_turns()))
    assert log.status == "success", log.error
    events = logged_sample(log).events
    made = [
        e for e in events if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    assert len(made) == 4
    with caplog.at_level(logging.WARNING):
        assert_replay_rebuilds_bridge_steps(log, seen)
    assert replay_warnings(caplog) == []
    uuids = [e.uuid for e in made]
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_inputs(log, inputs)
        rebuilt = bridged_steps(log, replay)
        assert [
            (s.stage, uuids.index(s.id.split("/")[0]), s.id.split("/")[1])
            for s in rebuilt
        ] == [
            ("tool_call", 0, "read_1"),
            ("tool_call", 0, "read_2"),
            ("tool_result", 0, "read_1"),
            ("tool_result", 0, "read_2"),
            ("tool_call", 1, "read_3"),
            ("tool_call", 1, "read_4"),
            ("tool_result", 1, "read_3"),
            ("tool_result", 1, "read_4"),
            ("tool_call", 2, "read_5"),
            ("tool_result", 2, "read_5"),
        ], inputs
        # each result as the model next received it
        results = [
            (uuids.index(s.id.split("/")[0]), resulted(s))
            for s in rebuilt
            if s.stage == "tool_result"
        ]
        assert [r.text for _, r in results] == [
            '{"output": "t0:0"}',
            '{"output": "t0:1"}',
            '{"output": "t1:0"}',
            '{"output": "t1:1"}',
            '{"output": "t2:0"}',
        ], inputs
        for turn, result in results:
            assert result in made[turn + 1].input, inputs
        assert replay_warnings(caplog) == []


def anchored_calls(*calls: ToolCall) -> ModelOutput:
    """Gemini's response with `calls`, each after a signed reasoning anchor naming its id, as the Google provider records them."""
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=[
                        ContentText(text="Reading."),
                        *[
                            ContentReasoning(
                                reasoning=base64.b64encode(
                                    f"signature {index}".encode()
                                ).decode(),
                                redacted=True,
                                internal={"gemini_function_call_id": call.id},
                            )
                            for index, call in enumerate(calls)
                        ],
                    ],
                    tool_calls=list(calls),
                ),
                stop_reason="tool_calls",
            )
        ],
    )


@pytest.mark.parametrize("reuse", ["in_one_response", "across_turns"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_google_bridge_call_under_a_fresh_id_carries_the_message_the_agent_received(
    reuse: str,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the Google bridge hands calls sharing an id in one response, or reusing
    # an earlier call's, over under fresh ids, and renames their reasoning
    # anchors to match. Replay's steps carry the message the agent received,
    # anchors included, and the result the agent sent for each renamed call,
    # as live. Across turns, the first call's result under read_1 has no step,
    # as two calls were proposed under read_1
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    turns = (
        [anchored_calls(read("a.txt", "null"), read("b.txt", "null")), done()]
        if reuse == "in_one_response"
        else [
            anchored_calls(read("a.txt", "read_1")),
            anchored_calls(read("b.txt", "read_1")),
            done(),
        ]
    )
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(gemini_scaffold()),
        sentinel=[r7_probe(seen, copies=True)],
    )
    [log] = eval(task, model=get_model("mockllm/model", custom_outputs=turns))
    assert log.status == "success", log.error
    made = [
        e
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    [renamed] = [e for e in made if e.agent_tool_call_ids is not None]
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        replay = assert_replay_rebuilds_bridge_steps(
            log, seen, unbuilt=0 if reuse == "in_one_response" else 1
        )
    assert replay_warnings(caplog) == []
    rebuilt = assert_bridged_steps_follow_the_conversation(log, replay)
    assert [s.stage for s in rebuilt] == (
        ["tool_call"] * 2 + ["tool_result"] * 2
        if reuse == "in_one_response"
        else ["tool_call", "tool_call", "tool_result"]
    )
    fresh = [s for s in rebuilt if s.id.startswith(f"{renamed.uuid}/")]
    assert {called(s).id for s in fresh} <= set(renamed.agent_tool_call_ids or [])
    for step in fresh:
        message = tool_step(step).assistant_message
        assert message is not None and not isinstance(message.content, str)
        anchors = [
            part.internal["gemini_function_call_id"]
            for part in message.content
            if isinstance(part, ContentReasoning) and isinstance(part.internal, dict)
        ]
        assert anchors == renamed.agent_tool_call_ids


@tool
def r7_read_file() -> Tool:
    async def execute(path: str) -> str:
        """Read a file.

        Args:
            path: The file to read.
        """
        return f"<{path}>"

    return execute


@approver
def r7_approved_paths(paths: dict[str, str]) -> Approver:
    """Approves a call, modified to read `paths[path]` where `paths` has its path."""

    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        path = call.arguments.get("path")
        if path not in paths:
            return Approval(decision="approve")
        return Approval(
            decision="modify",
            modified=replace(call, arguments={"path": paths[path]}),
        )

    return approve


@agent
def r7_google_dispatcher_scaffold(approval: list[ApprovalPolicy]) -> Agent:
    """An Antigravity-style tool loop over the Google API: it calls a bridged host tool through the `call_mcp_tool` dispatcher, runs each call as the bridge hands it over, and sends each result back as a `functionResponse`, until a response has no calls."""

    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.google_api import inspect_google_api_request
        from inspect_ai.agent._bridge.sandbox.service import call_tool
        from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge

        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=8080,
            model=None,
            bridged_tools={"host": {"read_file": r7_read_file()}},
            approval=approval,
        )
        tools = [
            {
                "functionDeclarations": [
                    {
                        "name": "call_mcp_tool",
                        "description": "Call a tool on an MCP server.",
                        "parameters": {"type": "object"},
                    }
                ]
            }
        ]
        contents: list[dict[str, Any]] = [
            {"role": "user", "parts": [{"text": "Read the files."}]}
        ]
        for _ in range(10):
            response = await inspect_google_api_request(
                {"model": "inspect", "contents": contents, "tools": tools},
                None,
                None,
                bridge,
            )
            content = response["candidates"][0]["content"]
            contents.append(content)
            calls = [p["functionCall"] for p in content["parts"] if "functionCall" in p]
            if not calls:
                break
            parts = []
            for function_call in calls:
                arguments = function_call["args"]
                result = await call_tool(bridge)(
                    arguments["ServerName"],
                    arguments["ToolName"],
                    arguments["Arguments"],
                )
                parts.append(
                    {
                        "functionResponse": {
                            "name": function_call["name"],
                            "response": {"output": str(result)},
                        }
                    }
                )
            contents.append({"role": "user", "parts": parts})
        return state

    return execute


def dispatched_read(path: str) -> ModelOutput:
    return call(
        "call_mcp_tool",
        ServerName="host",
        ToolName="read_file",
        Arguments={"path": path},
    )


def reading(*paths: str, content: Sequence[Content] = ()) -> ModelOutput:
    """A response with `content` before a read of each of `paths`, for `generated_ids` to give the calls ids."""
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=list(content), tool_calls=[read(path, "") for path in paths]
                ),
                stop_reason="tool_calls",
            )
        ],
    )


SIGNED = ContentReasoning(reasoning="c2lnbmF0dXJl", redacted=True)
"""Signed reasoning, which the Google bridge sends as a `<think>` part."""


def google_run(case: str) -> tuple[Agent, Any, list[ApprovalPolicy] | None]:
    """The scaffold, model and approval policies of a Google bridge run (`test_a_google_bridge_call_gets_its_result_without_a_sentinel`)."""
    text = ContentText(text="Reading.")
    retried = [o for turn in [reading("a.txt")] * 3 for o in [turn, turn]]
    match case:
        case "turns" | "gemini-cli":
            return (
                gemini_scaffold(gemini_cli=case == "gemini-cli"),
                get_model("mockllm/model", custom_outputs=gemini_turns()),
                None,
            )
        case "identical" | "identical-gemini-cli":
            return (
                gemini_scaffold(gemini_cli=case == "identical-gemini-cli"),
                generated_ids(
                    "read_", reading("a.txt", "a.txt", content=[text, SIGNED]), done()
                ),
                None,
            )
        case "modified":
            return (
                gemini_scaffold(),
                generated_ids("read_", reading("original.txt"), done()),
                [
                    ApprovalPolicy(
                        r7_approved_paths({"original.txt": "approved.txt"}), "*"
                    )
                ],
            )
        case "dispatcher-modified":
            paths = {"first.txt": "second.txt", "third.txt": "first.txt"}
            return (
                r7_google_dispatcher_scaffold(
                    [ApprovalPolicy(r7_approved_paths(paths), "*")]
                ),
                outputs(
                    dispatched_read("first.txt"), dispatched_read("third.txt"), done()
                ),
                None,
            )
        case "retry" | "retry-side":
            return (
                gemini_scaffold(retry=True, side=case == "retry-side"),
                generated_ids("read_", *retried, done(), done()),
                None,
            )
        case "loop-check":
            return (
                gemini_scaffold(loop_check=3),
                generated_ids(
                    "read_",
                    *[reading(f"{name}.txt") for name in "aba"],
                    done("Fetched."),
                    done('{"loop": false}'),
                    done(),
                ),
                None,
            )
        case "retry-compaction":
            return (
                gemini_scaffold(
                    retry=True,
                    compaction=CompactionEdit(threshold=COMPACTED_AT_FOUR),
                    padding=PADDING,
                ),
                generated_ids(
                    "read_",
                    reading("a.txt", content=[text, SIGNED]),
                    reading("a.txt", content=[SIGNED]),
                    *[reading(f"{name}.txt") for name in "bbccdd"],
                    done(),
                    done(),
                ),
                None,
            )
    raise ValueError(case)


PADDING = " word" * 100
"""A tool result's padding, so that one result's removal brings an input back under the compaction threshold."""

COMPACTED_AT_FOUR = 500
"""A `CompactionEdit` threshold that `retrying_scaffold(padding=PADDING)` first passes with four results, so compaction removes the first (it keeps three)."""

COMPACTED_AT_TWO = 300
"""A `CompactionEdit` threshold that `retrying_scaffold(padding=PADDING)` first passes with two results."""


GOOGLE_RUNS = [
    "turns",
    "gemini-cli",
    "identical",
    "identical-gemini-cli",
    "modified",
    "dispatcher-modified",
    "retry",
    "retry-side",
    "loop-check",
    "retry-compaction",
]
"""The cases of `google_run`."""

GOOGLE_RESULTS: dict[str, list[tuple[int, int, str]]] = {
    **{
        case: [
            (0, 0, "t0:0"),
            (0, 1, "t0:1"),
            (1, 0, "t1:0"),
            (1, 1, "t1:1"),
            (2, 0, "t2:0"),
        ]
        for case in ["turns", "gemini-cli"]
    },
    **{
        case: [(0, 0, "t0:0"), (0, 1, "t0:1")]
        for case in ["identical", "identical-gemini-cli"]
    },
    "modified": [(0, 0, "t0:0")],
    "dispatcher-modified": [(0, 0, "<second.txt>"), (1, 0, "<first.txt>")],
    "retry": [(1, 0, "t0:0"), (3, 0, "t1:0"), (5, 0, "t2:0")],
    "retry-side": [(3, 0, "t0:0"), (7, 0, "t1:0"), (11, 0, "t2:0")],
    "loop-check": [(0, 0, "t0:0"), (1, 0, "t1:0"), (2, 0, "t2:0")],
    "retry-compaction": [(turn * 2 + 1, 0, f"t{turn}:0{PADDING}") for turn in range(4)],
}
"""The results of each `google_run` case: the index of the bridge's model call whose response proposed the call, the call's position in that response, and the output the result carries. A call in a response the scaffold lost has none."""


def google_tool_steps(
    log: EvalLog,
    replay: Sequence["ReplayStep"] | None = None,
    seen: dict[str, Step] | None = None,
) -> list[tuple[str, int, int, Any]]:
    """The bridge's tool steps of `log`, from `replay` or as `r7_probe(seen)` saw them live, sorted by call: each step's stage, the index of the bridge's model call whose response proposed the call, the call's position in that response, and the call's function and arguments or the result's text."""
    events = logged_sample(log).events
    made = [
        e for e in events if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    proposed = {
        (e.uuid, c.id): (index, position)
        for index, e in enumerate(made)
        for position, c in enumerate(e.output.message.tool_calls or [])
    }
    keyed: list[tuple[str, tuple[int, int], BeforeToolCall | AfterToolCall]] = []
    if replay is not None:
        for s in replay:
            made_by, _, call_id = s.id.partition("/")
            if (made_by, call_id) in proposed:
                keyed.append((s.stage, proposed[(made_by, call_id)], tool_step(s)))
    else:
        assert seen is not None
        # live, a bridge's tool step is named by its call id alone
        by_id = {call_id: at for (_, call_id), at in proposed.items()}
        assert len(by_id) == len(proposed)
        for e in events:
            if isinstance(e, SentinelEvent) and e.path == "r7_probe":
                step = seen[e.explanation or ""]
                if isinstance(step, BeforeToolCall | AfterToolCall):
                    keyed.append((e.stage, by_id[e.step_id], step))
    shown = [
        (
            stage,
            index,
            position,
            step.result.text
            if isinstance(step, AfterToolCall)
            else (step.call.function, step.call.arguments),
        )
        for stage, (index, position), step in keyed
    ]
    return sorted(shown, key=lambda s: (s[1], s[2], s[0]))


@pytest.mark.parametrize("case", GOOGLE_RUNS)
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_google_bridge_call_gets_its_result_without_a_sentinel(
    case: str,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the Google bridge hands each call over under its id and reads its result
    # back under it, with or without a sentinel, so each call gets the result
    # the model next received, by call id. `retry-compaction` loses each
    # response and sends its request again, with text before the first lost
    # call and not before its retry, and compaction replaces the first result
    # after the model received it
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    scaffold, model, approval = google_run(case)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(scaffold),
        approval=approval,
    )
    [log] = eval(task, model=model)
    assert log.status == "success", log.error
    made = [
        e
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    proposed = [
        (index, f"{e.uuid}/{c.id}")
        for index, e in enumerate(made)
        for c in e.output.message.tool_calls or []
    ]
    if case == "retry-compaction":
        assert len([e for e in made if e.tools]) == 10
        removed = [
            m
            for e in made
            for m in e.input
            if isinstance(m, ChatMessageTool) and m.text == TOOL_RESULT_REMOVED
        ]
        assert len(removed) == 2
    rebuilt: dict[str, list[tuple[str, int, int, Any]]] = {}
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = bridged_steps(log, replayed_inputs(log, inputs))
        assert replay_warnings(caplog) == []
        # each proposed call, and the results of GOOGLE_RESULTS, under the
        # proposing call's id
        assert [s.id for s in replay if s.stage == "tool_call"] == [
            step_id for _, step_id in proposed
        ], inputs
        steps = google_tool_steps(log, replay)
        assert [
            (index, position, json.loads(text)["output"])
            for stage, index, position, text in steps
            if stage == "tool_result"
        ] == GOOGLE_RESULTS[case], inputs
        # each result as the model next received it
        for s in replay:
            if s.stage == "tool_result":
                index = next(i for i, step_id in proposed if step_id == s.id)
                call_id = s.id.partition("/")[2]
                received = next(
                    m
                    for e in made[index + 1 :]
                    for m in e.input
                    if isinstance(m, ChatMessageTool) and m.tool_call_id == call_id
                )
                assert resulted(s) == received, inputs
        rebuilt[inputs] = steps
    assert rebuilt["pooled"] == rebuilt["expanded"]

    # the same run with a sentinel watching: its log replays as it saw each
    # step, and the bridge's tool steps are those replayed without one
    seen: dict[str, Step] = {}
    scaffold, model, approval = google_run(case)
    probed = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(scaffold),
        approval=approval,
        sentinel=[r7_probe(seen, copies=True)],
    )
    [live] = eval(probed, model=model)
    assert live.status == "success", live.error
    # the sentinel is shown an approver's modify; replay shows the call as the
    # model wrote it
    modified = case in ["modified", "dispatcher-modified"]
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert_replay_rebuilds_bridge_steps(
            live,
            seen,
            bridge_differences=[
                f"{stage}.{field}"
                for stage in ["tool_call", "tool_result"]
                for field in ["call", "view"]
            ]
            if modified
            else [],
        )
    assert replay_warnings(caplog) == []
    watched = google_tool_steps(live, seen=seen)
    replayed_steps = rebuilt["expanded"]
    if modified:
        # the sentinel was shown the approver's call (the dispatcher's under the
        # host tool's name)
        assert [shown for stage, _, _, shown in watched if stage == "tool_call"] == [
            ("read_file", {"path": path})
            for path in (
                ["approved.txt"] if case == "modified" else ["second.txt", "first.txt"]
            )
        ]
        watched, replayed_steps = (
            [
                (stage, index, position, None if stage == "tool_call" else shown)
                for stage, index, position, shown in steps
            ]
            for steps in (watched, replayed_steps)
        )
    assert watched == replayed_steps


GOOGLE_REBUILT_IDS = Path(__file__).parent / "fixtures" / "google_bridge_0.3.292.dev12"
"""Logs of each `google_run` case but `retry-compaction`, and of `gemini_scaffold` reading 20 files (`20-turns`), recorded without a sentinel by the Google bridge before it kept call ids (Inspect at 7adfe8c18): it recorded each call it handed over, and each result, under an id rebuilt from the call (`call_<name>_<hash>`), which no call the model proposed has."""


def google_rebuilt_ids_log(case: str) -> EvalLog:
    log = read_eval_log(str(GOOGLE_REBUILT_IDS / f"{case}.eval"))
    assert log.eval.packages["inspect_ai"] == "0.3.292.dev12+g7adfe8c18"
    return log


@pytest.mark.parametrize(
    "case", [case for case in GOOGLE_RUNS if case != "retry-compaction"]
)
def test_a_google_bridge_call_in_a_log_with_rebuilt_ids_has_no_result(
    case: str, caplog: pytest.LogCaptureFixture
) -> None:
    # a result recorded under a rebuilt id is no call's, so replay shows each
    # call and no result: a missing result rather than another call's
    log = google_rebuilt_ids_log(case)
    made = [
        e
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    proposed = [
        f"{e.uuid}/{c.id}" for e in made for c in e.output.message.tool_calls or []
    ]
    received = {
        m.tool_call_id for e in made for m in e.input if isinstance(m, ChatMessageTool)
    }
    assert received
    assert all(re.fullmatch(r"call_[a-z_]+_[0-9a-f]{8}", r or "") for r in received), (
        received
    )
    assert not received & {p.split("/")[1] for p in proposed}
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            rebuilt = bridged_steps(log, replayed_inputs(log, inputs))
        assert [(s.stage, s.id) for s in rebuilt] == [
            ("tool_call", p) for p in proposed
        ], inputs
        assert replay_warnings(caplog) == []


def test_a_google_bridge_call_with_a_rebuilt_id_is_not_looked_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # after the pre-push review of 391c4072a: a call whose result is recorded
    # under a rebuilt id never gets one, and looking each up again at every
    # later request made replay quadratic in the turns
    from inspect_ai._sentinel import _replay

    log = google_rebuilt_ids_log("20-turns")
    last_held = _replay._PooledInput.last_held
    attempts = 0

    def counting(self: Any, *args: Any) -> int | None:
        nonlocal attempts
        attempts += 1
        return last_held(self, *args)

    for inputs in ["expanded", "pooled"]:
        attempts = 0
        with monkeypatch.context() as patch:
            patch.setattr(_replay._PooledInput, "last_held", counting)
            replay = replayed_inputs(log, inputs)
        stages = [s.stage for s in bridged_steps(log, replay)]
        assert stages == ["tool_call"] * 20, inputs
        assert attempts == 0, inputs


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_finding_google_bridge_results_stays_linear(
    backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the Google bridge keeps call ids, so each call gets a result: twice the
    # turns take about twice the reads of the pooled history
    from inspect_ai._sentinel._steps import PoolView

    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    reads = 0
    row, getitem = PoolView.row, PoolView.__getitem__

    def counting_row(self: PoolView, position: int) -> int:
        nonlocal reads
        reads += 1
        return row(self, position)

    def counting_getitem(self: PoolView, index: Any) -> Any:
        nonlocal reads
        reads += 1
        return getitem(self, index)

    work: list[int] = []
    for turns in (20, 40):
        task = Task(
            dataset=[Sample(input="What is 1 + 1?", target="2")],
            solver=as_solver(gemini_scaffold(turns=turns + 1)),
        )
        files = [reading(f"{n}.txt") for n in range(turns)]
        [log] = eval(task, model=generated_ids("read_", *files, done()))
        assert log.status == "success", log.error
        for inputs in ["expanded", "pooled"]:
            reads = 0
            with monkeypatch.context() as patch:
                patch.setattr(PoolView, "row", counting_row)
                patch.setattr(PoolView, "__getitem__", counting_getitem)
                replay = replayed_inputs(log, inputs)
            stages = [s.stage for s in bridged_steps(log, replay)]
            assert stages == ["tool_call", "tool_result"] * turns, inputs
            work.append(reads)
    assert work[2] <= 2.2 * work[0] and work[3] <= 2.2 * work[1], work


def replayed_inputs(log: EvalLog, inputs: str) -> list["ReplayStep"]:
    """`log`'s replay from its model inputs as logged (`"expanded"`) or as a message pool (`"pooled"`)."""
    from inspect_ai._sentinel import _replay

    sample = logged_sample(log)
    events: list[Event] = list(sample.events)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    return steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
    )


@pytest.mark.parametrize("client", ["openai", "anthropic"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_compacted_result_is_not_the_result_of_a_discarded_call(
    client: str,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # each response is lost and its retry answered from the model cache; with
    # four calls run, compaction replaces the first call's result. Each id is
    # proposed twice, by the lost response and its retry, so no call takes a
    # result, the compacted one included
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    prefix = "call_" if client == "openai" else "toolu_"
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(
            retrying_scaffold(
                client,
                compaction=CompactionEdit(threshold=COMPACTED_AT_FOUR),
                padding=PADDING,
            )
        ),
        config=GenerateConfig(cache=True),
    )
    [log] = eval(
        task,
        model=generated_ids(
            prefix,
            *[r7_tool_calls(read(f"{name}.txt", "")) for name in "abcd"],
            done(),
        ),
    )
    assert log.status == "success", log.error
    events = logged_sample(log).events
    made = [
        e for e in events if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    uuids = [e.uuid for e in made]
    assert [e.cache for e in made] == ["write", "read"] * 5
    removed = [
        m
        for e in made
        for m in e.input
        if isinstance(m, ChatMessageTool) and m.text == TOOL_RESULT_REMOVED
    ]
    assert [m.tool_call_id for m in removed] == [f"{prefix}1"] * 2
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_inputs(log, inputs)
        steps = bridged_steps(log, replay)
        assert [uuids.index(s.id.split("/")[0]) for s in steps] == list(range(8))
        assert all(s.stage == "tool_call" for s in steps), inputs
        assert replay_warnings(caplog) == []


@pytest.mark.parametrize("client", ["openai", "anthropic"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_result_compacted_in_the_request_answering_its_reused_id_is_not_taken(
    client: str,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the model reuses the call id for the same call, and compaction (keeping
    # one result) replaces the first result in the request carrying the
    # second. Neither call takes a result: two calls were proposed under the id
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(
            retrying_scaffold(
                client,
                retry=False,
                compaction=CompactionEdit(threshold=COMPACTED_AT_TWO, keep_tool_uses=1),
                padding=PADDING,
            )
        ),
    )
    [log] = eval(
        task,
        model=outputs(
            r7_tool_calls(read("a.txt", "read_1")),
            r7_tool_calls(read("a.txt", "read_1")),
            done(),
        ),
    )
    assert log.status == "success", log.error
    events = logged_sample(log).events
    made = [
        e for e in events if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    uuids = [e.uuid for e in made]
    assert [
        [m.text for m in e.input if isinstance(m, ChatMessageTool)] for e in made
    ] == [[], [f"t0:read_1{PADDING}"], [TOOL_RESULT_REMOVED, f"t1:read_1{PADDING}"]]
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_inputs(log, inputs)
        results = [
            (uuids.index(s.id.split("/")[0]), resulted(s).text)
            for s in bridged_steps(log, replay)
            if s.stage == "tool_result"
        ]
        assert results == [], inputs
        assert replay_warnings(caplog) == []


COMPACTED_AT_FOUR_FRESH = 570
"""As `COMPACTED_AT_FOUR`, for results under the bridge's fresh call ids, which are longer."""


@pytest.mark.parametrize("files", ["abcd", "abac"])
@pytest.mark.parametrize("client", ["openai", "anthropic"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_calls_under_a_reused_id_take_their_own_result_not_a_compacted_one(
    files: str,
    client: str,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # four reads, all under Mistral's SDK-default "null" id, and compaction
    # (keeping three results) replacing the first read's result in the
    # request carrying the fourth's. The bridge hands a read of another file
    # than the first over under a fresh id, and records it, and keeps "null"
    # for the first file read again. Each read under its fresh id has its own
    # result. The first file's reads have none: other calls were proposed
    # under "null" (the renamed reads, by the model's id), and the log
    # doesn't show which a result under it answers. None takes the removed
    # result
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(
            retrying_scaffold(
                client,
                retry=False,
                compaction=CompactionEdit(threshold=COMPACTED_AT_FOUR_FRESH),
                padding=PADDING,
            )
        ),
    )
    [log] = eval(
        task,
        model=outputs(
            *[r7_tool_calls(read(f"{name}.txt", "null")) for name in files],
            done(),
        ),
    )
    assert log.status == "success", log.error
    made = [
        e
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    uuids = [e.uuid for e in made]
    assert [[c.id for c in e.output.message.tool_calls or []] for e in made] == [
        ["null"]
    ] * 4 + [[]]
    # the last request carries "null" for the first file's reads, a fresh id
    # for each other read, and the removed result under "null"
    [tool_ids] = [
        [m.tool_call_id for m in e.input if isinstance(m, ChatMessageTool)]
        for e in made[4:]
    ]
    kept = [turn for turn, name in enumerate(files) if name == "a"]
    assert [turn for turn, id in enumerate(tool_ids) if id == "null"] == kept
    assert len(set(tool_ids) - {"null"}) == 4 - len(kept)
    removed = [
        (made.index(e), m.tool_call_id)
        for e in made
        for m in e.input
        if isinstance(m, ChatMessageTool) and m.text == TOOL_RESULT_REMOVED
    ]
    assert removed == [(4, "null")]
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_inputs(log, inputs)
        steps = bridged_steps(log, replay)
        want: list[tuple[str, int]] = []
        for turn, name in enumerate(files):
            want.append(("tool_call", turn))
            if name != "a":
                want.append(("tool_result", turn))
        assert [(s.stage, uuids.index(s.id.split("/")[0])) for s in steps] == want, (
            inputs
        )
        assert_exact_results(steps)
        assert all(
            resulted(s).text != TOOL_RESULT_REMOVED
            for s in steps
            if s.stage == "tool_result"
        )
        assert replay_warnings(caplog) == []


@pytest.mark.parametrize("spans", ["agent", "none"])
@pytest.mark.parametrize("client", ["openai", "anthropic"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_sequential_bridges_pair_results_by_the_ids_each_handed_over(
    spans: str,
    client: str,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # two agents run one after the other, each with its own bridge, all calls
    # under "null": the first reads a.txt, the second b.txt and then a.txt
    # three times, with compaction (keeping three results) replacing b.txt's
    # result in its last request. The second bridge keeps "null" for b.txt and
    # hands each a.txt over under a fresh id, which it records. In their own
    # agent spans the agents are two conversations; without one, they are one
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)

    @solver
    def two_agents() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            first = retrying_scaffold(client, retry=False)
            second = retrying_scaffold(
                client,
                retry=False,
                padding=PADDING,
                compaction=CompactionEdit(threshold=COMPACTED_AT_FOUR_FRESH),
            )
            if spans == "agent":
                await run(first, "What is 1 + 1?")
                await run(second, "What is 1 + 1?")
            else:
                await first(AgentState(messages=[]))
                await second(AgentState(messages=[]))
            return state

        return solve

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")], solver=two_agents()
    )
    reads = [r7_tool_calls(read(f"{name}.txt", "null")) for name in "abaaa"]
    [log] = eval(task, model=outputs(reads[0], done(), *reads[1:], done()))
    assert log.status == "success", log.error
    made = [
        e
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    uuids = [e.uuid for e in made]
    [tool_ids] = [
        [m.tool_call_id for m in e.input if isinstance(m, ChatMessageTool)]
        for e in made[6:]
    ]
    assert tool_ids[0] == "null"
    assert "null" not in tool_ids[1:]
    removed = [
        (made.index(e), m.tool_call_id)
        for e in made
        for m in e.input
        if isinstance(m, ChatMessageTool) and m.text == TOOL_RESULT_REMOVED
    ]
    assert removed == [(6, "null")]
    # each a.txt read under its fresh id has its own result. In the first
    # agent's own conversation, "null" is one call's, so it has its result.
    # In a conversation where the model also proposed the renamed a.txt
    # reads under "null", the call kept under it has none, as the log
    # doesn't show which call a result under "null" answers
    want = [0, 3, 4, 5] if spans == "agent" else [3, 4, 5]
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_inputs(log, inputs)
        steps = bridged_steps(log, replay)
        assert [
            uuids.index(s.id.split("/")[0]) for s in steps if s.stage == "tool_call"
        ] == [0, 2, 3, 4, 5], inputs
        assert [
            uuids.index(s.id.split("/")[0]) for s in steps if s.stage == "tool_result"
        ] == want, inputs
        assert_exact_results(steps)
        assert all(
            resulted(s).text != TOOL_RESULT_REMOVED
            for s in steps
            if s.stage == "tool_result"
        )
        assert replay_warnings(caplog) == []


@agent(name="concurrent_scaffold")
def concurrent_scaffold() -> Agent:
    """Two OpenAI-client tool loops run concurrently in one bridge, each sending its first request before either sends a result, and answering its calls with `loop<n>:<call id>`."""

    async def execute(state: AgentState) -> AgentState:
        from openai import AsyncOpenAI

        tools: list[Any] = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            }
        ]
        proposed = 0
        both_proposed = anyio.Event()
        async with agent_bridge(state) as bridge:
            async with AsyncOpenAI(api_key="sk-test") as client:

                async def loop(n: int) -> None:
                    nonlocal proposed
                    messages: list[Any] = [
                        {"role": "user", "content": "What is 1 + 1?"}
                    ]
                    for _ in range(2):
                        completion = await client.chat.completions.create(
                            model="inspect", messages=messages, tools=tools
                        )
                        message = completion.choices[0].message
                        messages.append(message.model_dump(exclude_none=True))
                        if not message.tool_calls:
                            return
                        proposed += 1
                        if proposed == 2:
                            both_proposed.set()
                        await both_proposed.wait()
                        for call in message.tool_calls:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call.id,
                                    "content": f"loop{n}:{call.id}",
                                }
                            )

                await tg_collect([partial(loop, 0), partial(loop, 1)])
            return bridge.state

    return execute


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_concurrent_identical_calls_under_one_id_take_no_result(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # two tool loops of one agent each propose the same call under "null"
    # before either sends its result; the bridge hands both over under
    # "null". Each loop's next request carries its own result, so a result
    # under the id can be either call's, and neither call has a result step
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(concurrent_scaffold()),
    )
    proposal = r7_tool_calls(read("a.txt", "null"))
    [log] = eval(task, model=outputs(proposal, proposal, done(), done()))
    assert log.status == "success", log.error
    made = [
        e
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    uuids = [e.uuid for e in made]
    assert [[c.id for c in e.output.message.tool_calls or []] for e in made] == [
        ["null"],
        ["null"],
        [],
        [],
    ]
    assert sorted(
        m.text for e in made for m in e.input if isinstance(m, ChatMessageTool)
    ) == ["loop0:null", "loop1:null"]
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_inputs(log, inputs)
        assert [
            (s.stage, uuids.index(s.id.split("/")[0]))
            for s in bridged_steps(log, replay)
        ] == [("tool_call", 0), ("tool_call", 1)], inputs
        assert replay_warnings(caplog) == []


@pytest.mark.parametrize(
    "ids", [("c1", "c2"), ("null", "null")], ids=["distinct", "null"]
)
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_concurrent_different_calls_take_their_own_results(
    ids: tuple[str, str],
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # two tool loops of one agent each propose a different call before either
    # sends its result, so each loop's first request looks like a retry of
    # the other's. Each distinct call has its own result. Under "null", the
    # bridge hands the second call over under a fresh id and records it: that
    # call has its own result, and the first, kept under "null", has none, as
    # the model proposed both under it
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(concurrent_scaffold()),
    )
    first = r7_tool_calls(read("a.txt", ids[0]))
    second = r7_tool_calls(read("b.txt", ids[1]))
    [log] = eval(task, model=outputs(first, second, done(), done()))
    assert log.status == "success", log.error
    made = [
        e
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    recorded = [e.agent_tool_call_ids for e in made if e.agent_tool_call_ids]
    assert len(recorded) == (1 if ids[0] == ids[1] else 0)
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_inputs(log, inputs)
        steps = bridged_steps(log, replay)
        results = 2 if ids[0] != ids[1] else 1
        assert (
            sorted(s.stage for s in steps)
            == ["tool_call"] * 2 + ["tool_result"] * results
        ), inputs
        assert len({s.id for s in steps}) == 2
        assert_exact_results(steps)
        assert replay_warnings(caplog) == []


def replayed_without_agent_tool_call_ids(
    log: EvalLog, inputs: str
) -> list["ReplayStep"]:
    """`replayed_inputs`, with every `ModelEvent.agent_tool_call_ids` removed, as in a log written before the bridge recorded them."""
    from inspect_ai._sentinel import _replay

    sample = logged_sample(log)
    events: list[Event] = [
        e.model_copy(update={"agent_tool_call_ids": None})
        if isinstance(e, ModelEvent)
        else e
        for e in sample.events
    ]
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    return steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
    )


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_log_without_agent_tool_call_ids_pairs_by_the_model_s_ids(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # a log written before the bridge recorded the ids the agent received: a
    # call the bridge handed over under a fresh id is read by the model's id,
    # in the model's message, so two calls under read_1 take no result
    log, _ = scaffold_log(
        backend,
        monkeypatch,
        r7_tool_calls(read("a.txt", "read_1")),
        r7_tool_calls(read("b.txt", "read_1")),
    )
    made = [
        e
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    assert [e.agent_tool_call_ids is not None for e in made] == [False, True, False]
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_without_agent_tool_call_ids(log, inputs)
        steps = bridged_steps(log, replay)
        assert [(s.stage, s.id) for s in steps] == [
            ("tool_call", f"{made[0].uuid}/read_1"),
            ("tool_call", f"{made[1].uuid}/read_1"),
        ], inputs
        for step, turn in zip(steps, made):
            message = tool_step(step).assistant_message
            assert message is not None
            assert comparable(message) == comparable(turn.output.message)
            assert tool_step(step).message_id == turn.output.message.id
        assert replay_warnings(caplog) == []


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_log_without_agent_tool_call_ids_takes_no_result_under_a_reused_id(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # `test_calls_under_a_reused_id_take_their_own_result_not_a_compacted_one`
    # in a log written before the bridge recorded the ids the agent received:
    # four calls under "null" in one conversation, so none has a result
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(
            retrying_scaffold(
                "openai",
                retry=False,
                compaction=CompactionEdit(threshold=COMPACTED_AT_FOUR_FRESH),
                padding=PADDING,
            )
        ),
    )
    [log] = eval(
        task,
        model=outputs(
            *[r7_tool_calls(read(f"{name}.txt", "null")) for name in "abcd"],
            done(),
        ),
    )
    assert log.status == "success", log.error
    uuids = [
        e.uuid
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_without_agent_tool_call_ids(log, inputs)
        assert [
            (s.stage, uuids.index(s.id.split("/")[0]), s.id.split("/")[1])
            for s in bridged_steps(log, replay)
        ] == [("tool_call", turn, "null") for turn in range(4)], inputs
        assert replay_warnings(caplog) == []


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_a_call_renamed_from_a_dropped_call_s_id_leaves_that_call_without_a_result(
    inputs: str,
) -> None:
    # after the round 1 review: a bridge outside any agent span drops its call
    # under "null"; an agent in its own span runs another call under "null";
    # then a bridge outside any agent span continues that agent's messages,
    # and the bridge hands its call, which the model proposed under "null",
    # over under "fresh". The result under "null" the continued messages
    # carry is the agent's call's, not the dropped call's. The model proposed
    # two calls under "null" outside any agent span, so the dropped call has
    # no result, as in a log without the recorded ids
    from inspect_ai._sentinel import _replay

    def proposing(path: str, id: str = "null") -> ChatMessageAssistant:
        return ChatMessageAssistant(
            id=f"msg-{path}",
            content="",
            tool_calls=[
                ToolCall(id=id, function="read_file", arguments={"path": path})
            ],
        )

    def made(
        uuid: str,
        input: list[ChatMessage],
        output: ChatMessageAssistant,
        span_id: str | None = None,
        ids: list[str] | None = None,
    ) -> ModelEvent:
        return ModelEvent(
            uuid=uuid,
            span_id=span_id,
            origin="agent",
            model="mockllm/model",
            requested_model="inspect",
            input=input,
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_message(output),
            agent_tool_call_ids=ids,
        )

    start: list[ChatMessage] = [ChatMessageUser(content="Read the files.")]
    kept = proposing("kept.txt")
    continued = [
        *start,
        kept,
        ChatMessageTool(id="kept-result", content="kept", tool_call_id="null"),
    ]
    third_result = ChatMessageTool(
        id="third-result", content="third", tool_call_id="fresh"
    )
    events: list[Event] = solving(
        [
            made("lost", start, proposing("lost.txt")),
            SpanBeginEvent(id="agent-b", name="agent b", type="agent"),
            made("kept", start, kept, "agent-b"),
            made(
                "kept-done", continued, ChatMessageAssistant(content="done"), "agent-b"
            ),
            SpanEndEvent(id="agent-b"),
            made("third", continued, proposing("third.txt"), ids=["fresh"]),
            made(
                "third-done",
                [*continued, proposing("third.txt", "fresh"), third_result],
                ChatMessageAssistant(content="done"),
            ),
        ]
    )
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    replay = steps_from_events(
        [],
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version="0.3.292", sentinel=False),
    )
    assert [
        (s.stage, s.id, resulted(s).id if s.stage == "tool_result" else None)
        for s in replay
        if s.stage.startswith("tool")
    ] == [
        ("tool_call", "lost/null", None),
        ("tool_call", "kept/null", None),
        ("tool_result", "kept/null", "kept-result"),
        ("tool_call", "third/fresh", None),
        ("tool_result", "third/fresh", "third-result"),
    ]


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("bridges", ["one", "two"])
def test_a_call_the_model_proposes_under_an_id_handed_out_before_takes_its_result(
    bridges: str, inputs: str
) -> None:
    # after the round 2 review: a bridge hands a call the model proposed
    # under "null" (an id its starting history holds) over under a new id,
    # and then the model proposes a call under that new id: the same call
    # again in the same bridge, which keeps the id, or, with "two", another
    # call in a second bridge outside any agent span, whose model read the id.
    # The ids come from the bridge's own renaming (`_fresh_call_ids`). The
    # later call takes its result, as in a log without the recorded ids; the
    # renamed call has none, as its id is the later call's too
    from inspect_ai._sentinel import _replay
    from inspect_ai.agent._bridge.util import _fresh_call_ids

    def proposing(path: str, id: str) -> ChatMessageAssistant:
        return ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(id=id, function="read_file", arguments={"path": path})
            ],
        )

    def made(
        uuid: str,
        input: list[ChatMessage],
        output: ChatMessageAssistant,
        ids: list[str] | None = None,
    ) -> ModelEvent:
        return ModelEvent(
            uuid=uuid,
            origin="agent",
            model="mockllm/model",
            requested_model="inspect",
            input=input,
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_message(output),
            agent_tool_call_ids=ids,
        )

    def handed_over(
        bridge: AgentBridge, output: ChatMessageAssistant, history: set[str]
    ) -> ChatMessageAssistant:
        handed = _fresh_call_ids(bridge, ModelOutput.from_message(output), history)
        calls = handed.message.tool_calls or []
        bridge._handouts.propose(calls)
        bridge._handouts.hand_over(calls, calls, None)
        return handed.message

    start_a: list[ChatMessage] = [
        ChatMessageUser(content="Read a file."),
        proposing("old.txt", "null"),
        ChatMessageTool(content="old", tool_call_id="null"),
    ]
    bridge_a = AgentBridge(AgentState(messages=list(start_a)))
    first = proposing("a.txt", "null")
    handed_first = handed_over(bridge_a, first, {"null"})
    assert handed_first.tool_calls
    fresh = handed_first.tool_calls[0].id
    assert fresh != "null"
    continued_a = [
        *start_a,
        handed_first,
        ChatMessageTool(id="result-a", content="a", tool_call_id=fresh),
    ]
    if bridges == "one":
        bridge_b, start_b, later = bridge_a, continued_a, proposing("a.txt", fresh)
    else:
        start_b = [ChatMessageUser(content=f"Read b.txt under the call id {fresh}.")]
        bridge_b = AgentBridge(AgentState(messages=list(start_b)))
        later = proposing("b.txt", fresh)
    held = {"null", fresh} if bridges == "one" else set()
    assert handed_over(bridge_b, later, held) == later
    events: list[Event] = solving(
        [
            made("a", start_a, first, [fresh]),
            made("a-done", continued_a, ChatMessageAssistant(content="done")),
            made("b", start_b, later),
            made(
                "b-done",
                [
                    *start_b,
                    later,
                    ChatMessageTool(id="result-b", content="b", tool_call_id=fresh),
                ],
                ChatMessageAssistant(content="done"),
            ),
        ]
    )
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    replay = steps_from_events(
        [],
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version="0.3.292", sentinel=False),
    )
    assert [
        (s.stage, s.id, resulted(s).id if s.stage == "tool_result" else None)
        for s in replay
        if s.stage.startswith("tool")
    ] == [
        ("tool_call", f"a/{fresh}", None),
        ("tool_call", f"b/{fresh}", None),
        ("tool_result", f"b/{fresh}", "result-b"),
    ]


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("other", ["bridged", "native"])
def test_a_renamed_call_takes_no_result_under_an_id_another_conversation_proposed(
    other: str, inputs: str
) -> None:
    # a bridge outside any agent span hands a call over under a new id, and
    # the agent drops the response; an agent in its own span, bridged or
    # native, whose model was given that id, proposes another call under it;
    # then a bridge outside any agent span continues that agent's messages.
    # The result under the id is the other agent's call's, not the dropped
    # call's, so the dropped call has none, as in a log without the
    # recorded ids
    from inspect_ai._sentinel import _replay

    fresh = "call_fresh"

    def proposing(path: str, id: str) -> ChatMessageAssistant:
        return ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(id=id, function="read_file", arguments={"path": path})
            ],
        )

    def made(
        uuid: str,
        input: list[ChatMessage],
        output: ChatMessageAssistant,
        span_id: str | None = None,
        ids: list[str] | None = None,
        bridged: bool = True,
    ) -> ModelEvent:
        return ModelEvent(
            uuid=uuid,
            span_id=span_id,
            origin="agent",
            model="mockllm/model",
            requested_model="inspect" if bridged else None,
            input=input,
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_message(output),
            agent_tool_call_ids=ids,
        )

    start: list[ChatMessage] = [
        ChatMessageUser(content="Read a file."),
        proposing("old.txt", "null"),
        ChatMessageTool(content="old", tool_call_id="null"),
    ]
    given: list[ChatMessage] = [
        ChatMessageUser(content=f"Read b.txt under the call id {fresh}.")
    ]
    later = proposing("b.txt", fresh)
    continued = [
        *given,
        later,
        ChatMessageTool(id="result-b", content="b", tool_call_id=fresh),
    ]
    events: list[Event] = solving(
        [
            made("lost", start, proposing("a.txt", "null"), ids=[fresh]),
            SpanBeginEvent(id="agent-b", name="agent b", type="agent"),
            made("b", given, later, "agent-b", bridged=other == "bridged"),
            made(
                "b-done",
                continued,
                ChatMessageAssistant(content="done"),
                "agent-b",
                bridged=other == "bridged",
            ),
            SpanEndEvent(id="agent-b"),
            made(
                "c",
                [*continued, ChatMessageUser(content="Go on.")],
                ChatMessageAssistant(content="done"),
            ),
        ]
    )
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    replay = steps_from_events(
        [],
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version="0.3.292", sentinel=False),
    )
    bridged_steps = [
        (s.stage, s.id, resulted(s).id if s.stage == "tool_result" else None)
        for s in replay
        if s.stage.startswith("tool") and s.id.startswith(("lost/", "b/"))
    ]
    assert bridged_steps == [
        ("tool_call", f"lost/{fresh}", None),
        *(
            [
                ("tool_call", f"b/{fresh}", None),
                ("tool_result", f"b/{fresh}", "result-b"),
            ]
            if other == "bridged"
            else []
        ),
    ]


def test_agent_tool_call_ids_that_don_t_match_the_calls_skip_their_steps(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # a model call whose recorded ids aren't one per call: replay can't tell
    # which id the agent received for which call, so it skips that model
    # call's tool steps and names it in a warning; other calls are unchanged
    log, _ = scaffold_log(
        "asyncio",
        monkeypatch,
        r7_tool_calls(read("a.txt", "read_1")),
        r7_tool_calls(read("b.txt", "read_2")),
    )
    sample = logged_sample(log)
    made = [
        e
        for e in sample.events
        if isinstance(e, ModelEvent) and e.requested_model is not None
    ]
    events: list[Event] = [
        e.model_copy(update={"agent_tool_call_ids": ["x", "y"]}) if e is made[1] else e
        for e in sample.events
    ]
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        replay = replay_events(log, events)
    assert [(s.stage, s.id) for s in bridged_steps(log, replay)] == [
        ("tool_call", f"{made[0].uuid}/read_1"),
        ("tool_result", f"{made[0].uuid}/read_1"),
    ]
    [warning] = replay_warnings(caplog)
    assert repr(made[1].uuid) in warning
    assert "agent_tool_call_ids" in warning


@agent(name="history_scaffold")
def history_scaffold(history_id: str, side: bool) -> Agent:
    """An OpenAI-client tool loop, bridged with `CompactionEdit` keeping one result, whose first request already holds a call under `history_id` and its result (a history the agent started with); with `side`, it sends a request with its own history and no tools first, as a title request does. It answers each call with `t<turn>:<call id>`."""

    async def execute(state: AgentState) -> AgentState:
        from openai import AsyncOpenAI

        tools: list[Any] = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            }
        ]
        compaction = CompactionEdit(threshold=COMPACTED_AT_TWO, keep_tool_uses=1)
        async with agent_bridge(state, compaction=compaction) as bridge:
            messages: list[Any] = [
                {"role": "user", "content": "What is 1 + 1?"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": history_id,
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps({"path": "history.txt"}),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": history_id,
                    "content": f"history{PADDING}",
                },
            ]
            async with AsyncOpenAI(api_key="sk-test") as client:
                if side:
                    await client.chat.completions.create(
                        model="inspect",
                        messages=[{"role": "user", "content": "Name this."}],
                    )
                for turn in range(3):
                    completion = await client.chat.completions.create(
                        model="inspect", messages=messages, tools=tools
                    )
                    message = completion.choices[0].message
                    messages.append(message.model_dump(exclude_none=True))
                    if not message.tool_calls:
                        break
                    for call in message.tool_calls:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": f"t{turn}:{call.id}{PADDING}",
                            }
                        )
        return bridge.state

    return execute


@pytest.mark.parametrize("side", [False, True], ids=["first", "after_side"])
@pytest.mark.parametrize("history_id", ["null", "call_0"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_call_under_an_id_the_starting_history_holds_takes_its_own_result(
    history_id: str,
    side: bool,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the agent starts from a history with a call under `history_id` and its
    # result, and the model proposes one call under "null"; compaction
    # replaces the history's result in the next request. Under "null", the
    # bridge hands the call over under a fresh id and records it, so the call
    # has its own result under that id and doesn't take the removed result.
    # Under another id, the call keeps its id and its result. With `side`, a
    # request with its own history comes first
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(history_scaffold(history_id, side)),
    )
    [log] = eval(
        task,
        model=generated_ids(None, r7_tool_calls(read("a.txt", "null")), done()),
    )
    assert log.status == "success", log.error
    made = [
        e
        for e in logged_sample(log).events
        if isinstance(e, ModelEvent) and e.requested_model is not None and e.tools
    ]
    uuids = [e.uuid for e in made]
    [last] = [
        [(m.tool_call_id, m.text) for m in e.input if isinstance(m, ChatMessageTool)]
        for e in made[1:]
    ]
    assert last[0] == (history_id, TOOL_RESULT_REMOVED)
    assert (last[1][0] == "null") == (history_id != "null")
    for inputs in ["expanded", "pooled"]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replayed_inputs(log, inputs)
        steps = bridged_steps(log, replay)
        assert [(s.stage, uuids.index(s.id.split("/")[0])) for s in steps] == [
            ("tool_call", 0),
            ("tool_result", 0),
        ], inputs
        assert (called(steps[0]).id == "null") == (history_id != "null")
        assert resulted(steps[1]).text == f"t0:{called(steps[1]).id}{PADDING}"
        assert replay_warnings(caplog) == []


@pytest.mark.parametrize("by", ["sentinel", "approver"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_rejected_call_shows_its_rejection_as_its_result(
    by: str,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the bridge hands neither call of the response over: it tells the model
    # the rejected call was rejected and its sibling was not run, and
    # generates again, so the next request carries a result for each
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log, _ = scaffold_log(
            backend,
            monkeypatch,
            r7_tool_calls(read("a.txt", "read_1"), read("b.txt", "read_2")),
            r7_tool_calls(read("c.txt", "read_3")),
            scaffold=openai_scaffold(
                approval=[ApprovalPolicy(rejecting_approver(1), "*")]
                if by == "approver"
                else None
            ),
            sentinel=[bridge_reject_nth(1)] if by == "sentinel" else (),
        )
        live = [
            (e.stage, e.step_id)
            for e in logged_sample(log).events
            if isinstance(e, SentinelEvent)
            and e.path == "r7_probe"
            and e.stage.startswith("tool")
        ]
        replay = replayed(log)
    rebuilt = assert_bridged_steps_follow_the_conversation(log, replay)
    assert [(s.stage, s.id.split("/")[1]) for s in rebuilt] == [
        ("tool_call", "read_1"),
        ("tool_call", "read_2"),
        ("tool_result", "read_1"),
        ("tool_result", "read_2"),
        ("tool_call", "read_3"),
        ("tool_result", "read_3"),
    ]
    rejected, sibling = [resulted(s).error for s in rebuilt[2:4]]
    assert rejected is not None and rejected.message.startswith("Denied.")
    assert sibling is not None and "was not executed" in sibling.message
    # live had no result step for either
    assert ("tool_result", "read_1") not in live
    assert ("tool_result", "read_2") not in live
    assert replay_warnings(caplog) == []


@protocol
def bridge_modifies_paths() -> Protocol:
    """Modifies every `read_file` call to read `modified.txt`."""

    async def decide(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        return Decision(
            action="modify",
            modified=replace(step.call, arguments={"path": "modified.txt"}),
        )

    return decide


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_modified_call_shows_as_the_model_wrote_it(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log, seen = scaffold_log(
            backend,
            monkeypatch,
            r7_tool_calls(read("a.txt", "read_1")),
            sentinel=[bridge_modifies_paths()],
        )
        # live's result step shows the call the sentinel's modify gave the
        # agent; replay's shows the model's
        replay = assert_replay_rebuilds_bridge_steps(
            log, seen, bridge_differences=["tool_result.call", "tool_result.view"]
        )
    rebuilt = assert_bridged_steps_follow_the_conversation(log, replay)
    assert [(s.stage, called(s).arguments) for s in rebuilt] == [
        ("tool_call", {"path": "a.txt"}),
        ("tool_result", {"path": "a.txt"}),
    ]
    [live] = [step for step in seen.values() if isinstance(step, AfterToolCall)]
    assert live.call.arguments == {"path": "modified.txt"}
    assert bridged_call_ids(log, replay) == ["read_1"]
    assert replay_warnings(caplog) == []


async def redact_results(
    model: Model,
    messages: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: Any,
    config: GenerateConfig,
) -> GenerateInput:
    """A request filter that rewrites every tool message, keeping its id."""
    return GenerateInput(
        [
            m.model_copy(update={"content": "[redacted]"})
            if isinstance(m, ChatMessageTool)
            else m
            for m in messages
        ],
        tools,
        tool_choice,
        config,
    )


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_result_a_request_filter_rewrote_shows_as_rewritten(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log, seen = scaffold_log(
            backend,
            monkeypatch,
            r7_tool_calls(read("a.txt", "read_1")),
            scaffold=openai_scaffold(filter=redact_results),
        )
        # live checked the result the scaffold sent; the model received the
        # filter's rewrite
        replay = assert_replay_rebuilds_bridge_steps(
            log, seen, bridge_differences=["tool_result.result"]
        )
    [result] = [s for s in bridged_steps(log, replay) if s.stage == "tool_result"]
    [live] = [step for step in seen.values() if isinstance(step, AfterToolCall)]
    assert (live.result.text, resulted(result).text) == (
        "file contents",
        "[redacted]",
    )
    assert_bridged_steps_follow_the_conversation(log, replay)
    assert bridged_call_ids(log, replay) == ["read_1"]
    assert replay_warnings(caplog) == []


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_call_a_token_limit_kept_from_the_agent_has_a_tool_call_step(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the model call records its output, then reaches the limit: the bridge
    # never hands the call over, and live never checked it
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log, _ = scaffold_log(
            backend,
            monkeypatch,
            r7_tool_calls(read("a.txt", "read_1")),
            token_limit=1,
        )
        replay = replayed(log)
    events = logged_sample(log).events
    [turn] = [e for e in events if isinstance(e, ModelEvent)]
    # live checked only the model call's input; its model_output step is
    # replay's for a recorded output, as without a bridge
    assert [
        (e.stage, e.step_id)
        for e in events
        if isinstance(e, SentinelEvent) and e.path == "r7_probe"
    ] == [("model_input", turn.uuid)]
    assert [(s.stage, s.id) for s in replay] == [
        ("model_input", turn.uuid),
        ("model_output", turn.uuid),
        ("tool_call", f"{turn.uuid}/read_1"),
    ]
    assert logged_sample(log).limit is not None
    assert_bridged_steps_follow_the_conversation(log, replay)
    # the sentinel checked no bridged call, so nothing can differ from it
    assert replay_warnings(caplog) == []


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_result_a_message_limit_kept_from_the_model_has_no_step(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # live checked the call and its result; the limit then ended the sample
    # before the request carrying the result reached the model
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log, seen = scaffold_log(
            backend,
            monkeypatch,
            r7_tool_calls(read("a.txt", "read_1")),
            message_limit=3,
        )
        live = [
            (e.stage, e.step_id)
            for e in logged_sample(log).events
            if isinstance(e, SentinelEvent)
            and e.path == "r7_probe"
            and e.stage.startswith("tool")
        ]
        replay = assert_replay_rebuilds_bridge_steps(log, seen, unbuilt=1)
    assert live == [("tool_call", "read_1"), ("tool_result", "read_1")]
    assert [s.stage for s in bridged_steps(log, replay)] == ["tool_call"]
    assert logged_sample(log).limit is not None
    assert bridged_call_ids(log, replay) == ["read_1"]
    assert replay_warnings(caplog) == []


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_calls_under_one_id_in_one_bridged_response_are_skipped_with_a_warning(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    log, _ = scaffold_log(
        backend,
        monkeypatch,
        r7_tool_calls(read("a.txt", "dup"), read("b.txt", "dup")),
        sentinel=None,
    )
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    assert [s.stage for s in replay] == ["model_input", "model_output"] * 2
    assert replay_warnings(caplog) == [
        "Replay skipped the tool steps of bridged call(s) 'dup': the model "
        "response proposed several calls under each id."
    ]


def without_message_ids(events: Sequence[Event]) -> list[Event]:
    """The events as a log from before `ToolEvent.call_message_id` (#6143) records them."""
    return [
        e.model_copy(update={"call_message_id": None})
        if isinstance(e, ToolEvent)
        else e
        for e in events
    ]


def test_a_native_call_reusing_a_bridged_call_id_keeps_its_tool_steps(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, Step] = {}
    log = run_logged(
        [
            as_solver(r7_runs_a_bridged_host_tool(report=True)),
            use_tools(addition()),
            generate(),
        ],
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
            done(),
            r7_tool_calls(
                ToolCall(id="shared", function="addition", arguments={"x": 5, "y": 5})
            ),
            done(),
        ),
        sentinel=[r7_probe(seen, copies=True)],
    )
    live = [
        ((e.stage, e.step_id), seen[e.explanation or ""])
        for e in logged_sample(log).events
        if isinstance(e, SentinelEvent) and e.path == "r7_probe"
    ]
    tools = [
        (key, step.call.arguments)
        for key, step in live
        if isinstance(step, BeforeToolCall | AfterToolCall)
    ]
    assert tools == [
        (("tool_call", "shared"), {"x": 1, "y": 1}),
        (("tool_result", "shared"), {"x": 1, "y": 1}),
        (("tool_call", "shared"), {"x": 5, "y": 5}),
        (("tool_result", "shared"), {"x": 5, "y": 5}),
    ]
    # the bridge's checks are marked, so the native call keeps its own, and
    # the host call's steps are rebuilt under its model call's uuid
    replay = assert_replay_rebuilds_bridge_steps(
        log,
        seen,
        lambda step: step.call.arguments == {"x": 5, "y": 5},
        HOST_DIFFERENCES,
    )
    assert [
        (s.stage, s.id, s.step.call.arguments)
        for s in replay
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
        and s not in bridged_steps(log, replay)
    ] == [
        ("tool_call", "shared", {"x": 5, "y": 5}),
        ("tool_result", "shared", {"x": 5, "y": 5}),
    ]
    assert bridged_call_ids(log, replay) == ["shared"]
    assert replay_warnings(caplog) == []


@solver
def r7_runs_a_native_call_aside() -> Solver:
    """A native call generated and run on a history of its own, so a bridge the sample runs later does not find its id in its state."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        tools = [addition()]
        history: list[ChatMessage] = [ChatMessageUser(content="What is 5 + 5?")]
        output = await get_model().generate(history, tools=tools)
        await execute_tools([*history, output.message], tools)
        return state

    return solve


@pytest.mark.parametrize("host_first", [True, False])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_native_call_keeps_its_id_whether_a_host_call_under_it_ran_first(
    host_first: bool,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # a host call and a native call under one id, each checked at both stages:
    # the native call's steps keep the call id live recorded, whichever ran
    # first, and the host call's are rebuilt under its model call's uuid
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    host = [as_solver(r7_runs_a_bridged_host_tool(report=True))]
    native = [r7_runs_a_native_call_aside()]
    host_outputs = [
        r7_tool_calls(
            ToolCall(
                id="shared",
                function="mcp__host__addition",
                arguments={"x": 1, "y": 1},
            )
        ),
        done(),
    ]
    native_outputs = [
        r7_tool_calls(
            ToolCall(id="shared", function="addition", arguments={"x": 5, "y": 5})
        ),
    ]
    seen: dict[str, Step] = {}
    log = run_logged(
        [*host, *native] if host_first else [*native, *host],
        outputs(
            *(
                [*host_outputs, *native_outputs]
                if host_first
                else [*native_outputs, *host_outputs]
            )
        ),
        sentinel=[r7_probe(seen, copies=True)],
    )
    events = logged_sample(log).events
    ran = [e for e in events if isinstance(e, ToolEvent)]
    assert [(e.id, "bridge" in (e.metadata or {})) for e in ran] == (
        [("shared", True), ("shared", False)]
        if host_first
        else [("shared", False), ("shared", True)]
    )
    live = [
        ((e.stage, e.step_id), seen[e.explanation or ""])
        for e in events
        if isinstance(e, SentinelEvent) and e.path == "r7_probe"
    ]
    host_steps = [
        (("tool_call", "shared"), {"x": 1, "y": 1}),
        (("tool_result", "shared"), {"x": 1, "y": 1}),
    ]
    native_steps = [
        (("tool_call", "shared"), {"x": 5, "y": 5}),
        (("tool_result", "shared"), {"x": 5, "y": 5}),
    ]
    assert [
        (key, step.call.arguments)
        for key, step in live
        if isinstance(step, BeforeToolCall | AfterToolCall)
    ] == ([*host_steps, *native_steps] if host_first else [*native_steps, *host_steps])
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        replay = assert_replay_rebuilds_bridge_steps(
            log,
            seen,
            lambda step: step.call.arguments == {"x": 5, "y": 5},
            HOST_DIFFERENCES,
        )
    # the native call's steps keep the call id, whatever replay does with host steps
    assert [
        (s.stage, s.id, s.step.call.arguments)
        for s in replay
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
        and s.step.call.function == "addition"
    ] == [
        ("tool_call", "shared", {"x": 5, "y": 5}),
        ("tool_result", "shared", {"x": 5, "y": 5}),
    ]
    # the host call's steps are named by its model call, the bridge's first
    host_turn = next(
        e for e in events if isinstance(e, ModelEvent) and e.requested_model
    )
    assert [
        (s.stage, s.id, s.step.call.function, s.step.call.arguments)
        for s in replay
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
        and s.step.call.function != "addition"
    ] == [
        (
            "tool_call",
            f"{host_turn.uuid}/shared",
            "mcp__host__addition",
            {"x": 1, "y": 1},
        ),
        (
            "tool_result",
            f"{host_turn.uuid}/shared",
            "mcp__host__addition",
            {"x": 1, "y": 1},
        ),
    ]
    assert replay_warnings(caplog) == []


def test_a_person_s_decision_at_a_bridge_check_reaches_later_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve", "allowed").install(monkeypatch)
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r7_bridged_scaffold("report")),
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="host",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
            done(),
        ),
        sentinel=[
            r7_probe(seen, copies=True),
            h_ask("tool_call", ["approve", "reject"]),
        ],
    )
    # the person approved the host call at the bridge's check, which replay
    # does not pair with the rebuilt step; the steps after it still see the
    # decision, as live
    replay = assert_replay_rebuilds_bridge_steps(
        log, seen, bridge_differences=HOST_DIFFERENCES
    )
    assert [(s.stage, len(s.step.human_decisions or [])) for s in replay] == [
        ("model_input", 0),
        ("model_output", 0),
        ("tool_call", 0),
        ("tool_result", 1),
        ("model_input", 1),
        ("model_output", 1),
    ]
    assert all(not s.recorded_answers for s in replay)


def r7_tool_calls(*calls: ToolCall) -> ModelOutput:
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="", tool_calls=list(calls)),
                stop_reason="tool_calls",
            )
        ],
    )


@monitor
def r7_waits_for_a_cancel(started: Any) -> MonitorGroup:
    """Waits at its first tool_result step until it is cancelled."""

    async def after(context: Context, step: AfterToolCall) -> Observation | None:
        if not started.is_set():
            started.set()
            await anyio.sleep_forever()
        return None

    return MonitorGroup(after)


@agent
def r7_bridged_scaffold(case: str, started: Any = None) -> Agent:
    """A scaffold whose bridge checks one call's results more than once.

    `report`: a host call's result as the scaffold reports it; `reported_twice`:
    then sent again as MCP content. `reused_id`: two calls the scaffold runs under one model call id.
    `reused_by_host`: a call the scaffold runs, then a host call under its id.
    `retried`: a request whose result check is cancelled, then sent again.
    """

    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )
        from inspect_ai.agent._bridge.sandbox.service import call_tool
        from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge

        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=8080,
            model=None,
            bridged_tools={"host": {"addition": addition()}},
        )
        [served] = bridge.served_tools.values()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "mcp__host__addition",
                    "description": served.description,
                    "parameters": served.parameters.model_dump(exclude_none=True),
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo the text.",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                },
            },
        ]
        messages: list[Any] = [{"role": "user", "content": "What is 1 + 1?"}]

        async def request() -> Any:
            completion = await inspect_completions_api_request(
                {"model": "inspect", "messages": messages, "tools": tools}, None, bridge
            )
            message = completion.choices[0].message
            messages.append(message.model_dump(exclude_none=True))
            return message.tool_calls or []

        [proposed] = await request()
        if case in ("report", "reported_twice"):
            result = await call_tool(bridge)(
                "host", "addition", json.loads(proposed.function.arguments)
            )
            messages.append(
                {"role": "tool", "tool_call_id": proposed.id, "content": str(result)}
            )
            await request()
            if case == "reported_twice":
                messages[2]["content"] = json.dumps(
                    [{"type": "text", "text": str(result)}]
                )
                await request()
        elif case == "reused_id":
            messages.append(
                {"role": "tool", "tool_call_id": proposed.id, "content": "one"}
            )
            [again] = await request()
            messages.append(
                {"role": "tool", "tool_call_id": again.id, "content": "two"}
            )
            await request()
        elif case == "reused_by_host":
            messages.append(
                {"role": "tool", "tool_call_id": proposed.id, "content": "one"}
            )
            [host] = await request()
            result = await call_tool(bridge)(
                "host", "addition", json.loads(host.function.arguments)
            )
            messages.append(
                {"role": "tool", "tool_call_id": host.id, "content": str(result)}
            )
            await request()
        else:
            messages.append(
                {"role": "tool", "tool_call_id": proposed.id, "content": "one"}
            )
            with anyio.CancelScope() as scope:
                async with anyio.create_task_group() as tg:

                    async def cancel() -> None:
                        await started.wait()
                        scope.cancel()

                    tg.start_soon(cancel)
                    await request()
            # the scaffold sends the same request again
            await request()
        return state

    return execute


@pytest.mark.parametrize(
    "case", ["reported_twice", "reused_id", "reused_by_host", "retried"]
)
def test_a_bridge_checking_one_call_id_more_than_once_replays(case: str) -> None:
    echo = ToolCall(id="c1", function="echo", arguments={"text": "one"})
    model = outputs(
        *(
            [
                r7_tool_calls(
                    replace(
                        echo, function="mcp__host__addition", arguments={"x": 1, "y": 1}
                    )
                )
            ]
            if case == "reported_twice"
            else [r7_tool_calls(echo)]
        ),
        *(
            [r7_tool_calls(replace(echo, arguments={"text": "two"}))]
            if case == "reused_id"
            else []
        ),
        *(
            [
                r7_tool_calls(
                    replace(
                        echo, function="mcp__host__addition", arguments={"x": 1, "y": 1}
                    )
                )
            ]
            if case == "reused_by_host"
            else []
        ),
        done(),
        *([done()] if case == "reported_twice" else []),
    )
    started = anyio.Event()
    log = run_logged(
        as_solver(r7_bridged_scaffold(case, started)),
        model,
        sentinel=[
            r7_probe({}),
            *([r7_waits_for_a_cancel(started)] if case == "retried" else []),
        ],
    )
    events = [e for e in logged_sample(log).events if isinstance(e, SentinelEvent)]
    # each check of a step records its events in its own sentinel span
    checks = list(dict.fromkeys((e.stage, e.step_id, e.span_id) for e in events))
    tool_checks = [(stage, id) for stage, id, _ in checks if stage.startswith("tool")]
    if case.startswith("reused"):
        # a reused id is handed over under a fresh one, so each call's steps
        # have their own id
        assert len({id for _, id in tool_checks}) == 2
    else:
        # the bridge checked a step under the call id more than once
        assert len(tool_checks) > len(set(tool_checks))
    # replay rebuilds each call the model wrote, under the id the agent
    # received it under, with the result the model next received under that
    # id, whatever the bridge checked; a reused id's steps are live's checks
    # but the first call's result: the model proposed two calls under c1, so
    # the log doesn't show which a result under c1 answers
    steps = replayed(log)
    generates = [(stage, id) for stage, id, _ in checks if stage.startswith("model")]
    assert [
        (step.stage, step.id) for step in steps if step.stage.startswith("model")
    ] == generates
    rebuilt = bridged_steps(log, steps)
    assert len(rebuilt) == len([s for s in steps if s.stage.startswith("tool")])
    if case.startswith("reused"):
        assert [(s.stage, s.id.split("/")[1]) for s in rebuilt] == [
            check for check in tool_checks if check != ("tool_result", "c1")
        ]
        fresh = tool_checks[-1][1]
        assert fresh != "c1"
    else:
        fresh = "c1"
    assert [(s.stage, s.id.split("/")[1], called(s).arguments) for s in rebuilt] == {
        "reported_twice": [
            ("tool_call", "c1", {"x": 1, "y": 1}),
            ("tool_result", "c1", {"x": 1, "y": 1}),
        ],
        "reused_id": [
            ("tool_call", "c1", {"text": "one"}),
            ("tool_call", fresh, {"text": "two"}),
            ("tool_result", fresh, {"text": "two"}),
        ],
        "reused_by_host": [
            ("tool_call", "c1", {"text": "one"}),
            ("tool_call", fresh, {"x": 1, "y": 1}),
            ("tool_result", fresh, {"x": 1, "y": 1}),
        ],
        "retried": [
            ("tool_call", "c1", {"text": "one"}),
            ("tool_result", "c1", {"text": "one"}),
        ],
    }[case]
    assert [resulted(s).text for s in rebuilt if s.stage == "tool_result"] == {
        "reported_twice": ["2"],
        "reused_id": ["two"],
        "reused_by_host": ["2"],
        "retried": ["one"],
    }[case]


@approver
def r7_bridged_approver(decision: str) -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        if decision == "modify":
            return Approval(
                decision="modify",
                modified=ToolCall(
                    id=call.id, function=call.function, arguments={"x": 2, "y": 1}
                ),
            )
        return Approval(decision="approve")

    return approve


# the names scaffolds declare a bridged host tool by
# (tests/agent/test_bridge_approval.py)
BRIDGED_NAMES = {
    "bare": "addition",
    "claude-code": "mcp__host__addition",
    "gemini-cli": "mcp_host_addition",
    "gemini-cut": "mcp_" + "s" * 26 + "..." + "s" * 20 + "_addition",
    "opencode": "host_addition",
    "codex-hashed": "additio_9f2b038d5e15",
    "dispatcher": "call_mcp_tool",
}


def bridged_approval_log(name: str, decision: str) -> EvalLog:
    seen: dict[str, Step] = {}
    arguments: dict[str, Any] = {"x": 1, "y": 1}
    proposed = (
        call(name, ServerName="host", ToolName="addition", Arguments=arguments)
        if name == "call_mcp_tool"
        else call(name, **arguments)
    )
    return run_logged(
        as_solver(
            r7_runs_a_bridged_host_tool(
                name, [ApprovalPolicy(r7_bridged_approver(decision), "*")]
            )
        ),
        outputs(proposed),
        sentinel=[r7_probe(seen)],
    )


def replay_inputs(
    log: EvalLog, events: Sequence[Event], inputs: str, **kwargs: Any
) -> list["ReplayStep"]:
    from inspect_ai._sentinel import _replay

    sample = logged_sample(log)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    return steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
        **kwargs,
    )


# since #6192 the bridge reviews a call under the host tool's name; before it,
# under the scaffold's (`test_an_older_bridged_approval_under_the_scaffold_s_name_replays`)
REVIEWS_AS_HOST_TOOL = hasattr(AgentBridge, "reviewed_calls")


def assert_bridged_approval_replays(log: EvalLog, decision: str) -> ToolCall:
    """Assert the host tool ran the approved call, and replay rebuilds its `tool_call` step as the model wrote the call, with no approver's modify; return the approved call."""
    events = logged_sample(log).events
    [approval] = [e for e in events if isinstance(e, ApprovalEvent)]
    [ran] = [e for e in events if isinstance(e, ToolEvent)]
    approved = approval.modified or approval.call
    assert approval.decision == decision
    assert ran.metadata is not None and ran.metadata["bridge"]["grant"] == "consumed"
    assert ran.error is None
    assert ran.arguments == approved.arguments
    assert ran.function == "addition"
    live = [e.stage for e in events if isinstance(e, SentinelEvent)]
    # the bridge checks the call it runs (an older log has no such checks);
    # replay shows the call as the model wrote it, and no result, as no later
    # request carries one
    assert live[:2] == ["model_input", "model_output"]
    assert live[2:] in ([], ["tool_call"])
    [turn] = [e for e in events if isinstance(e, ModelEvent)]
    steps = replayed(log)
    expected = [(step.stage, step.id) for step in steps]
    assert [stage for stage, _ in expected] == [*live[:2], "tool_call"]
    assert [called(steps[2])] == turn.output.message.tool_calls
    for inputs in ["expanded", "pooled"]:
        for recorded in [events, without_origins(events)]:
            replay = replay_inputs(log, recorded, inputs)
            assert [(step.stage, step.id) for step in replay] == expected
    return approved


@pytest.mark.parametrize("decision", ["approve", "modify"])
@pytest.mark.parametrize("scaffold", list(BRIDGED_NAMES))
def test_an_approved_bridged_host_tool_call_replays(
    scaffold: str, decision: str
) -> None:
    name = BRIDGED_NAMES[scaffold]
    approved = assert_bridged_approval_replays(
        bridged_approval_log(name, decision), decision
    )
    host_name = name == "call_mcp_tool" or REVIEWS_AS_HOST_TOOL
    assert approved.function == ("addition" if host_name else name)


@pytest.mark.parametrize("decision", ["approve", "modify"])
def test_an_older_bridged_approval_under_the_scaffold_s_name_replays(
    decision: str,
) -> None:
    """Inspect through 0.3.286 recorded a bridged call's approval under the scaffold's name, and the host tool's `ToolEvent` under the tool's."""
    path = (
        Path(__file__).parent
        / "fixtures"
        / f"bridged_approval_scaffold_name_{decision}.json"
    )
    log = read_eval_log(str(path))
    approved = assert_bridged_approval_replays(log, decision)
    assert approved.function == "mcp__host__addition"


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_a_native_tool_event_with_a_bridged_approvals_name_is_refused(
    inputs: str,
) -> None:
    """Without `metadata["bridge"]`, the scaffold's name in the approval is a call the `ToolEvent` does not record."""
    log = bridged_approval_log("mcp__host__addition", "modify")

    def native(event: Event) -> Event:
        if isinstance(event, ToolEvent):
            return event.model_copy(update={"metadata": None})
        if isinstance(event, ApprovalEvent):
            assert event.modified is not None
            name = "mcp__host__addition"
            return event.model_copy(
                update={
                    "call": replace(event.call, function=name),
                    "modified": replace(event.modified, function=name),
                }
            )
        return event

    events = [native(e) for e in logged_sample(log).events]
    with pytest.raises(
        ValueError, match=r"approved call does not match the ToolEvent that ran"
    ):
        replay_inputs(log, events, inputs)


@pytest.mark.parametrize("tool_event", [True, False])
def test_a_bridged_approval_reaches_the_requests_before_its_call_runs(
    tool_event: bool,
) -> None:
    """The bridge approves a call when the model proposes it and the scaffold may run it after later requests, so those requests' steps carry the person's decision."""
    log = run_logged(
        as_solver(
            r7_runs_a_bridged_host_tool(
                approval=[ApprovalPolicy(r7_bridged_approver("approve"), "*")],
                request_before_running=True,
            )
        ),
        outputs(call("mcp__host__addition", x=1, y=1), done()),
    )
    events = logged_sample(log).events
    [approval] = [e for e in events if isinstance(e, ApprovalEvent)]
    [ran] = [e for e in events if isinstance(e, ToolEvent)]
    assert ran.metadata is not None and ran.metadata["bridge"]["grant"] == "consumed"
    turns = [e for e in events if isinstance(e, ModelEvent)]
    assert len(turns) == 2
    assert events.index(approval) < events.index(turns[1]) < events.index(ran)
    if not tool_event:
        events = [e for e in events if e is not ran]
    for inputs in ["expanded", "pooled"]:
        for recorded in [events, without_origins(events)]:
            replay = replay_inputs(
                log, recorded, inputs, human_approvers=(approval.approver,)
            )
            # the call's tool_call step comes right after its model call's
            # output, before the bridge's approval; no request carries a result
            assert [(s.stage, s.id) for s in replay] == [
                ("model_input", turns[0].uuid),
                ("model_output", turns[0].uuid),
                ("tool_call", f"{turns[0].uuid}/{approval.call.id}"),
                ("model_input", turns[1].uuid),
                ("model_output", turns[1].uuid),
            ]
            assert not replay[2].step.human_decisions
            for step in replay[3:]:
                decisions = step.step.human_decisions or []
                assert [(d.step_id, d.decided.report.action) for d in decisions] == [
                    (approval.call.id, "proceed")
                ], (inputs, step.stage)


class _Overlap:
    first_waiting: anyio.Event
    second_proposed: anyio.Event


@approver
def r7_first_approver() -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        _Overlap.first_waiting.set()
        await _Overlap.second_proposed.wait()
        return Approval(decision="approve")

    return approve


@approver
def r7_second_approver() -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        _Overlap.second_proposed.set()
        return Approval(
            decision="modify",
            modified=ToolCall(
                id=call.id, function=call.function, arguments={"x": 2, "y": 1}
            ),
        )

    return approve


@solver
def r7_two_bridged_agents_overlap() -> Solver:
    """The first agent awaits approval of its call while the second proposes its own."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        first = r7_runs_a_bridged_host_tool(
            approval=[ApprovalPolicy(r7_first_approver(), "*")],
            request_before_running=True,
        )
        second = r7_runs_a_bridged_host_tool(
            approval=[ApprovalPolicy(r7_second_approver(), "*")],
            request_before_running=True,
        )

        async def run_first() -> None:
            await run(first, "What is 1 + 1?")

        async def run_second() -> None:
            await _Overlap.first_waiting.wait()
            await run(second, "What is 1 + 1?")

        await tg_collect([run_first, run_second])
        return state

    return solve


@pytest.mark.parametrize("shared_id", [True, False])
@pytest.mark.parametrize("tool_event", [True, False])
def test_concurrent_bridged_approvals_reach_their_own_agents(
    tool_event: bool, shared_id: bool, caplog: pytest.LogCaptureFixture
) -> None:
    _Overlap.first_waiting = anyio.Event()
    _Overlap.second_proposed = anyio.Event()
    proposed = [
        ModelOutput.for_tool_call(
            "mockllm/model",
            tool_name="mcp__host__addition",
            tool_arguments={"x": 1, "y": 1},
            tool_call_id="call_0" if shared_id else f"call_{agent}",
        )
        for agent in range(2)
    ]
    log = run_logged(
        r7_two_bridged_agents_overlap(),
        outputs(*proposed, done(), done()),
    )
    events = logged_sample(log).events
    first, second = [e for e in events if isinstance(e, ApprovalEvent)][::-1]
    assert first.approver == "r7_first_approver"
    assert (first.call.id == second.call.id) == shared_id
    turns = [e for e in events if isinstance(e, ModelEvent)]
    assert len(turns) == 4
    agents = {turn.uuid: turn.span_id for turn in turns}
    # the first agent's approval is recorded after the second's proposal
    assert events.index(turns[1]) < events.index(first)
    assert [turns[0].span_id, turns[1].span_id] == [first.span_id, second.span_id]
    ran = [e for e in events if isinstance(e, ToolEvent)]
    assert len(ran) == 2
    if not tool_event:
        events = [e for e in events if e not in ran]
    expected = {
        approval.span_id: [(approval.call.id, action)]
        for approval, action in [(first, "proceed"), (second, "modify")]
    }
    approvers = (first.approver, second.approver)
    for inputs in ["expanded", "pooled"]:
        for recorded in [events, without_origins(events)]:
            replay = replay_inputs(log, recorded, inputs, human_approvers=approvers)
            # each agent's call has a tool_call step, right after its model
            # call's output and before its approval
            assert len(replay) == 10
            for step in replay:
                decisions = step.step.human_decisions or []
                made_by = step.id.split("/")[0]
                assert [(d.step_id, d.decided.report.action) for d in decisions] == (
                    []
                    if made_by in (turns[0].uuid, turns[1].uuid)
                    else expected[agents[made_by]]
                ), (inputs, step.stage)
    if not shared_id:
        return
    # recorded outside both agents, the first approval is left unpublished
    outside = [
        e.model_copy(update={"span_id": None}) if e is first else e for e in events
    ]
    replay = replay_inputs(log, outside, "expanded", human_approvers=approvers)
    later = [
        s for s in replay if s.id.split("/")[0] not in (turns[0].uuid, turns[1].uuid)
    ]
    assert len(later) == 4
    for step in later:
        decisions = step.step.human_decisions or []
        assert [(d.step_id, d.decided.report.action) for d in decisions] == (
            expected[second.span_id] if agents[step.id] == second.span_id else []
        )
    assert "Skipped the human decisions on call(s) 'call_0'" in caplog.text


class _Interleave:
    native_approved: anyio.Event
    other_approved: anyio.Event


@approver
def r7_other_approver(decision: str = "approve") -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        _Interleave.other_approved.set()
        return Approval(decision="reject" if decision == "reject" else "approve")

    return approve


@monitor
def r7_holds_the_native_call() -> MonitorGroup:
    async def before_call(context: Context, step: BeforeToolCall) -> Observation | None:
        if not _Interleave.native_approved.is_set():
            _Interleave.native_approved.set()
            await _Interleave.other_approved.wait()
        return None

    return MonitorGroup(before_call)


@solver
def r7_native_call_held_across_another_agent(other: str) -> Solver:
    """A native agent's approved call waits to run while another agent (bridged, or native and refused) proposes and is approved a call with the same id."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        native = react(
            tools=[addition()],
            approval=[ApprovalPolicy(d3_approver([], "modify", x=2), "*")],
            submit=False,
        )
        second = (
            r7_runs_a_bridged_host_tool(
                approval=[ApprovalPolicy(r7_other_approver(), "*")]
            )
            if other == "bridge"
            else react(
                tools=[addition()],
                approval=[ApprovalPolicy(r7_other_approver("reject"), "*")],
                submit=False,
            )
        )

        async def run_native() -> None:
            await run(native, "What is 1 + 1?")

        async def run_other() -> None:
            await _Interleave.native_approved.wait()
            await run(second, "What is 1 + 1?")

        await tg_collect([run_native, run_other])
        return state

    return solve


@pytest.mark.parametrize("other", ["bridge", "native"])
def test_a_native_call_takes_only_its_own_agent_s_approval(other: str) -> None:
    _Interleave.native_approved = anyio.Event()
    _Interleave.other_approved = anyio.Event()
    proposed = [
        ModelOutput.for_tool_call(
            "mockllm/model",
            tool_name=name,
            tool_arguments={"x": 1, "y": 1},
            tool_call_id="call_0",
        )
        for name in [
            "addition",
            "mcp__host__addition" if other == "bridge" else "addition",
        ]
    ]
    log = run_logged(
        r7_native_call_held_across_another_agent(other),
        outputs(*proposed, done(), done()),
        sentinel=[r7_holds_the_native_call()],
    )
    events = logged_sample(log).events
    native_approval, other_approval = [
        e for e in events if isinstance(e, ApprovalEvent)
    ]
    assert native_approval.decision == "modify"
    assert other_approval.call.id == "call_0"
    native_turn, other_turn = [e for e in events if isinstance(e, ModelEvent)][:2]
    [ran] = [
        e
        for e in events
        if isinstance(e, ToolEvent)
        and not e.error
        and "bridge" not in (e.metadata or {})
    ]
    assert ran.arguments == {"x": 2, "y": 1}
    # the other agent proposes and is approved the id while the native call waits
    assert (
        events.index(native_approval)
        < events.index(other_turn)
        < events.index(other_approval)
        < events.index(ran)
    )
    for inputs in ["expanded", "pooled"]:
        for recorded in [events, without_origins(events)]:
            replay = replay_inputs(log, recorded, inputs)
            [generate] = [
                s
                for s in replay
                if s.id == native_turn.uuid and s.stage == "model_input"
            ]
            # the native call's steps; a bridged call's are rebuilt apart
            tool_steps = [
                s
                for s in replay
                if s.stage.startswith("tool") and s not in bridged_steps(log, replay)
            ]
            assert [s.stage for s in tool_steps] == ["tool_call", "tool_result"]
            for replayed_step in tool_steps:
                step = replayed_step.step
                assert isinstance(step, BeforeToolCall | AfterToolCall)
                assert step.conversation == generate.step.conversation
                assert step.message_id == native_turn.output.message.id
                assert step.call.arguments == {"x": 2, "y": 1}


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_approvals_of_a_reused_call_id_replay_in_linear_work(
    inputs: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # after Ransom's 35th review: each approval found its proposal by
    # rescanning every earlier proposal of its id
    from inspect_ai._sentinel import _replay

    conversation = _replay._Driver._conversation
    work: list[int] = []

    def counting_conversation(self: Any, event: Event) -> str:
        work[-1] += 1
        return conversation(self, event)

    monkeypatch.setattr(_replay._Driver, "_conversation", counting_conversation)
    for turns in (100, 200, 400):
        events: list[Event] = [
            SpanBeginEvent(id=agent, name=agent, type="agent") for agent in "ab"
        ]
        for n in range(turns):
            agent = "ab"[n % 2]
            proposed = ToolCall(id="call_0", function="lookup", arguments={"n": n})
            turn = imported_call(
                f"model-{n}", [ChatMessageUser(content=f"turn {n}")], agent, proposed
            )
            events += [
                turn.model_copy(update={"origin": "agent"}),
                ApprovalEvent(
                    message="",
                    call=proposed,
                    approver="auto",
                    decision="approve",
                    span_id=agent,
                ),
                ToolEvent(
                    id="call_0",
                    function="lookup",
                    arguments={"n": n},
                    result="found",
                    metadata={"bridge": "host"},
                    span_id=agent,
                ),
            ]
        events += [SpanEndEvent(id=agent) for agent in "ab"]
        events = solving(events)
        pool: list[ChatMessage] = []
        if inputs == "pooled":
            events, pool = _replay._condensed(events, [])
        work.append(0)
        replay = steps_from_events(
            [],
            events,
            pool,
            sample_uuid="sample",
            eval_info=EvalInfo(inspect_ai_version="0.3.300", sentinel=False),
            human_approvers=(),
        )
        assert len([s for s in replay if s.stage == "model_input"]) == turns
        assert work[-1] <= 5 * turns, work
    assert work[-1] <= 4.2 * work[0], work


class CountedCalls(list[ToolCall]):
    """A message's tool calls, counting each one read (`reads`)."""

    def __init__(self, calls: Iterator[ToolCall]) -> None:
        super().__init__(calls)
        self.reads = 0

    def __iter__(self) -> Iterator[ToolCall]:
        for call in super().__iter__():
            self.reads += 1
            yield call


@pytest.mark.parametrize("proposed", ["generated", "prefilled"])
def test_a_wide_batch_of_calls_finds_its_proposals_in_linear_work(
    proposed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # after the PR C review: each tool event found its call by scanning every
    # call of the message its event names
    from inspect_ai._sentinel import _replay

    owner, lookup = (
        (_replay._Proposals, "named")
        if proposed == "generated"
        else (_replay._Driver, "_prefilled_by_id")
    )
    by_id = getattr(owner, lookup)
    found: list[int] = []

    def counting_lookup(self: Any, *args: Any) -> Any:
        result = by_id(self, *args)
        if result:
            found[-1] += 1
        return result

    monkeypatch.setattr(owner, lookup, counting_lookup)
    reads: list[int] = []
    for width in (8, 16, 32, 64):
        calls = CountedCalls(
            ToolCall(id=f"call-{n}", function="lookup", arguments={"n": n})
            for n in range(width)
        )
        found.append(0)
        message = ChatMessageAssistant(id="assistant", content="", tool_calls=[])
        object.__setattr__(message, "tool_calls", calls)
        events: list[Event] = []
        if proposed == "generated":
            turn = imported_call(
                "turn", [ChatMessageUser(content="Look up.")], "solvers"
            )
            turn.output.choices[0].message = message
            offered = [ToolInfo(name="lookup", description="Look up an item.")]
            events.append(turn.model_copy(update={"origin": "agent", "tools": offered}))
        for n in range(width):
            events += [
                SpanBeginEvent(id=f"tool-{n}", name="lookup", type="tool"),
                ToolEvent(
                    id=f"call-{n}",
                    function="lookup",
                    arguments={"n": n},
                    result="found",
                    call_message_id="assistant",
                    span_id=f"tool-{n}",
                ),
                SpanEndEvent(id=f"tool-{n}"),
            ]
        replay = steps_from_events(
            [message] if proposed == "prefilled" else [],
            solving(events),
            [],
            sample_uuid="sample",
            eval_info=EvalInfo(inspect_ai_version="0.3.300", sentinel=False),
        )
        tools = [s for s in replay if s.stage.startswith("tool")]
        assert len(tools) == 2 * width
        # each call is found by the id its event records, not by position
        assert found[-1] == width
        reads.append(calls.reads)
        assert calls.reads <= 3 * width, (width, reads)
    assert reads[-1] <= 8.8 * reads[0], reads


@pytest.mark.parametrize("tool_events", ["none", "bridge", "native"])
@pytest.mark.parametrize("case", ["shared", "distinct_ids", "separate_spans"])
def test_a_stored_timeline_s_conversation_owns_its_approval(
    case: str, tool_events: str
) -> None:
    # after Ransom's 36th review: an approval and a ToolEvent took the latest
    # proposal of their span, though a stored timeline put it in another
    # conversation
    from inspect_ai._sentinel import _replay

    spans = {"a": "agent", "b": "other" if case == "separate_spans" else "agent"}
    ids = {"a": "call_0", "b": "call_1" if case == "distinct_ids" else "call_0"}
    calls = {c: ToolCall(id=ids[c], function="lookup", arguments={}) for c in "ab"}
    tasks = {c: ChatMessageUser(content=f"Task {c}.") for c in "ab"}
    first = {
        c: linked_call(
            f"{c}1", spans[c], [tasks[c]], f"Look up {c}.", "agent", calls[c]
        )
        for c in "ab"
    }
    for c in "ab":
        first[c].tools = [ToolInfo(name="lookup", description="Find it")]
    approval = ApprovalEvent(
        uuid="a-approval",
        message="",
        call=calls["a"],
        approver="human",
        decision="approve",
        span_id=spans["a"],
    )
    ran = {
        c: ToolEvent(
            uuid=f"{c}-tool",
            id=ids[c],
            function="lookup",
            arguments={},
            result="found",
            # B's call runs on the host: two native calls of one id are refused
            metadata=None
            if tool_events == "native" and c == "a"
            else {"bridge": "host"},
            span_id=spans[c],
        )
        for c in "ab"
    }
    second = {
        c: linked_call(
            f"{c}2",
            spans[c],
            [
                tasks[c],
                first[c].output.message,
                ChatMessageTool(content="found", tool_call_id=ids[c]),
            ],
            "Done.",
            "agent",
        )
        for c in "ab"
    }
    running: list[Event] = []
    if tool_events != "none":
        for c in "ab":
            running += [
                SpanBeginEvent(
                    id=f"{c}-tool-span",
                    name="lookup",
                    type="tool",
                    parent_id=spans[c],
                ),
                ran[c],
                SpanEndEvent(id=f"{c}-tool-span"),
            ]
    agent_spans = sorted(set(spans.values()))
    events = solving(
        [
            *[SpanBeginEvent(id=s, name=s, type="agent") for s in agent_spans],
            first["a"],
            first["b"],
            approval,
            *running,
            second["a"],
            second["b"],
            *[SpanEndEvent(id=s) for s in agent_spans],
        ]
    )
    in_a: list[Event] = [first["a"], approval, ran["a"], second["a"]]
    in_b: list[Event] = [first["b"], ran["b"], second["b"]]
    stored = Timeline(
        name="target",
        description="",
        root=TimelineSpan(
            id="a",
            name="a",
            content=[TimelineEvent(event=e) for e in in_a],
            branches=[
                TimelineSpan(
                    id="b",
                    name="b",
                    content=[TimelineEvent(event=e) for e in in_b],
                )
            ],
        ),
    )
    tool_ids = {c: ran[c].id for c in "ab"}
    for inputs in ["expanded", "pooled"]:
        for recorded in [events, without_origins(events)]:
            pool: list[ChatMessage] = []
            if inputs == "pooled":
                recorded, pool = _replay._condensed(recorded, [])
            replay = steps_from_events(
                [],
                recorded,
                pool,
                sample_uuid="sample",
                eval_info=EvalInfo(inspect_ai_version="0.3.300", sentinel=False),
                timeline=stored,
                human_approvers=("human",),
            )
            assert {"a2", "b2"} <= {s.id for s in replay}, (inputs, case)
            tool_steps = [s for s in replay if s.stage.startswith("tool")]
            assert len(tool_steps) == (2 if tool_events == "native" else 0)
            for step in replay:
                conversation = step.step.conversation
                decisions = [
                    (d.step_id, d.decided.report.action)
                    for d in step.step.human_decisions or []
                ]
                if step.stage.startswith("tool"):
                    assert isinstance(step.step, BeforeToolCall | AfterToolCall)
                    assert step.step.message_id == (
                        first[conversation].output.message.id
                    )
                    assert step.id == tool_ids[conversation]
                after_approval = step.id != "a1" and step.stage != "tool_call"
                assert decisions == (
                    [("call_0", "proceed")]
                    if conversation == "a" and after_approval
                    else []
                ), (inputs, case, step.stage, step.id)


def run_logged(
    solver: Solver | list[Solver],
    model: Any,
    *,
    inferred: str | None = None,
    **task_kwargs: Any,
) -> EvalLog:
    """Run the eval, and check that its steps replayed with the turns inferred are those replayed with the recorded origins, unless `inferred` names why they differ."""
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=solver,
        **task_kwargs,
    )
    log = eval(task, model=model)[0]
    assert log.status == "success", log.error
    assert_inferred(log, replay_events(log, logged_sample(log).events), inferred)
    return log


def logged_sample(log: EvalLog) -> EvalSample:
    assert log.location
    [sample] = read_eval_log(log.location, resolve_attachments="full").samples or []
    return sample


def replay_events(
    log: EvalLog, events: Sequence[Event], **kwargs: Any
) -> list["ReplayStep"]:
    sample = logged_sample(log)
    return steps_from_events(
        sample.messages,
        events,
        [],
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
        **kwargs,
    )


def bridged_uuids(events: Sequence[Event]) -> set[str]:
    """The uuids of the model calls an agent bridge made for its agent (`ModelEvent.requested_model`)."""
    return {
        e.uuid
        for e in events
        if isinstance(e, ModelEvent) and e.requested_model is not None and e.uuid
    }


def bridged_call_id(step: "ReplayStep", uuids: set[str]) -> str | None:
    """The call id of a bridge's rebuilt tool step (named `<model call uuid>/<call id>`), None for any other step."""
    made_by, _, call_id = step.id.partition("/")
    if step.stage.startswith("tool") and made_by in uuids:
        return call_id
    return None


def bridged_steps(log: EvalLog, replay: Sequence["ReplayStep"]) -> list["ReplayStep"]:
    """The bridge's rebuilt tool steps of `replay`."""
    uuids = bridged_uuids(logged_sample(log).events)
    return [s for s in replay if bridged_call_id(s, uuids) is not None]


def bridged_call_ids(log: EvalLog, replay: Sequence["ReplayStep"]) -> list[str]:
    """The call ids of the bridge's rebuilt `tool_call` steps of `replay`, in order."""
    return [
        s.id.partition("/")[2]
        for s in bridged_steps(log, replay)
        if s.stage == "tool_call"
    ]


def assert_exact_results(steps: Sequence["ReplayStep"]) -> None:
    """Assert each bridged `tool_result` step's result is its own call's, where the scaffold answers each call naming the id it received the call under (`t<turn>:<id>`, or `loop<n>:<id>` from `concurrent_scaffold`)."""
    for step in steps:
        if step.stage == "tool_result":
            text = resulted(step).text
            match = re.match(r"(?:t|loop)\d+:(\S+?)(?:\s|$)", text)
            assert match is not None, text
            assert match.group(1) == called(step).id, (text, called(step).id)


def tool_step(step: "ReplayStep") -> BeforeToolCall | AfterToolCall:
    """A replayed tool step's step."""
    assert isinstance(step.step, BeforeToolCall | AfterToolCall), step.stage
    return step.step


def called(step: "ReplayStep") -> ToolCall:
    """The call a replayed tool step shows."""
    assert isinstance(step.step, BeforeToolCall | AfterToolCall), step.stage
    return step.step.call


def resulted(step: "ReplayStep") -> ChatMessageTool:
    """The result a replayed `tool_result` step shows."""
    assert isinstance(step.step, AfterToolCall), step.stage
    return step.step.result


def in_order(keys: Sequence[tuple[str, ...]]) -> list[Any]:
    """`keys` with each run of a bridge's `tool_result` steps as a set: the bridge checks one request's results concurrently, so live can record them in any order."""
    ordered: list[Any] = []
    for key in keys:
        if key[0] == "bridge" and key[1] == "tool_result":
            if ordered and isinstance(ordered[-1], frozenset):
                ordered[-1] = ordered[-1] | {key}
            else:
                ordered.append(frozenset({key}))
        else:
            ordered.append(key)
    return ordered


def assert_replay_rebuilds_bridge_steps(
    log: EvalLog,
    seen: dict[str, Step],
    native: Callable[[Step], bool] = lambda _: False,
    bridge_differences: Sequence[str] = (),
    unbuilt: int = 0,
    extra: int = 0,
) -> list["ReplayStep"]:
    """Rebuild the steps of a log `r7_probe(seen, copies=True)` watched, and compare with live in order: a step other than a bridge's tool step under its id, and a bridge's tool step (a live tool step `native` rejects; replay names it `<model call uuid>/<call id>`) with the live step of its stage and call id, but for the fields `bridge_differences` names (`"stage.field"`). `unbuilt` is the number of the bridge's live tool steps replay has none for, and `extra` the number of its rebuilt tool steps live has none for, each by the definition of a bridge's tool steps."""
    live = [
        (
            ("bridge", e.stage, e.step_id)
            if isinstance(step, BeforeToolCall | AfterToolCall) and not native(step)
            else (e.stage, e.step_id),
            step,
        )
        for e in logged_sample(log).events
        if isinstance(e, SentinelEvent) and e.path == "r7_probe"
        for step in [seen[e.explanation or ""]]
    ]
    replay = replayed(log)
    uuids = bridged_uuids(logged_sample(log).events)
    keyed = [
        (
            (s.stage, s.id)
            if (call_id := bridged_call_id(s, uuids)) is None
            else ("bridge", s.stage, call_id),
            s,
        )
        for s in replay
    ]
    rebuilt = {key for key, _ in keyed}
    shown = {key for key, _ in live}
    assert len([k for k, _ in live if k not in rebuilt]) == unbuilt
    assert len([k for k, _ in keyed if k not in shown]) == extra
    assert all(k[0] == "bridge" for k, _ in [*live, *keyed] if k not in rebuilt & shown)
    assert in_order([k for k, _ in keyed if k in shown]) == in_order(
        [k for k, _ in live if k in rebuilt]
    )
    # a key repeats for a call the bridge handed out twice (a cached retry):
    # its steps pair in order
    by_key: dict[tuple[str, ...], list[ReplayStep]] = {}
    for key, s in keyed:
        by_key.setdefault(key, []).append(s)
    for key, step in live:
        if key in by_key:
            assert_step_equals_live(
                key[-2:],
                by_key[key].pop(0),
                step,
                bridge_differences if key[0] == "bridge" else (),
            )
    return replay


def tool_step_calls(
    replay: list["ReplayStep"],
) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (step.stage, step.step.call.function, step.step.call.arguments)
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ]


UNMATCHED_MODIFY = (
    "Skipped the tool steps of call(s) {}: a sentinel modified each, and its tool "
    "recorded other arguments than the modify gave it, so the log cannot show "
    "the call the sentinel was shown."
)

UNRECORDED_CHECK = (
    "Skipped the tool steps of call(s) {}: a sentinel modified each under a call "
    "id other calls share, and no approval that replay can rely on records the call "
    "as its tool validated it, so the log cannot show the call the sentinel was "
    "shown."
)


def replay_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "inspect_ai._sentinel._replay"
    ]


# a log replay cannot read without guessing fails, naming the rule


def test_two_steps_of_a_stage_with_one_id_fail_the_replay() -> None:
    log = run_logged(tool_loop(addition()), agent_model())
    events = logged_sample(log).events
    tool = next(i for i, e in enumerate(events) if isinstance(e, ToolEvent))
    with pytest.raises(MalformedLogError, match="Two tool_call steps"):
        replay_events(log, [*events[: tool + 1], *events[tool - 1 :]])


def test_a_native_check_no_tool_call_matches_is_settled_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    Panel("approve", "allowed").install(monkeypatch)
    log = run_logged(
        tool_loop(addition()),
        agent_model(),
        sentinel=[h_ask("tool_call", ["approve", "reject"])],
    )
    events = logged_sample(log).events
    [ran] = [e for e in events if isinstance(e, ToolEvent)]
    replay = replay_events(log, [e for e in events if e is not ran])
    assert [step.stage for step in replay] == ["model_input", "model_output"] * 2
    # the person's answer still reaches the next turn
    [decision] = replay[2].step.human_decisions or []
    assert decision.step_id == ran.id
    [warning] = replay_warnings(caplog)
    assert f"call id(s) {ran.id} that match no tool call" in warning


def test_a_span_tree_cycle_fails_the_replay() -> None:
    log = run_logged(tool_loop(addition()), agent_model())
    events = logged_sample(log).events
    first, second = [e for e in events if isinstance(e, SpanBeginEvent)][:2]
    first.parent_id, second.parent_id = second.id, first.id
    with pytest.raises(MalformedLogError, match="cycle"):
        replay_events(log, events)


def test_a_span_tree_cycle_no_step_walks_through_fails_the_replay() -> None:
    log = run_logged(tool_loop(addition()), agent_model())
    events = logged_sample(log).events
    a = SpanBeginEvent(id="a", parent_id="b", name="a")
    b = SpanBeginEvent(id="b", parent_id="a", name="b")
    with pytest.raises(MalformedLogError, match="cycle"):
        replay_events(log, [a, b, *events])


# react with a summary compaction, run by `inspect eval` with inspect_ai 0.3.285,
# which records no ModelEvent.origin: the solver and model of
# test_a_log_from_before_recorded_origins_replays_with_the_timeline_s_turns
OLD_LOG = Path(__file__).parent / "fixtures" / "react_compaction_0.3.285.json"


def react_with_a_summary_compaction() -> tuple[Solver, Any]:
    from inspect_ai.model._compaction.summary import CompactionSummary

    turns = [call("addition", x=turn, y=turn) for turn in range(6)]
    solver = as_solver(
        react(
            tools=[addition()],
            compaction=CompactionSummary(threshold=300),
            submit=False,
        )
    )
    return solver, outputs(*turns, *[done("summary")] * 3, *turns, done())


def test_a_log_from_before_recorded_origins_replays_with_the_timeline_s_turns() -> None:
    old = read_eval_log(str(OLD_LOG), resolve_attachments="full")
    assert old.eval.packages["inspect_ai"] == "0.3.285"
    [sample] = old.samples or []
    models = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert models and all(e.origin is None for e in models)
    inferred = steps_from_events(
        sample.messages,
        sample.events,
        sample.events_data["messages"] if sample.events_data else [],
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(old.eval),
    )
    # the same eval now, which records origins
    solver, model = react_with_a_summary_compaction()
    log = run_logged(solver, model)
    recorded = replay_events(log, logged_sample(log).events)

    def arguments(step: Step) -> Any:
        call = getattr(step, "call", None)
        return call.arguments if call is not None else None

    def shape(steps: Sequence["ReplayStep"]) -> list[Any]:
        # react's prompts changed since 0.3.285, so compare the messages'
        # roles, and the steps' tool calls
        return [
            (
                s.stage,
                s.segment[1],
                [m.role for m in s.step.history or []],
                [m.role for m in s.step.input or []],
                arguments(s.step),
            )
            for s in steps
        ]

    assert shape(inferred) == shape(recorded)
    # the two summary calls are not turns, so neither has steps
    generates = {s.id for s in inferred if s.stage == "model_input"}
    assert len(generates) == len(models) - 2
    assert max(s.segment[1] for s in inferred) == 2


@pytest.mark.parametrize(
    "where",
    [
        "sample_init",
        "sample_start",
        "sample_attempt_start",
        "sample_scoring",
        "cleanup",
    ],
)
def test_a_model_call_outside_the_phases_is_not_a_turn(where: str) -> None:
    from inspect_ai._util.registry import _registry
    from inspect_ai.hooks import Hooks, hooks

    async def call_the_model(*args: Any) -> None:
        await get_model().generate(where)

    @hooks(name="r7_calls_the_model", description="calls the model from a hook")
    class CallsTheModel(Hooks):
        pass

    if where != "cleanup":
        setattr(CallsTheModel, f"on_{where}", call_the_model)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=generate(),
        cleanup=call_the_model if where == "cleanup" else None,
    )
    try:
        log = eval(task, model=outputs(done(), done()))[0]
    finally:
        _registry.pop("hooks:r7_calls_the_model", None)
    assert log.status == "success", log.error
    events = logged_sample(log).events
    models = [e for e in events if isinstance(e, ModelEvent)]
    [solve] = [e for e in models if e.origin == "agent"]
    [outside] = [e for e in models if e is not solve]
    assert outside.origin == "setup"
    assert (outside.span_id is None) == (where != "sample_init")
    for inputs in ["expanded", "pooled"]:
        for recorded in [events, without_origins(events)]:
            replay = replay_inputs(log, recorded, inputs)
            assert [(s.stage, s.id) for s in replay] == [
                ("model_input", solve.uuid),
                ("model_output", solve.uuid),
            ]


def test_a_chain_in_cleanup_is_not_an_earlier_layout() -> None:
    # Ransom's review 31 B1: a chain awaited in Task.cleanup records a
    # top-level solver span after the solvers and scorers spans close
    from inspect_ai.solver import chain

    @solver
    def cleans_up() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await get_model().generate("cleanup")
            return state

        return solve

    async def cleanup(state: TaskState) -> None:
        async def no_generate(*args: Any, **kwargs: Any) -> TaskState:
            raise AssertionError("cleanup does not generate")

        await chain(cleans_up())(state, no_generate)

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=generate(),
        cleanup=cleanup,
    )
    log = eval(task, model=outputs(done(), done()))[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    assert any(
        isinstance(e, SpanBeginEvent) and e.parent_id is None and e.type == "solver"
        for e in events
    )
    models = [e for e in events if isinstance(e, ModelEvent)]
    [solve] = [e for e in models if e.origin == "agent"]
    [outside] = [e for e in models if e is not solve]
    assert outside.origin == "setup"
    for inputs in ["expanded", "pooled"]:
        for recorded in [events, without_origins(events)]:
            replay = replay_inputs(log, recorded, inputs)
            assert [(s.stage, s.id) for s in replay] == [
                ("model_input", solve.uuid),
                ("model_output", solve.uuid),
            ]


@pytest.mark.parametrize("start", ["sample_start", "sample_attempt_start"])
@pytest.mark.parametrize("after", [False, True])
def test_a_model_call_before_solving_stops_early_is_not_a_turn(
    start: str, after: bool
) -> None:
    from inspect_ai._util.registry import _registry
    from inspect_ai.hooks import Hooks, hooks
    from inspect_ai.util import LimitExceededError

    async def call_and_stop(*args: Any) -> None:
        await get_model().generate(start)
        raise LimitExceededError("custom", value=1, limit=1)

    async def call_the_model(*args: Any) -> None:
        await get_model().generate("after")

    @hooks(name="r7_stops_early", description="calls the model, then stops")
    class StopsEarly(Hooks):
        pass

    setattr(StopsEarly, f"on_{start}", call_and_stop)
    if after:
        setattr(StopsEarly, "on_sample_scoring", call_the_model)
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=generate(),
        cleanup=call_the_model if after else None,
    )
    try:
        log = eval(task, model=outputs(done(), done(), done()))[0]
    finally:
        _registry.pop("hooks:r7_stops_early", None)
    assert log.status == "success", log.error
    events = logged_sample(log).events
    assert not any(
        isinstance(e, SpanBeginEvent) and e.name == "solvers" for e in events
    )
    models = [e for e in events if isinstance(e, ModelEvent)]
    assert len(models) == (3 if after else 1)
    assert all(e.origin == "setup" for e in models)
    for inputs in ["expanded", "pooled"]:
        for recorded in [events, without_origins(events)]:
            replay = replay_inputs(log, recorded, inputs)
            assert not [s for s in replay if s.stage in ("model_input", "model_output")]


@pytest.mark.parametrize("phase", [None, "init", "solvers", "scorers"])
def test_a_call_outside_the_phases_is_setup_only_in_a_log_that_records_them(
    phase: str | None,
) -> None:
    task: list[ChatMessage] = [ChatMessageUser(content="Solve it.")]
    m1 = linked_call("m1", None, task, "Solved.", None)
    events: list[Event] = [m1]
    if phase is not None:
        events.extend(
            [
                SpanBeginEvent(id=phase, name=phase, type=phase),
                SpanEndEvent(id=phase),
            ]
        )
    replay = steps_from_events(
        [*task, m1.output.message],
        events,
        [],
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version=None, sentinel=False),
    )
    assert [(s.stage, s.id) for s in replay] == (
        [("model_input", "m1"), ("model_output", "m1")] if phase is None else []
    )


@protocol
def r7_generate_fails() -> Protocol:
    async def check(
        context: Context, step: BeforeGenerate, escalations: Escalations
    ) -> Decision | None:
        raise PermissionError("sentinel denied")

    return check


@pytest.mark.parametrize(
    "sentinel,status",
    [
        (lambda: d3_generate_decides("terminate", False), "success"),
        # a monitor's failure is recorded, then the protocol's, which fails
        # the sample
        (lambda: [d3_generate_raises(), r7_generate_fails()], "error"),
        # the protocol's failure alone is recorded
        (lambda: r7_generate_fails(), "error"),
    ],
    ids=["terminate", "failure", "protocol-failure"],
)
def test_a_model_input_check_without_a_model_call_is_skipped_with_warning(
    sentinel: Callable[[], Any], status: str, caplog: pytest.LogCaptureFixture
) -> None:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=tool_loop(addition()),
        sentinel=sentinel(),
    )
    log = eval(task, model=agent_model())[0]
    assert log.status == status
    events = logged_sample(log).events
    assert not [e for e in events if isinstance(e, ModelEvent)]
    checked = {(e.stage, e.step_id) for e in events if isinstance(e, SentinelEvent)}
    assert [stage for stage, _ in checked] == ["model_input"]
    assert replay_events(log, events) == []
    assert [r.message for r in caplog.records if "Skipped" in r.message] == [
        "Skipped 1 sentinel model check(s) without a matching model call in this transcript."
    ]


@monitor
def r7_first_generate_raises() -> MonitorGroup:
    failed = False

    async def check(context: Context, step: BeforeGenerate) -> Observation | None:
        nonlocal failed
        if not failed:
            failed = True
            raise ValueError("monitor broke")
        return None

    return MonitorGroup(check)


@protocol
def r7_first_generate_fails() -> Protocol:
    failed = False

    async def check(
        context: Context, step: BeforeGenerate, escalations: Escalations
    ) -> Decision | None:
        nonlocal failed
        if not failed:
            failed = True
            raise PermissionError("sentinel denied")
        return None

    return check


@solver
def r7_generates_again_after_a_failure() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        try:
            await get_model().generate(state.messages)
        except Exception:
            pass
        state.output = await get_model().generate(state.messages)
        return state

    return solve


@pytest.mark.parametrize(
    "monitor_fails,recorded",
    [
        (d3_generate_raises, 2),
        # the later check records nothing, so no step id names the turn
        (r7_first_generate_raises, 1),
    ],
    ids=["later-check-recorded", "later-check-abstains"],
)
def test_a_model_input_step_without_its_model_call_is_not_replayed_after_a_later_turn(
    monitor_fails: Callable[[], Any], recorded: int, caplog: pytest.LogCaptureFixture
) -> None:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=r7_generates_again_after_a_failure(),
        # a monitor's failure is recorded, then the protocol's, which is caught
        sentinel=[monitor_fails(), r7_first_generate_fails()],
    )
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    [turn] = [e for e in events if isinstance(e, ModelEvent)]
    orphan, *called = dict.fromkeys(
        e.step_id
        for e in events
        if isinstance(e, SentinelEvent) and e.stage == "model_input"
    )
    assert len(called) + 1 == recorded
    assert called in ([turn.uuid], []) and orphan != turn.uuid
    replay = replay_events(log, events)
    assert [s.id for s in replay if s.stage == "model_input"] == [turn.uuid]
    assert [r.message for r in caplog.records if "Skipped" in r.message] == [
        "Skipped 1 sentinel model check(s) without a matching model call in this transcript."
    ]


def test_unmatched_checks_emit_one_counted_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[Event] = []
    for index in range(2):
        span_id = f"check-{index}"
        events.extend(
            [
                SpanBeginEvent(id=span_id, name="probe", type="sentinel"),
                SentinelEvent(
                    factory="probe",
                    path="probe",
                    function="check",
                    step_id=f"missing-{index}",
                    conversation="sample",
                    stage="model_input" if index == 0 else "model_output",
                    kind="observation",
                    status="reported",
                    suspicion=0.1,
                    span_id=span_id,
                ),
                SpanEndEvent(id=span_id),
            ]
        )
    assert (
        steps_from_events(
            [],
            events,
            [],
            sample_uuid="sample",
            eval_info=EvalInfo(inspect_ai_version=None, sentinel=True),
        )
        == []
    )
    assert [r.message for r in caplog.records if "Skipped" in r.message] == [
        "Skipped 2 sentinel model check(s) without a matching model call in this transcript."
    ]


@pytest.mark.parametrize("stage", ["model_input", "model_output"])
@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_empty_step_id_check_does_not_attach_to_uuidless_model_call(
    stage: SentinelStage, inputs: str, caplog: pytest.LogCaptureFixture
) -> None:
    from inspect_ai._sentinel import _replay

    check = SentinelEvent(
        factory="inspect_sentinel/human",
        path="human",
        function="check",
        step_id="",
        conversation="sample",
        stage=stage,
        kind="decision",
        status="reported",
        action="proceed",
        span_id="check",
    )
    call = imported_call("unused", [ChatMessageUser(content="Go ahead")], "run")
    call = call.model_copy(update={"uuid": None, "origin": "agent"})
    events: list[Event] = [
        SpanBeginEvent(id="check", name="human", type="sentinel"),
        check,
        SpanEndEvent(id="check"),
        call,
    ]
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    replay = steps_from_events(
        [],
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version="0.3.200", sentinel=True),
    )
    [step] = [s for s in replay if s.stage == stage]
    assert step.recorded_answers == {}
    assert [r.message for r in caplog.records if "Skipped" in r.message] == [
        "Skipped 1 sentinel model check(s) without a matching model call in this transcript."
    ]


@solver
def r7_runs_two_branches() -> Solver:
    """Two attempts at the task in one conversation, each in a span of its own, as Petri's rollbacks are."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for branch in ("first", "second"):
            async with span(branch, type="trajectory"):
                state.output = await get_model().generate(
                    [ChatMessageUser(content=f"The {branch} attempt.")]
                )
        return state

    return solve


def test_a_stored_timeline_gives_one_conversation_per_branch() -> None:
    log = run_logged(r7_runs_two_branches(), "mockllm/model")
    events = logged_sample(log).events
    spans = {e.name: e.id for e in events if isinstance(e, SpanBeginEvent)}
    first, second = [
        [
            TimelineEvent(event=e)
            for e in events
            if isinstance(e, ModelEvent) and e.span_id == spans[branch]
        ]
        for branch in ("first", "second")
    ]
    timeline = Timeline(
        name="target",
        description="",
        root=TimelineSpan(
            id="target",
            name="target",
            content=list(first),
            branches=[
                TimelineSpan(id="rollback", name="rollback", content=list(second))
            ],
        ),
    )
    sample = logged_sample(log)
    assert {s.step.conversation for s in replay_events(log, events)} == {sample.uuid}
    assert [
        s.step.conversation
        for s in replay_events(log, events, timeline=timeline)
        if s.stage == "model_input"
    ] == ["target", "rollback"]


def solving(events: list[Event]) -> list[Event]:
    for event in events:
        if isinstance(event, SpanBeginEvent):
            if event.parent_id is None:
                event.parent_id = "solvers"
        elif not isinstance(event, SpanEndEvent) and event.span_id is None:
            event.span_id = "solvers"
    return [
        SpanBeginEvent(id="solvers", name="solvers", type="solvers"),
        *events,
        SpanEndEvent(id="solvers"),
    ]


def test_a_stored_timeline_does_not_change_turn_inference_without_origins() -> None:
    task = ChatMessageUser(content="Solve it.")
    m1 = linked_call("m1", "agent", [task], "First.", None)
    asked: list[ChatMessage] = [
        task,
        m1.output.message,
        ChatMessageUser(content="Next?"),
    ]
    m2 = linked_call("m2", "agent", asked, "Alternative A.", None)
    m3 = linked_call("m3", "agent", asked, "Alternative B.", None)
    m4 = linked_call(
        "m4",
        "agent",
        [*asked, m3.output.message, ChatMessageUser(content="Continue.")],
        "Done.",
        None,
    )
    events = solving(
        [
            SpanBeginEvent(id="agent", name="agent", type="agent"),
            m1,
            m2,
            m3,
            m4,
            SpanEndEvent(id="agent"),
        ]
    )
    stored = Timeline(
        name="target",
        description="",
        root=TimelineSpan(
            id="target",
            name="target",
            content=[TimelineEvent(event=m1), TimelineEvent(event=m2)],
            branches=[
                TimelineSpan(
                    id="rollback",
                    name="rollback",
                    content=[TimelineEvent(event=m3), TimelineEvent(event=m4)],
                )
            ],
        ),
    )
    replay = steps_from_events(
        [],
        events,
        [],
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version=None, sentinel=False),
        timeline=stored,
    )
    turns = [step for step in replay if step.stage == "model_input"]
    assert [step.id for step in turns] == ["m1", "m3", "m4"]
    assert [step.step.conversation for step in turns] == [
        "target",
        "rollback",
        "rollback",
    ]


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_a_solver_wrapping_a_subagent_keeps_its_agent_s_continuity(
    inputs: str,
) -> None:
    # Ransom's 39th review: the timeline keeps a solver that holds a subagent
    # as a span of its own, but the solver's own calls are still its agent's
    from inspect_ai._sentinel import _replay

    task = ChatMessageUser(content="Solve it.")
    m1 = linked_call("m1", "agent", [task], "First.", None)
    asked: list[ChatMessage] = [
        task,
        m1.output.message,
        ChatMessageUser(content="Next?"),
    ]
    m2 = linked_call("m2", "agent", asked, "Alternative A.", None)
    m3 = linked_call("m3", "agent", asked, "Alternative B.", None)
    s1 = linked_call("s1", "sub", [ChatMessageUser(content="Help.")], "Helped.", None)
    m4 = linked_call(
        "m4",
        "wrap",
        [*asked, m3.output.message, ChatMessageUser(content="Continue.")],
        "Done.",
        None,
    )
    events = solving(
        [
            SpanBeginEvent(id="agent", name="agent", type="agent"),
            m1,
            m2,
            m3,
            SpanBeginEvent(id="wrap", name="wrap", type="solver", parent_id="agent"),
            SpanBeginEvent(id="sub", name="sub", type="agent", parent_id="wrap"),
            s1,
            SpanEndEvent(id="sub"),
            m4,
            SpanEndEvent(id="wrap"),
            SpanEndEvent(id="agent"),
        ]
    )
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    replay = steps_from_events(
        [],
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version=None, sentinel=False),
    )

    assert [
        s.id
        for s in replay
        if s.stage == "model_input" and s.step.conversation == "agent"
    ] == ["m1", "m3", "m4"]


# the shared continuity fixtures, whose "expected_continuity" (else
# "expected") gives the turns replay's log driver infers
CONTINUITY_FIXTURES = Path(__file__).parent.parent / "timeline" / "fixtures" / "events"


@pytest.mark.parametrize(
    "fixture",
    sorted(
        path.stem
        for path in CONTINUITY_FIXTURES.glob("*.json")
        if path.stem.startswith(("continuity_", "agent_result_"))
    ),
)
def test_replay_infers_the_turns_of_the_continuity_fixtures(fixture: str) -> None:
    # continuity applies only in replay's log driver (decided by Charles
    # 2026-10-26): a log without origins replays as one recording, for the
    # main agent's calls, the origins its continuity tree shows
    import json

    from pydantic import TypeAdapter

    data = json.loads((CONTINUITY_FIXTURES / f"{fixture}.json").read_text())
    events = TypeAdapter(list[Event]).validate_python(data["events"])
    main = data.get("expected_continuity", data["expected"])["agent"]
    turns = set(main["event_uuids"])
    utility = {
        uuid
        for child in main.get("children", [])
        if child.get("utility")
        for uuid in child["event_uuids"]
    }
    recorded = [
        event.model_copy(
            update={"origin": "agent" if event.uuid in turns else "helper"}
        )
        if isinstance(event, ModelEvent) and event.uuid in turns | utility
        else event
        for event in events
    ]

    def steps(events: list[Event]) -> list[Any]:
        return [
            (s.stage, s.id, s.segment, comparable(s.step))
            for s in steps_from_events(
                [],
                events,
                [],
                sample_uuid="sample",
                eval_info=EvalInfo(inspect_ai_version="0.3.200", sentinel=False),
            )
        ]

    assert steps(events) == steps(recorded)


@pytest.mark.parametrize("phases", [True, False])
def test_a_solver_s_call_after_the_only_agent_is_not_judged_by_its_prompt(
    phases: bool,
) -> None:
    # self-review after Ransom's ninth review: the timeline merges a solver's
    # calls beside the only agent span into that span, and the prompt rule
    # took the agent's tool-calling prompt as theirs, so a final generate()
    # under the solver's own prompt was utility; continuity keeps the two
    # conversations apart, and so now does the prompt rule
    checker = ChatMessageSystem(content="You check.")
    asked: list[ChatMessage] = [checker, ChatMessageUser(content="Check it.")]
    call = ToolCall(id="t1", function="f", arguments={})
    b1 = linked_call("B1", "B", asked, "", None, call)
    result = ChatMessageTool(content="ok", tool_call_id="t1", function="f")
    b2 = linked_call("B2", "B", [*asked, b1.output.message, result], "Fine.", None)
    final: list[ChatMessage] = [
        ChatMessageSystem(content="You are the main solver."),
        ChatMessageUser(content="Solve it."),
    ]
    m1 = linked_call("M1", "solvers" if phases else None, final, "Solved.", None)
    events: list[Event] = [
        SpanBeginEvent(id="B", name="checker", type="agent", parent_id="solvers"),
        b1,
        b2,
        SpanEndEvent(id="B"),
        m1,
    ]
    if phases:
        events = [
            SpanBeginEvent(id="solvers", name="solvers", type="solvers"),
            *events,
            SpanEndEvent(id="solvers"),
        ]
    else:
        events[0] = SpanBeginEvent(id="B", name="checker", type="agent")

    def steps(events: list[Event]) -> list[tuple[str, str]]:
        return sorted(
            (s.stage, s.id)
            for s in steps_from_events(
                [*final, m1.output.message],
                events,
                [],
                sample_uuid="sample",
                eval_info=EvalInfo(inspect_ai_version=None, sentinel=False),
            )
        )

    recorded = [
        e.model_copy(update={"origin": "agent"}) if isinstance(e, ModelEvent) else e
        for e in events
    ]

    assert steps(events) == steps(recorded)
    assert ("model_input", "M1") in steps(events)


def checked_m3(later_turn: bool, recorded: bool) -> list[Event]:
    """`continuity_none` with a sentinel check of m3, a call inferred as utility unless its origin is recorded."""
    import json

    from pydantic import TypeAdapter

    data = json.loads((CONTINUITY_FIXTURES / "continuity_none.json").read_text())
    events: list[Event] = []
    for event in TypeAdapter(list[Event]).validate_python(data["events"]):
        if isinstance(event, ModelEvent):
            if event.uuid == "m4" and not later_turn:
                continue
            if recorded:
                event = event.model_copy(update={"origin": "agent"})
        if isinstance(event, ModelEvent) and event.uuid == "m3":
            last = event.input[-1].model_copy(update={"id": "u3"})
            event = event.model_copy(update={"input": [*event.input[:-1], last]})
            events += [
                SpanBeginEvent(
                    id="check", name="probe", type="sentinel", span_id=event.span_id
                ),
                SentinelEvent(
                    factory="probe",
                    path="probe",
                    function="check",
                    step_id="m3",
                    conversation="agent",
                    stage="model_input",
                    kind="observation",
                    status="reported",
                    suspicion=0.1,
                    span_id="check",
                ),
                SpanEndEvent(id="check", span_id=event.span_id),
            ]
        events.append(event)
    return events


@pytest.mark.parametrize("later_turn", [True, False])
def test_a_checked_call_inferred_not_a_turn_has_no_steps(
    later_turn: bool,
) -> None:
    # A checked call inferred as utility has no step. The next turn keeps its
    # own id and is not handed that check.
    replay = steps_from_events(
        [],
        checked_m3(later_turn, recorded=False),
        [],
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version="0.3.200", sentinel=True),
    )

    assert [s.id for s in replay if s.stage == "model_input"] == [
        "m1",
        "m2",
        *(["m4"] if later_turn else []),
    ]


@pytest.mark.parametrize("later_turn", [True, False])
def test_a_checked_call_recorded_as_a_turn_keeps_its_check(
    later_turn: bool,
) -> None:
    replay = steps_from_events(
        [],
        checked_m3(later_turn, recorded=True),
        [],
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version="0.3.200", sentinel=True),
    )

    assert [s.id for s in replay if s.stage == "model_input"] == [
        "m1",
        "m2",
        "m3",
        *(["m4"] if later_turn else []),
    ]


def test_a_main_conversation_ending_in_a_fork_replays_both_heads() -> None:
    import json

    from pydantic import TypeAdapter

    data = json.loads((CONTINUITY_FIXTURES / "continuity_fork_at_end.json").read_text())
    events = TypeAdapter(list[Event]).validate_python(data["events"])
    m2 = next(e for e in events if isinstance(e, ModelEvent) and e.uuid == "m2")
    replay = steps_from_events(
        [*m2.input, m2.output.message],
        events,
        [],
        sample_uuid="sample",
        eval_info=EvalInfo(inspect_ai_version="0.3.200", sentinel=False),
    )

    assert [s.id for s in replay if s.stage == "model_input"] == [
        "m1",
        "m2",
        "m3",
    ]


def test_a_person_s_approval_is_a_human_decision_without_a_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.approval import human_approver

    Panel("approve", "fine").install(monkeypatch)
    log = run_logged(
        tool_loop(addition()),
        agent_model(2),
        approval=[ApprovalPolicy(human_approver(), "*")],
    )
    sample = logged_sample(log)
    replay = steps_from_events(
        sample.messages,
        sample.events,
        [],
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
        human_approvers=("human",),
    )
    first, second = [s for s in replay if s.stage == "tool_call"]
    assert first.step.human_decisions == ()
    [decision] = second.step.human_decisions or []
    assert decision.step_id == first.id
    assert decision.decided.report.action == "proceed"
    assert decision.decided.report.explanation == "fine"


# nothing quadratic: counted on n and 2n turns, with a compaction and
# parallel tool calls, the work doubles rather than quadruples


class _Turns(MockLLM):
    """Two parallel tool calls a turn for `turns` turns, then done; a call offered no tools is a compaction's summary."""

    turns = 0

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: Any,
        config: GenerateConfig,
    ) -> Any:
        if not tools:
            return done("summary")
        if _Turns.turns == 0:
            return done()
        _Turns.turns -= 1
        turn = _Turns.turns
        return calls(
            ("addition", {"x": turn, "y": 1}),
            ("addition", {"x": turn, "y": 2}),
            turn=turn,
        )


@modelapi(name="r7_turns")
def r7_turns() -> type[ModelAPI]:
    return _Turns


def long_run(turns: int, seen: dict[str, Step] | None = None) -> EvalLog:
    from inspect_ai.model._compaction.summary import CompactionSummary

    _Turns.turns = turns
    return run_logged(
        as_solver(
            react(
                tools=[addition()],
                compaction=CompactionSummary(threshold=400),
                submit=False,
            )
        ),
        "r7_turns/model",
        sentinel=[r7_probe(seen)] if seen is not None else None,
    )


def assert_views_share_storage(
    steps: Sequence[Step], pool: Sequence[ChatMessage] | None = None
) -> None:
    """Every step's conversation fields are views of lists the conversation keeps, never copies.

    Per conversation, `history` and `human_decisions` are each backed by one list, and live `agent_messages` is the running agent's own list, one object (replay's is None). The tool stages' `input` and `tools` are the producing model call's own lists, one per assistant message, whatever its calls and stages: live, its `ModelEvent`'s; in replay, rows of the one pool.
    """
    backing: dict[tuple[str, str], set[int]] = {}
    generates = {
        step.output.message.id: step
        for step in steps
        if isinstance(step, AfterGenerate) and step.output.choices
    }
    for step in steps:
        for name in ("history", "human_decisions"):
            value = getattr(step, name)
            assert isinstance(value, ListView), (name, type(value))
            backing.setdefault((step.conversation, name), set()).add(id(value._items))
        if step.agent_messages is not None:
            backing.setdefault((step.conversation, "agent_messages"), set()).add(
                id(step.agent_messages)
            )
        inputs: list[Any] = [step.input]
        if isinstance(step, BeforeToolCall | AfterToolCall) and step.input is not None:
            assert isinstance(step.tools, ListView)
            if pool is None:
                assert isinstance(step.input, ListView)
                producer = generates.get(step.message_id)
                if producer is not None:
                    assert step.input == producer.input
                for name in ("input", "tools"):
                    backing.setdefault((step.message_id, name), set()).add(
                        id(getattr(step, name)._items)
                    )
                inputs = []
        if pool is not None:
            if isinstance(step, BeforeToolCall | AfterToolCall) and step.tools:
                assert isinstance(step.tools, ListView)
                backing.setdefault((step.message_id, "tools"), set()).add(
                    id(step.tools._items)
                )
                # one range index per producing model call, not per call
                backing.setdefault((step.message_id, "input view"), set()).add(
                    id(step.input)
                )
            for input in inputs:
                assert isinstance(input, PoolView) and input._pool is pool
    for (conversation, name), lists in backing.items():
        assert len(lists) == 1, (conversation, name, len(lists))


@pytest.mark.parametrize("turns", [10, 20])
def test_live_steps_copy_nothing_of_the_conversation(turns: int) -> None:
    seen: dict[str, Step] = {}
    log = long_run(turns, seen)
    assert log.samples
    assert len(seen) > 4 * turns
    assert_views_share_storage(list(seen.values()))


class Work(NamedTuple):
    keyed: int
    """Pool rows keyed (content keys computed)."""
    visited: int
    """Positions the fold compared, by content."""
    indexed: int
    """Bisections the fold's lookups and index construction made."""
    entries: int
    """Entries the fold's indexes of previous inputs were built with."""
    pool: int
    """Rows in the message pool."""
    ranges: int
    """Input ranges the log stores, over all model events."""
    steps: int


def replay_work(
    monkeypatch: pytest.MonkeyPatch,
    messages: Sequence[ChatMessage],
    events: Sequence[Event],
    pool: Sequence[ChatMessage],
    sample_uuid: str,
    eval_info: EvalInfo,
) -> Work:
    from inspect_ai._sentinel import _replay, _steps

    keyed = visited = indexed = entries = 0
    index = _replay._PooledInput._index
    content_key = _steps.content_key
    canonical = _replay._PoolKeys.canonical

    def counting_content_key(message: Any) -> str:
        nonlocal keyed
        keyed += 1
        return content_key(message)

    def counting_canonical(self: Any, row: int) -> int:
        nonlocal visited
        visited += 1
        return canonical(self, row)

    def counting_bisect_left(rows: list[int], row: int) -> int:
        # one per range a lookup passes
        nonlocal indexed
        indexed += 1
        return bisect.bisect_left(rows, row)

    def counting_index(self: Any) -> Any:
        nonlocal entries
        built = self._points is None
        result = index(self)
        if built:
            entries += sum(len(offsets) for offsets in result[1])
        return result

    with monkeypatch.context() as patch:
        patch.setattr(_replay._PooledInput, "_index", counting_index)
        patch.setattr(_replay, "content_key", counting_content_key)
        patch.setattr(_replay._PoolKeys, "canonical", counting_canonical)
        patch.setattr(_replay, "bisect_left", counting_bisect_left)
        replay = steps_from_events(
            messages, events, pool, sample_uuid=sample_uuid, eval_info=eval_info
        )
    assert_views_share_storage([step.step for step in replay], pool)
    ranges = sum(len(e.input_refs or []) for e in events if isinstance(e, ModelEvent))
    return Work(keyed, visited, indexed, entries, len(pool), ranges, len(replay))


def assert_linear(small: Work, large: Work, doubles: bool = True) -> None:
    """For these stored input shapes, each pool row is keyed once and the fold's work stays within a constant of stored rows and ranges; with `doubles`, twice the turns cost at most a little over twice the work."""
    for work in (small, large):
        assert work.keyed <= work.pool
        # a few comparisons, bisections and index entries per stored row and range
        fold = work.visited + work.indexed + work.entries
        assert fold <= 6 * (work.ranges + work.pool), work
    if doubles:
        assert large.steps <= 2.2 * small.steps
        assert large.visited <= 2.2 * small.visited, (small, large)
        assert large.indexed <= 2.2 * small.indexed + 10, (small, large)
        assert large.entries <= 2.2 * small.entries + 10, (small, large)


def log_work(turns: int, monkeypatch: pytest.MonkeyPatch, origins: bool = True) -> Work:
    from inspect_ai._sentinel import _replay

    log = long_run(turns)
    sample = logged_sample(log)
    events = sample.events if origins else without_origins(sample.events)
    events, pool = _replay._condensed(events, [])
    return replay_work(
        monkeypatch,
        sample.messages,
        events,
        pool,
        sample.uuid or "",
        EvalInfo.from_eval(log.eval),
    )


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_an_adversarial_log_replays_in_linear_work(inputs: str) -> None:
    # after Ransom's ninth review: repeated tool call ids, an unresolved
    # bridge task, fragmented and falling inputs, unresolved forks and
    # sentinel 0.1.x checks named by message id (repeat suffixes included)
    # at once; the lines of inspect_ai executed per unit the log stores stay
    # flat as the rounds double for these input shapes
    from test_helpers.adversarial_log import adversarial_log, executed_lines

    pooled = inputs == "pooled"
    per_unit = []
    for rounds in (100, 200, 400):
        log = adversarial_log(rounds, window=None if pooled else 16, checks=True)
        events: list[Event] = log.events
        pool: list[ChatMessage] = []
        if pooled:
            events, _, entries = condense_model_event_inputs(events, 0, {})
            pool = [message for _, message in entries]
        stored = len(events) + len(pool)
        for e in events:
            if isinstance(e, ModelEvent):
                stored += len(e.input_refs) if pooled and e.input_refs else len(e.input)
        replay, lines = executed_lines(
            steps_from_events,
            log.messages,
            events,
            pool,
            sample_uuid="sample",
            eval_info=EvalInfo(inspect_ai_version="0.3.200", sentinel=True),
        )
        assert len([s for s in replay if s.stage == "model_input"]) >= rounds
        per_unit.append(lines / stored)
    assert per_unit[2] <= 1.3 * per_unit[0], per_unit


def test_tool_call_prompt_scan_without_system_message_is_linear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.event import _timeline

    original = _timeline._get_system_prompt_for_event
    work: list[int] = []

    def count_prompt_input(event: ModelEvent, inputs: Any) -> str | None:
        work[-1] += len(inputs.of(event))
        return original(event, inputs)

    monkeypatch.setattr(_timeline, "_get_system_prompt_for_event", count_prompt_input)
    for turns in (100, 200, 400):
        pool: list[ChatMessage] = [
            ChatMessageUser(content=f"message {n}") for n in range(turns)
        ]
        events: list[Event] = [SpanBeginEvent(id="run", name="run", type="agent")]
        for n in range(turns):
            call = ToolCall(id=f"tool-{n}", function="lookup", arguments={})
            event = imported_call(f"model-{n}", [], "run", call)
            events.append(event.model_copy(update={"input_refs": [(0, n + 1)]}))
        events.append(SpanEndEvent(id="run"))
        work.append(0)
        replay = steps_from_events(
            [],
            solving(events),
            pool,
            sample_uuid="sample",
            eval_info=EvalInfo(inspect_ai_version="0.3.200", sentinel=False),
        )
        assert len([s for s in replay if s.stage == "model_input"]) == turns
        assert work[-1] <= 2 * len(pool), work
    assert work[-1] <= 4.2 * work[0], work


def test_pooled_prompt_fallback_without_system_message_reads_pool_once() -> None:
    from inspect_ai.event import _timeline

    class CountingPool(list[ChatMessage]):
        reads = 0

        def __getitem__(self, index: Any) -> Any:
            self.reads += 1
            return super().__getitem__(index)

        def __iter__(self) -> Iterator[ChatMessage]:
            for message in super().__iter__():
                self.reads += 1
                yield message

    work: list[int] = []
    for size in (100, 200, 400):
        pool = CountingPool(
            ChatMessageUser(content=f"message {n}") for n in range(size)
        )
        events = [turn_event([], [(0, n + 1)]) for n in range(size)]
        inputs = _timeline._Inputs(events, pool)
        for event in events:
            assert _timeline._get_system_prompt_for_event(event, inputs) is None
        work.append(pool.reads)
        assert work[-1] <= 3 * len(pool), work
    assert work[-1] <= 4.2 * work[0], work


@pytest.mark.parametrize("setup", [False, True])
@pytest.mark.parametrize("empty", [True, False])
@pytest.mark.parametrize("delayed", [False, True])
@pytest.mark.parametrize("ordinary", [False, True])
def test_bridge_result_lookup_with_empty_results_stays_bounded(
    empty: bool,
    setup: bool,
    delayed: bool,
    ordinary: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.event import _timeline

    original = _timeline._Inputs._pool_tool_rows
    original_results = _timeline._Inputs.tool_results
    original_row = _timeline._Inputs.row
    work: list[int] = []
    final_results: list[tuple[str, str]] = []
    active_lookup = False

    class CountingRows(dict[str, list[int]]):
        def get(self, key: str, default: Any = None) -> Any:
            work[-1] += 1
            return super().get(key, default)

    def counted_rows(inputs: Any) -> dict[str, list[int]]:
        rows = original(inputs)
        if not isinstance(rows, CountingRows):
            rows = CountingRows(rows)
            inputs._tool_rows = rows
        return rows

    def counted_results(
        inputs: Any, event: ModelEvent, ids: Any
    ) -> list[tuple[str, str]]:
        nonlocal active_lookup
        active_lookup = True
        try:
            results = original_results(inputs, event, ids)
        finally:
            active_lookup = False
        if event.uuid == "last":
            final_results.extend(results)
        return results

    def counted_row(inputs: Any, row: int) -> ChatMessage:
        if active_lookup:
            work[-1] += 1
        return original_row(inputs, row)

    monkeypatch.setattr(_timeline._Inputs, "_pool_tool_rows", counted_rows)
    monkeypatch.setattr(_timeline._Inputs, "tool_results", counted_results)
    monkeypatch.setattr(_timeline._Inputs, "row", counted_row)
    for rounds in (100, 200, 400):
        final_results.clear()
        pool: list[ChatMessage] = [ChatMessageUser(content="Start")]
        delayed_results: list[ChatMessageTool] = []
        events: list[Event] = []
        if setup:
            events.extend(
                [
                    SpanBeginEvent(id="init", name="init", type="init"),
                    linked_call("setup", "init", [], "Ready", None),
                    SpanEndEvent(id="init"),
                ]
            )
        events.extend(
            [
                SpanBeginEvent(id="solvers", name="solvers", type="solvers"),
                SpanBeginEvent(
                    id="main", name="main", type="agent", parent_id="solvers"
                ),
            ]
        )
        for n in range(rounds):
            task = ToolCall(id=f"task-{n}", function="task", arguments={})
            call = linked_call(f"m{n}", "main", [], "", None, task)
            events.append(call.model_copy(update={"input_refs": [(0, len(pool))]}))
            pool.append(call.output.message)
            sub = f"agent-{task.id}"
            events.extend(
                [
                    SpanBeginEvent(id=sub, name="sub", type="agent", parent_id="main"),
                    linked_call(f"sub-{n}", sub, [], "done", None).model_copy(
                        update={"input_refs": [(0, 1)]}
                    ),
                    SpanEndEvent(id=sub),
                ]
            )
            result = ChatMessageTool(
                content="" if empty else f"result {n}",
                tool_call_id=task.id,
                function="task",
            )
            if delayed:
                delayed_results.append(result)
            else:
                pool.append(result)
            if ordinary:
                pool.append(
                    ChatMessageTool(
                        content=f"ordinary result {n}",
                        tool_call_id=f"ordinary-{n}",
                        function="ordinary",
                    )
                )
        pool.extend(delayed_results)
        events.append(
            linked_call("last", "main", [], "Done", None).model_copy(
                update={"input_refs": [(0, len(pool))]}
            )
        )
        events.append(SpanEndEvent(id="main"))
        events.append(SpanEndEvent(id="solvers"))
        work.append(0)
        replay = steps_from_events(
            [],
            events,
            pool,
            sample_uuid="sample",
            eval_info=EvalInfo(inspect_ai_version="0.3.200", sentinel=False),
        )
        assert replay
        assert dict(final_results) == (
            {f"task-{n}": f"result {n}" for n in range(rounds)}
            if delayed and not empty
            else ({f"task-{rounds - 1}": f"result {rounds - 1}"} if not empty else {})
        )
        assert work[-1] <= 4 * rounds, (rounds, work)
    assert work[-1] <= 4.2 * work[0] + 10, work


def test_bridge_result_lookup_for_agent_batch_over_fragmented_input_stays_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.event import _timeline

    original_results = _timeline._Inputs.tool_results
    original_row = _timeline._Inputs.row
    original_bisect = bisect.bisect_left
    work: list[int] = []
    final_results: list[tuple[str, str]] = []
    active_lookup = False

    def counted_results(
        inputs: Any, event: ModelEvent, ids: Any
    ) -> list[tuple[str, str]]:
        nonlocal active_lookup
        active_lookup = True
        try:
            results = original_results(inputs, event, ids)
        finally:
            active_lookup = False
        if event.uuid == "final":
            final_results.extend(results)
        return results

    def counted_row(inputs: Any, row: int) -> ChatMessage:
        if active_lookup:
            work[-1] += 1
        return original_row(inputs, row)

    def counted_bisect(*args: Any, **kwargs: Any) -> int:
        if active_lookup:
            work[-1] += 1
        return original_bisect(*args, **kwargs)

    def agent(call_id: str) -> list[Event]:
        span = f"agent-{call_id}"
        return [
            SpanBeginEvent(id=span, name="task", type="agent", parent_id="main"),
            linked_call(
                f"sub-{call_id}", span, [ChatMessageUser(content=call_id)], "", None
            ),
            SpanEndEvent(id=span),
        ]

    monkeypatch.setattr(_timeline._Inputs, "tool_results", counted_results)
    monkeypatch.setattr(_timeline._Inputs, "row", counted_row)
    monkeypatch.setattr(_timeline, "bisect_left", counted_bisect)
    for agents in (100, 200, 400):
        final_results.clear()
        # the parent keeps every other setup message, so its inputs are stored
        # as many disjoint pool ranges
        setup: list[ChatMessage] = [
            ChatMessageUser(content=f"note {n}") for n in range(2 * agents)
        ]
        seed = ToolCall(id="seed", function="task", arguments={})
        first = linked_call("first", "main", setup[::2], "", None, seed)
        history = [*setup[::2], first.output.message]
        tasks = [
            ToolCall(id=f"task-{n}", function="task", arguments={})
            for n in range(agents)
        ]
        fanout = linked_call("fanout", "main", history, "", None, *tasks)
        history.append(fanout.output.message)
        waiting = linked_call("waiting", "main", history, "", None)
        results = [
            ChatMessageTool(content=f"result {call.id}", tool_call_id=call.id)
            for call in [seed, *tasks]
        ]
        final = linked_call(
            "final", "main", [*history, waiting.output.message, *results], "", None
        )
        events: list[Event] = [
            SpanBeginEvent(id="init", name="init", type="init"),
            linked_call("setup", "init", setup, "", None),
            SpanEndEvent(id="init"),
            SpanBeginEvent(id="solvers", name="solvers", type="solvers"),
            SpanBeginEvent(id="main", name="main", type="agent", parent_id="solvers"),
            first,
            *agent("seed"),
            fanout,
            *[event for call in tasks for event in agent(call.id)],
            waiting,
            final,
            SpanEndEvent(id="main"),
            SpanEndEvent(id="solvers"),
        ]
        events, data = condense_events(events)
        event_adapter = TypeAdapter(list[Event])
        message_adapter = TypeAdapter(list[ChatMessage])
        events = event_adapter.validate_json(event_adapter.dump_json(events))
        pool = message_adapter.validate_json(
            message_adapter.dump_json(data["messages"])
        )
        [stored] = [
            event
            for event in events
            if isinstance(event, ModelEvent) and event.uuid == "waiting"
        ]
        assert len(stored.input_refs or []) > agents
        work.append(0)
        replay = steps_from_events(
            [],
            events,
            pool,
            sample_uuid="sample",
            eval_info=EvalInfo(inspect_ai_version="0.3.277", sentinel=False),
        )
        assert replay
        assert dict(final_results) == {
            call.id: f"result {call.id}" for call in [seed, *tasks]
        }
        assert work[-1] <= 4 * len(pool), (agents, work)
    assert work[-1] <= 4.2 * work[0] + 10, work


def test_summary_match_reads_linearly_with_retained_prefix_and_compactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.event import _timeline

    original = _timeline._Inputs.fingerprint
    work: list[int] = []

    def count_fingerprint(inputs: Any, message: ChatMessage) -> Any:
        work[-1] += 1
        return original(inputs, message)

    monkeypatch.setattr(_timeline._Inputs, "fingerprint", count_fingerprint)
    for size in (100, 200, 400):
        pool: list[ChatMessage] = [
            ChatMessageUser(content=f"retained {n}", source="input")
            for n in range(size)
        ]
        pool.extend(ChatMessageUser(content=f"summary {n}") for n in range(size))
        inputs = _timeline._Inputs([], pool)
        continuity = _timeline._Continuity(inputs)
        work.append(0)
        for n in range(size):
            event = imported_call(f"summary-{n}", [], "run")
            event.output = ModelOutput.from_content("imported", f"summary {n}")
            call = _timeline._Call(event, [], event.output.message)
            next_input = PoolView(pool, [(0, size), (size + n, size + n + 1)])
            assert continuity._summarizes(call, next_input)
        assert work[-1] <= 3 * (len(pool) + size), work
    assert work[-1] <= 4.2 * work[0], work


@pytest.mark.parametrize("origins", [True, False])
def test_replay_reads_each_pool_row_once_and_folds_linearly(
    origins: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_linear(
        log_work(20, monkeypatch, origins), log_work(40, monkeypatch, origins)
    )


def turn_event(
    input: list[ChatMessage], refs: list[tuple[int, int]] | None = None
) -> ModelEvent:
    return ModelEvent(
        model="mockllm/model",
        origin="agent",
        input=input if refs is None else [],
        input_refs=refs,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", "ok"),
    )


def rebuilt_inputs(
    turns: int, shape: str
) -> tuple[list[ModelEvent], list[ChatMessage]]:
    """Inputs that grow by one message a turn, with one message rebuilt each turn (the opening, or one in the middle), stored as few ranges: the growing messages first in the pool, then the rebuilt ones."""
    body: list[ChatMessage] = [
        ChatMessageUser(content=f"message {n}") for n in range(turns)
    ]
    rebuilt: list[ChatMessage] = [
        ChatMessageUser(content=f"rebuilt for turn {n}") for n in range(turns)
    ]
    events = []
    for turn in range(1, turns):
        changed = (turns + turn, turns + turn + 1)
        refs = (
            [changed, (0, turn)] if shape == "opening" else [(0, 1), changed, (1, turn)]
        )
        events.append(turn_event([], refs))
    return events, [*body, *rebuilt]


@pytest.mark.parametrize("shape", ["opening", "middle"])
def test_a_rebuilt_message_keeps_the_fold_linear(
    shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = EvalInfo(inspect_ai_version=None, sentinel=False)
    small, large = (
        replay_work(monkeypatch, [], *rebuilt_inputs(turns, shape), "sample", info)
        for turns in (200, 400)
    )
    assert_linear(small, large)


@pytest.mark.parametrize("shape", ["opening", "middle"])
def test_a_rebuilt_message_s_fold_is_linear_in_what_the_log_stores(
    shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai._sentinel import _replay

    # condensed as inspect_ai writes it, each turn's rebuilt row interleaves
    # with the growing ones, so each input is stored as about as many ranges
    # as it has messages
    info = EvalInfo(inspect_ai_version=None, sentinel=False)
    works = []
    for turns in (100, 200):
        stored, rows = rebuilt_inputs(turns, shape)
        expanded: list[Event] = [
            turn_event(list(PoolView(rows, event.input_refs or []))) for event in stored
        ]
        condensed, pool = _replay._condensed(expanded, [])
        works.append(replay_work(monkeypatch, [], condensed, pool, "sample", info))
    small, large = works
    assert_linear(small, large, doubles=False)


def test_replay_tells_apart_pool_rows_whose_murmur3_hashes_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._sentinel import _replay

    collide_murmur3(monkeypatch)
    keys = _replay._PoolKeys(
        [ChatMessageUser(content="first"), ChatMessageUser(content="second")]
    )
    assert [keys.canonical(0), keys.canonical(1)] == [0, 1]


def test_the_fold_over_pool_ranges_is_the_fold_live() -> None:
    from inspect_ai._sentinel import _replay
    from inspect_ai._sentinel._steps import _Sent

    rng = random.Random(7)
    messages: list[ChatMessage] = [
        ChatMessageUser(content=text, metadata=metadata)
        for text in "ABCD"
        for metadata in (None, {"variant": 1})
    ]
    for _ in range(300):
        inputs = [
            [rng.choice(messages) for _ in range(rng.randint(0, 6))]
            for _ in range(rng.randint(1, 6))
        ]
        live = _Sent()
        for input in inputs:
            live.record(input)
        condensed, pool = _replay._condensed([turn_event(i) for i in inputs], [])
        keys = _replay._PoolKeys(pool)
        replay = _Sent()
        for event in condensed:
            assert isinstance(event, ModelEvent)
            replay.record_input(
                _replay._PooledInput(PoolView(pool, event.input_refs or []), keys)
            )
        assert [comparable(m) for m in replay.messages] == [
            comparable(m) for m in live.messages
        ], inputs


class _Interleaved(MockLLM):
    """The first two requests fail, the first only once the second has arrived; the rest succeed."""

    requests = 0
    second: anyio.Event | None = None

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, _RetriedError)

    def retry_wait(self) -> Any:
        return tenacity.wait_fixed(0)

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: Any,
        config: GenerateConfig,
    ) -> Any:
        _Interleaved.requests += 1
        second = _Interleaved.second
        assert second is not None
        if _Interleaved.requests == 1:
            await second.wait()
            raise _RetriedError("try again")
        if _Interleaved.requests == 2:
            second.set()
            raise _RetriedError("try again")
        return done()


@modelapi(name="r7_interleaved")
def r7_interleaved() -> type[ModelAPI]:
    return _Interleaved


@solver
def r7_generates_the_same_input_twice_at_once() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()

        async def ask() -> ModelOutput:
            return await model.generate([ChatMessageUser(content="Same question.")])

        await tg_collect([ask, ask])
        return state

    return solve


def test_overlapping_equal_generates_with_interleaved_retries_replay_by_message_id() -> (
    None
):
    # a generate's later attempts carry no id, so replay groups them by their
    # input; two overlapping generates with equal content but their own
    # messages keep those messages' ids through the log, which tells them apart
    _Interleaved.requests = 0
    _Interleaved.second = anyio.Event()
    seen: dict[str, Step] = {}
    log = run_logged(
        r7_generates_the_same_input_twice_at_once(),
        "r7_interleaved/model",
        sentinel=[r7_probe(seen)],
    )
    assert log.samples
    live = set(live_steps(log.samples[0], seen))
    replay = {(step.stage, step.id) for step in replayed(log)}
    first_attempts = [
        e.uuid
        for e in log.samples[0].events
        if isinstance(e, ModelEvent) and e.error is not None
    ]
    assert {id for _, id in live} == set(first_attempts)
    assert len(replay) == len(live) == 4
    assert replay == live


def test_views_read_as_the_lists_they_cut() -> None:
    from inspect_ai._sentinel._steps import ListView, PoolView

    items = list(range(10))
    pool: list[ChatMessage] = [ChatMessageUser(content=str(i)) for i in range(10)]
    cases: list[tuple[Sequence[Any], list[Any]]] = [
        (ListView(items, 7, 2), items[2:7]),
        (
            PoolView(pool, [(0, 3), (5, 8), (2, 4)]),
            [*pool[0:3], *pool[5:8], *pool[2:4]],
        ),
    ]
    for view, expected in cases:
        assert view == expected and expected == view
        assert list(reversed(view)) == expected[::-1]
        for start in range(-len(expected) - 1, len(expected) + 1):
            for stop in range(-len(expected) - 1, len(expected) + 1):
                assert list(view[start:stop]) == expected[start:stop]
        assert list(view[::2]) == expected[::2]
        assert view[-1] == expected[-1]
        with pytest.raises(IndexError):
            view[len(expected)]


@monitor
def r7_holds_the_first_after_stage(
    after_started: Any, second_before: Any
) -> MonitorGroup:
    """Keep the first generate's after-stage open until the second generate's before-stage has run."""

    async def before_generate(
        context: Context, step: BeforeGenerate
    ) -> Observation | None:
        if step.input[-1].text == "second":
            second_before.set()
        return None

    async def after_generate(
        context: Context, step: AfterGenerate
    ) -> Observation | None:
        if step.input[-1].text == "first":
            after_started.set()
            await second_before.wait()
        return None

    return MonitorGroup(before_generate, after_generate)


@solver
def r7_generates_while_an_after_stage_runs(after_started: Any) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()

        async def first() -> ModelOutput:
            return await model.generate([ChatMessageUser(content="first")])

        async def second() -> ModelOutput:
            await after_started.wait()
            return await model.generate([ChatMessageUser(content="second")])

        await tg_collect([first, second])
        return state

    return solve


def test_a_generate_while_another_after_stage_runs_replays_as_it_ran() -> None:
    after_started, second_before = anyio.Event(), anyio.Event()
    replay = assert_replay_equals_live(
        r7_generates_while_an_after_stage_runs(after_started),
        outputs(done("first answer"), done("second answer")),
        sentinel=[r7_holds_the_first_after_stage(after_started, second_before)],
    )
    assert len([step for step in replay if step.stage == "model_input"]) == 2


@tool
def asks_a_helper() -> Tool:
    async def execute() -> str:
        """Have a helper model propose a call, and run it."""
        helper_model = outputs(call("addition", x=4, y=5))
        output = await helper_model.generate("Add 4 and 5.", [addition()])
        result = await execute_tools(
            [ChatMessageUser(content="Add 4 and 5."), output.message], [addition()]
        )
        return result.messages[0].text

    return execute


def test_a_call_a_tool_s_helper_model_proposes_replays_as_it_ran() -> None:
    replay = assert_replay_equals_live(
        tool_loop(asks_a_helper()), outputs(call("asks_a_helper"), done())
    )
    # the helper's call is checked live (a tool's region is not final), and
    # replayed though its producer is not an agent turn
    assert ("tool_result", "addition") in {
        (step.stage, step.step.call.function)
        for step in replay
        if isinstance(step.step, AfterToolCall)
    }


def test_a_viewer_that_rejects_the_call_leaves_no_step() -> None:
    replay = assert_replay_equals_live(
        tool_loop(addition_raising_viewer()),
        outputs(call("addition_raising_viewer", x=1, y=1), done()),
    )
    assert not [step for step in replay if step.stage.startswith("tool")]


@tool
def refuses() -> Tool:
    async def execute() -> str:
        """Refuse, as an approval would."""
        raise ToolApprovalError("not today")

    return execute


@tool
def misparses() -> Tool:
    async def execute() -> str:
        """Fail, as a call with invalid arguments would."""
        raise ToolParsingError("not a number")

    return execute


@monitor
def r7_counts_tool_calls(seen: list[Any]) -> MonitorGroup:
    async def before_call(context: Context, step: BeforeToolCall) -> Observation | None:
        seen.append(step)
        return None

    return MonitorGroup(before_call)


@pytest.mark.parametrize(
    "raises,name", [(refuses, "refuses"), (misparses, "misparses")]
)
def test_a_tool_that_raises_an_oversight_error_itself_is_a_known_difference(
    raises: Callable[[], Tool], name: str
) -> None:
    # known difference: with every instance abstaining, the log of a tool that
    # raises ToolApprovalError or ToolParsingError itself reads as a call
    # rejected before its step was built, so replay gives it no tool steps
    seen: list[Any] = []
    log = run_logged(
        tool_loop(raises()),
        outputs(call(name), done()),
        sentinel=[r7_counts_tool_calls(seen)],
    )
    assert len(seen) == 1
    assert not [s for s in replayed(log) if s.stage.startswith("tool")]


@approver
def r7_decides(decision: str) -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        if decision == "modify":
            return Approval(
                decision="modify",
                modified=replace(call, arguments={**call.arguments, "x": 7}),
                explanation="seven",
            )
        return Approval(
            decision=cast(ApprovalDecision, decision), explanation=f"{decision} it"
        )

    return approve


@solver
def r7_continues_after_a_termination() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        tools = [addition()]
        for _ in range(2):
            output = await model.generate(state.messages, tools)
            state.messages.append(output.message)
            if not output.message.tool_calls:
                break
            try:
                result = await execute_tools(state.messages, tools)
                state.messages.extend(result.messages)
            except TerminateSampleError:
                state.messages.append(ChatMessageUser(content="carry on"))
        return state

    return solve


@pytest.mark.parametrize(
    "decision,action",
    [("reject", "reject"), ("modify", "modify"), ("terminate", "terminate")],
)
def test_a_person_s_approval_decision_reaches_later_steps(
    decision: str, action: str
) -> None:
    solver_ = (
        r7_continues_after_a_termination()
        if decision == "terminate"
        else tool_loop(addition())
    )
    log = run_logged(
        solver_,
        agent_model(2),
        approval=[ApprovalPolicy(r7_decides(decision), "*")],
    )
    sample = logged_sample(log)
    [approver_name] = {
        e.approver for e in sample.events if isinstance(e, ApprovalEvent)
    }
    replay = steps_from_events(
        sample.messages,
        sample.events,
        [],
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
        human_approvers=(approver_name,),
    )
    last = [s for s in replay if s.stage == "model_input"][-1]
    decisions = last.step.human_decisions or []
    assert decisions, [s.stage for s in replay]
    assert decisions[0].decided.report.action == action
    # the person decided before the call ran, so its own result step sees it
    for after in [s for s in replay if s.stage == "tool_result"]:
        assert [d.step_id for d in after.step.human_decisions or []][-1:] == [after.id]


def tool_steps(steps: Sequence["ReplayStep"]) -> list[tuple[Any, ...]]:
    return [
        (
            s.stage,
            s.id,
            s.step.call.function,
            s.step.call.arguments,
            s.step.result.text if isinstance(s.step, AfterToolCall) else None,
        )
        for s in steps
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
    ]


# transcripts shaped as Scout's importers write them, built by hand: no
# origins, no tools offered, and model inputs expanded


def imported_call(
    uuid: str, input: Sequence[ChatMessage], span_id: str, *calls: ToolCall
) -> ModelEvent:
    return ModelEvent(
        uuid=uuid,
        span_id=span_id,
        model="imported",
        input=list(input),
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(
            model="imported",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=f"turn {uuid}",
                        tool_calls=list(calls) or None,
                        model="imported",
                    ),
                    stop_reason="tool_calls" if calls else "stop",
                )
            ],
        ),
    )


def imported_conversation(
    span_id: str, *turns: list[ToolCall]
) -> tuple[list[ChatMessage], list[ModelEvent]]:
    """A model call for each of `turns` and one for the final answer, each call answered by a tool message `result of <id> in turn <n>`."""
    messages: list[ChatMessage] = [ChatMessageUser(content="Find the config file.")]
    calls: list[ModelEvent] = []
    for n, turn in enumerate([*turns, []]):
        event = imported_call(f"m{n}", messages, span_id, *turn)
        calls.append(event)
        messages.append(event.output.message)
        messages.extend(
            ChatMessageTool(
                content=f"result of {call.id} in turn {n}",
                tool_call_id=call.id,
                function=call.function,
            )
            for call in turn
        )
    return messages, calls


def imported_tool_event(
    call: ToolCall,
    turn: int,
    span_id: str,
    id: str | None = None,
    function: str | None = None,
) -> ToolEvent:
    return ToolEvent(
        id=id or call.id,
        function=function or call.function,
        arguments=call.arguments,
        result=f"result of {call.id} in turn {turn}",
        span_id=span_id,
    )


READ = ToolCall(id="call_read", function="read_file", arguments={"path": "a.cfg"})
LIST = ToolCall(id="call_list", function="list_dir", arguments={"path": "."})
GREP = ToolCall(id="call_grep", function="grep", arguments={"pattern": "port"})


def as_copies(
    messages: list[ChatMessage], calls: list[ModelEvent]
) -> tuple[list[ChatMessage], list[ModelEvent]]:
    """The conversation as LangSmith and Weave write it: each model call's output, in the messages and in later inputs, a copy without its id or model."""
    copies = {
        id(event.output.message): event.output.message.model_copy(
            update={"id": f"copy-{event.uuid}", "model": None}
        )
        for event in calls
    }

    def copied(written: list[ChatMessage]) -> list[ChatMessage]:
        return [copies.get(id(m), m) for m in written]

    return copied(messages), [
        event.model_copy(update={"input": copied(event.input)}) for event in calls
    ]


def claude_code_transcript() -> tuple[list[ChatMessage], list[Event]]:
    # a Task call is written in the sub-agent's span, with no tool span; a
    # Bash call in its tool span
    task = ToolCall(id="toolu_task", function="Task", arguments={"prompt": "Look."})
    bash = ToolCall(id="toolu_bash", function="Bash", arguments={"command": "ls"})
    messages, (m0, m1, m2) = imported_conversation("session", [task], [bash])
    task_event = imported_tool_event(task, 0, "agent-toolu_task")
    task_event.agent_span_id = "agent-toolu_task"
    return messages, [
        SpanBeginEvent(id="session", name="session", type="agent"),
        m0,
        SpanBeginEvent(
            id="agent-toolu_task", name="Explore", type="agent", parent_id="session"
        ),
        task_event,
        imported_call("sub", [ChatMessageUser(content="Look.")], "agent-toolu_task"),
        SpanEndEvent(id="agent-toolu_task"),
        m1,
        SpanBeginEvent(id="tool-bash", name="Bash", type="tool", parent_id="session"),
        imported_tool_event(bash, 1, "tool-bash"),
        SpanEndEvent(id="tool-bash"),
        m2,
        SpanEndEvent(id="session"),
    ]


def spanless_transcript(
    span_type: str | None, tool_event_ids: bool, copies: bool
) -> tuple[list[ChatMessage], list[Event]]:
    # ToolEvents in the run's span, with the call's id or with their own
    messages, calls = imported_conversation("run", [READ, LIST], [GREP])
    if copies:
        messages, calls = as_copies(messages, calls)
    m0, m1, m2 = calls

    def tool_event(call: ToolCall, turn: int) -> ToolEvent:
        if tool_event_ids:
            return imported_tool_event(call, turn, "run")
        return imported_tool_event(
            call, turn, "run", id=f"run-{call.id}", function=f"tools.{call.function}"
        )

    return messages, [
        SpanBeginEvent(id="run", name="agent run", type=span_type),
        m0,
        *[tool_event(call, 0) for call in [READ, LIST]],
        m1,
        tool_event(GREP, 1),
        m2,
        SpanEndEvent(id="run"),
    ]


def atif_transcript() -> tuple[list[ChatMessage], list[Event]]:
    # model calls in an agent span, and no ToolEvents
    messages, calls = imported_conversation("terminus", [READ, LIST], [GREP])
    return messages, [
        SpanBeginEvent(id="terminus", name="terminus_2", type="agent"),
        *calls,
        SpanEndEvent(id="terminus"),
    ]


IMPORTERS: dict[str, Callable[[], tuple[list[ChatMessage], list[Event]]]] = {
    "claude_code": claude_code_transcript,
    # Phoenix: a chain span of no type, ToolEvents keyed by the call's id
    "phoenix": partial(spanless_transcript, None, True, False),
    # Logfire: an agent span, ToolEvents keyed by the call's id
    "logfire": partial(spanless_transcript, "agent", True, False),
    # LangSmith: an agent span, ToolEvents keyed by their run's id, and copies
    # of each output in the messages and later inputs
    "langsmith": partial(spanless_transcript, "agent", False, True),
    # Weave: a span of no type, ToolEvents keyed by their call's id in Weave,
    # and copies of each output
    "weave": partial(spanless_transcript, None, False, True),
    "atif": atif_transcript,
}


@pytest.mark.parametrize("importer", IMPORTERS)
def test_an_imported_transcript_is_replayed_from_its_messages(importer: str) -> None:
    # a transcript with no log header is replayed by sentinel's messages
    # projection, not from its events
    messages, events = IMPORTERS[importer]()

    with pytest.raises(
        ValueError, match="Replay this transcript from its messages instead"
    ):
        steps_from_events(
            messages,
            events,
            [],
            sample_uuid="transcript",
            eval_info=cast(EvalInfo, None),
        )


@tool
def not_found() -> Tool:
    async def execute() -> str:
        """Fail with a tool error."""
        raise ToolError("not found")

    return execute


def test_a_call_a_fail_fast_tool_halted_has_no_tool_steps() -> None:
    # Inspect writes the halted call's ToolEvent without a tool span; live ran
    # no tool stage for it, so replay of a log Inspect wrote builds none
    def model() -> Any:
        halting = calls(("not_found", {}), ("not_found", {}))
        halting.message.metadata = {TOOL_CALLS_FAIL_FAST: ["not_found"]}
        return outputs(halting, done())

    replay = assert_replay_equals_live(tool_loop(not_found()), model())
    log = run_logged(tool_loop(not_found()), model())
    sample = logged_sample(log)
    [halted] = [
        index
        for index, e in enumerate(sample.events)
        if isinstance(e, ToolEvent) and e.id == "t0c1"
    ]
    assert not isinstance(sample.events[halted - 1], SpanBeginEvent)
    assert [(s.stage, s.id) for s in replay if s.stage.startswith("tool")] == [
        ("tool_call", "t0c0"),
        ("tool_result", "t0c0"),
    ]


@pytest.mark.parametrize("version", ["0.3.100", "0.3.200"])
def test_an_inspect_log_s_calls_without_a_tool_span_keep_no_tool_steps(
    version: str | None,
) -> None:
    # live runs no tool stage for a call it records without a tool span (a
    # call not executed after an earlier one failed), so a log written by
    # Inspect, with or without a version in its header, keeps reading its
    # calls from events
    messages, events = spanless_transcript(None, True, False)
    replay = steps_from_events(
        messages,
        events,
        [],
        sample_uuid="transcript",
        eval_info=EvalInfo(inspect_ai_version=version, sentinel=False),
    )

    assert tool_steps(replay) == []


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("message_ids", [False, True])
@pytest.mark.parametrize("uuids", [False, True])
@pytest.mark.parametrize(
    "version", ["0.3.43", "0.3.93", "0.3.94", "0.3.99", "0.3.100.dev1", "0.3.100rc1"]
)
def test_a_log_before_0_3_100_is_refused(
    inputs: str, message_ids: bool, uuids: bool, version: str
) -> None:
    from inspect_ai._sentinel import _replay

    user = ChatMessageUser(content="Find the setting")
    call = ToolCall(id="lookup-call", function="lookup", arguments={})
    first = linked_call("first", "agent", [user], "Looking", None, call)
    first.tools = [ToolInfo(name="lookup", description="Find the setting")]
    result = ChatMessageTool(content="found", tool_call_id=call.id, function="lookup")
    second = linked_call(
        "second", "agent", [user, first.output.message, result], "Done", None
    )
    if not message_ids:
        user.id = None
        first.output.message.id = None
        result.id = None
        second.output.message.id = None
    if not uuids:
        first.uuid = None
        second.uuid = None
    events: list[Event] = [
        SpanBeginEvent(id="agent", name="agent", type="agent"),
        first,
        ToolEvent(
            id=call.id,
            function="lookup",
            arguments={},
            result="found",
            message_id=result.id,
            span_id="agent",
        ),
        second,
        SpanEndEvent(id="agent"),
    ]
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    with pytest.raises(
        ValueError,
        match="0.3.100 or later.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            [user, first.output.message, result, second.output.message],
            events,
            pool,
            sample_uuid="sample",
            eval_info=EvalInfo(inspect_ai_version=version, sentinel=False),
        )


@pytest.mark.parametrize("version", ["0.3.43", "0.3.93", "0.3.200"])
@pytest.mark.parametrize("depth", [1, 2])
@pytest.mark.parametrize("execution_error", [False, True])
def test_nested_tool_events_are_refused_after_json_read(
    version: str, depth: int, execution_error: bool, tmp_path: Path
) -> None:
    log = run_logged(tool_loop(addition()), agent_model())
    assert log.location
    stored = read_eval_log(log.location)
    [sample] = stored.samples or []
    model_call = next(event for event in sample.events if isinstance(event, ModelEvent))
    inner = ToolEvent(
        id="inner",
        function="addition",
        arguments={},
        result="2",
        error=(
            ToolCallError(type="timeout", message="timed out")
            if execution_error
            else None
        ),
    )
    outer = ToolEvent(
        id="outer",
        function="handoff",
        arguments={},
        result="done",
        events=[model_call, inner],
    )
    if depth == 2:
        outer = ToolEvent(
            id="outermost",
            function="handoff",
            arguments={},
            result="done",
            events=[outer],
        )
    sample.events = [outer]
    stored.eval.packages["inspect_ai"] = version
    path = tmp_path / "legacy.json"
    write_eval_log(stored, path)
    reread = read_eval_log(str(path))
    [persisted] = reread.samples or []
    [parent] = persisted.events
    assert isinstance(parent, ToolEvent)
    assert isinstance(parent.events[0], dict)
    with pytest.raises(
        ValueError,
        match="0.3.100 or later.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            persisted.messages,
            persisted.events,
            [],
            sample_uuid=persisted.uuid or "",
            eval_info=EvalInfo.from_eval(reread.eval),
        )


@pytest.mark.parametrize("version", [None, "unknown"])
@pytest.mark.parametrize("serialized", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_unknown_version_refuses_nested_spanless_native_tool(
    version: str | None, serialized: bool, failed: bool
) -> None:
    inner = ToolEvent(
        id="inner",
        function="addition",
        arguments={},
        result="2",
        completed=datetime.now(timezone.utc),
        failed=failed,
    )
    outer = ToolEvent(
        id="outer", function="handoff", arguments={}, result="done", events=[inner]
    )
    if serialized:
        outer = ToolEvent.model_validate_json(outer.model_dump_json())
        assert isinstance(outer.events[0], dict)
    events: list[Event] = [
        SpanBeginEvent(id="outer-span", name="handoff", type="tool"),
        outer,
        SpanEndEvent(id="outer-span"),
    ]
    with pytest.raises(
        ValueError,
        match="0.3.100 or later.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            [], events, [], sample_uuid="sample", eval_info=EvalInfo(version, False)
        )


@pytest.mark.parametrize("version", [None, "unknown"])
@pytest.mark.parametrize("serialized", [False, True])
def test_unknown_version_keeps_failed_tool_with_matching_span(
    version: str | None, serialized: bool
) -> None:
    messages, events, pool = _historical_approval_events("expanded", "approve", True)
    tool = next(event for event in events if isinstance(event, ToolEvent))
    tool.failed = True
    tool.completed = datetime.now(timezone.utc)
    if serialized:
        adapter = TypeAdapter(list[Event])
        events = adapter.validate_json(adapter.dump_json(events))
    replay = steps_from_events(
        messages,
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo(version, False),
    )
    assert [step.stage for step in replay if step.stage.startswith("tool")] == [
        "tool_call"
    ]


@pytest.mark.parametrize("version", [None, "unknown", "0.3.100", "0.3.200"])
@pytest.mark.parametrize("finalized", [False, True])
@pytest.mark.parametrize("serialized", [False, True])
def test_spanless_halted_tool_is_allowed(
    version: str | None, finalized: bool, serialized: bool
) -> None:
    halted = ToolEvent(
        id="halted",
        function="addition",
        arguments={},
        pending=None if finalized else True,
        completed=datetime.now(timezone.utc) if finalized else None,
        error=(
            ToolCallError(type="cancelled", message="earlier call failed")
            if finalized
            else None
        ),
    )
    if serialized:
        halted = ToolEvent.model_validate_json(halted.model_dump_json())
    events: list[Event] = [halted]
    assert (
        steps_from_events(
            [], events, [], sample_uuid="sample", eval_info=EvalInfo(version, False)
        )
        == []
    )


@pytest.mark.parametrize("version", [None, "unknown", "0.3.100", "0.3.200"])
def test_spanless_timeout_is_refused_only_without_a_known_version(
    version: str | None,
) -> None:
    # Ransom's 39th review O1: cancelling a call awaiting approval records it
    # as an execution timeout of an older log does
    halted = ToolEvent(
        id="halted",
        function="addition",
        arguments={},
        completed=datetime.now(timezone.utc),
        error=ToolCallError(type="timeout", message="cancelled by operator"),
    )

    def replay() -> list["ReplayStep"]:
        return steps_from_events(
            [], [halted], [], sample_uuid="sample", eval_info=EvalInfo(version, False)
        )

    if version in (None, "unknown"):
        with pytest.raises(ValueError, match="0.3.100 or later"):
            replay()
    else:
        assert replay() == []


def answers_as_a_person(decision: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Have the built-in `human` approver's panel decide `decision`; a modify sets x to 7."""
    from inspect_ai.approval._human import acp as acp_module
    from inspect_ai.approval._human import approver as approver_module

    async def acp(**kwargs: object) -> Approval | None:
        return None

    async def panel(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: object,
        choices: list[str],
    ) -> Approval:
        if decision == "modify":
            return Approval(
                decision="modify",
                modified=replace(call, arguments={**call.arguments, "x": 7}),
                explanation="seven",
            )
        return Approval(
            decision=cast(ApprovalDecision, decision), explanation=f"{decision} it"
        )

    monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
    monkeypatch.setattr(approver_module, "panel_approval", panel)


@pytest.mark.parametrize(
    "decision,action",
    [
        ("approve", "proceed"),
        ("reject", "reject"),
        ("terminate", "terminate"),
        ("modify", "modify"),
        ("escalate", None),
    ],
)
def test_a_human_approver_s_decision_reaches_later_steps_in_a_log_without_origins(
    decision: str, action: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.approval import auto_approver, human_approver

    answers_as_a_person(decision, monkeypatch)
    policies = [ApprovalPolicy(human_approver(), "*")]
    if decision == "escalate":
        # the person passes the call on to the next approver
        policies.append(ApprovalPolicy(auto_approver(), "*"))
    log = run_logged(
        r7_continues_after_a_termination()
        if decision == "terminate"
        else tool_loop(addition()),
        agent_model(2),
        approval=policies,
    )
    sample = logged_sample(log)
    replay = steps_from_events(
        sample.messages,
        without_origins(sample.events),
        [],
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
        human_approvers=("human",),
    )
    # a call the person rejected or ended never reached its tool_call step
    first = next(e.id for e in sample.events if isinstance(e, ToolEvent))
    later = [s for s in replay if s.stage == "model_input"][-1]
    decisions = list(later.step.human_decisions or [])
    if action is None:
        assert decisions == []
        return
    assert decisions
    assert decisions[0].step_id == first
    assert decisions[0].call_ids == (first,)
    reported = decisions[0].decided
    assert (reported.name, reported.path) == ("human", "human")
    assert reported.report.action == action
    if action == "modify":
        assert reported.report.modified is not None
        assert reported.report.modified.arguments["x"] == 7


def _historical_approval_events(
    inputs: str, decision: str, legacy_arguments: bool
) -> tuple[list[ChatMessage], list[Event], list[ChatMessage]]:
    from inspect_ai._sentinel import _replay

    user = ChatMessageUser(content="Add one")
    proposal = ToolCall(id="c1", function="addition", arguments={"x": 1, "y": 1})
    approved = replace(proposal, arguments={"x": 7, "y": 1})
    first = linked_call("m1", "agent", [user], "Adding", None, proposal)
    first.tools = [ToolInfo(name="addition", description="Add numbers")]
    result_text = "8" if decision == "modify" else "2"
    result = ChatMessageTool(
        content=result_text, tool_call_id="c1", function="addition"
    )
    second = linked_call(
        "m2", "agent", [user, first.output.message, result], "Done", None
    )
    events: list[Event] = [
        SpanBeginEvent(id="agent", name="agent", type="agent"),
        first,
        ApprovalEvent(
            message="Adding",
            call=proposal,
            approver="human",
            decision=cast(ApprovalDecision, decision),
            modified=approved if decision == "modify" else None,
            span_id="agent",
        ),
    ]
    if decision in ("approve", "modify"):
        events.extend(
            [
                SpanBeginEvent(
                    id="tool", name="addition", type="tool", parent_id="agent"
                ),
                ToolEvent(
                    id="c1",
                    function="addition",
                    arguments=proposal.arguments
                    if legacy_arguments
                    else approved.arguments,
                    result=result_text,
                    message_id=result.id,
                    span_id="tool",
                ),
                SpanEndEvent(id="tool"),
            ]
        )
    events.extend([second, SpanEndEvent(id="agent")])
    events = solving(events)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    adapter = TypeAdapter(list[Event])
    return (
        [user, first.output.message, result, second.output.message],
        adapter.validate_json(adapter.dump_json(events)),
        pool,
    )


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_modern_approval_tool_stages_use_recorded_arguments(
    inputs: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    messages, events, pool = _historical_approval_events(inputs, "modify", False)
    replay = steps_from_events(
        messages,
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo("0.3.277", False),
        human_approvers=("human",),
    )
    assert [
        step.step.call.arguments
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ] == [{"x": 7, "y": 1}, {"x": 7, "y": 1}]
    later = next(
        step for step in replay if step.stage == "model_input" and step.id == "m2"
    )
    assert [
        decision.decided.report.action for decision in later.step.human_decisions or []
    ] == ["modify"]
    warnings = [
        record.message
        for record in caplog.records
        if "Skipped human decisions from ApprovalEvents" in record.message
    ]
    assert not warnings


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("decision", ["approve", "modify"])
def test_modern_approval_without_modified_payload_keeps_tool_stages(
    inputs: str, decision: str
) -> None:
    messages, events, pool = _historical_approval_events(inputs, "approve", True)
    approval = next(event for event in events if isinstance(event, ApprovalEvent))
    approval.decision = cast(ApprovalDecision, decision)
    adapter = TypeAdapter(list[Event])
    events = adapter.validate_json(adapter.dump_json(events))
    replay = steps_from_events(
        messages,
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo("0.3.277", False),
    )
    tool_steps = [
        step.step
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ]
    assert [step.call.arguments for step in tool_steps] == [
        {"x": 1, "y": 1},
        {"x": 1, "y": 1},
    ]
    assert isinstance(tool_steps[1], AfterToolCall)
    assert tool_steps[1].result.text == "2"


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("version", ["0.3.100", None, "0.3.277", "0.3.285", "0.3.300"])
@pytest.mark.parametrize("decision", ["approve", "modify"])
def test_modern_approval_uses_executed_tool_view_at_both_stages(
    inputs: str, version: str | None, decision: str
) -> None:
    """A ToolEvent that records the modified call replays whatever the header says."""
    from inspect_ai._sentinel import _replay

    path = Path(__file__).parent / "fixtures" / "approval_modified_0.3.100.json"
    log = read_eval_log(str(path), resolve_attachments="full")
    [sample] = log.samples or []
    events: list[Event] = []
    for event in sample.events:
        if isinstance(event, ApprovalEvent):
            event = event.model_copy(update={"decision": decision})
        elif isinstance(event, ToolEvent):
            event = event.model_copy(
                update={
                    "arguments": {"x": 7, "y": 1},
                    "view": ToolCallContent(
                        format="markdown",
                        content="```python\naddition(x=7, y=1)\n```\n",
                    ),
                }
            )
        events.append(event)
    adapter = TypeAdapter(list[Event])
    events = adapter.validate_json(adapter.dump_json(events))
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    replay = steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "sample",
        eval_info=EvalInfo(version, False),
    )
    tool_steps = [
        step.step
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ]
    assert [step.call.arguments for step in tool_steps] == [
        {"x": 7, "y": 1},
        {"x": 7, "y": 1},
    ]
    assert [
        step.view.call.content if step.view.call is not None else None
        for step in tool_steps
    ] == ["```python\naddition(x=7, y=1)\n```\n"] * 2
    assert tool_steps[0].view.context is None


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("decision", ["approve", "modify"])
@pytest.mark.parametrize("renamed", [False, True])
@pytest.mark.parametrize("version", ["0.3.100", "0.3.300", None])
def test_older_modified_approval_log_is_refused(
    inputs: str, decision: str, renamed: bool, version: str | None
) -> None:
    """The archived 0.3.100 sample cannot identify the executed call, even under the newer header a retried eval gives it."""
    from inspect_ai._sentinel import _replay

    path = Path(__file__).parent / "fixtures" / "approval_modified_0.3.100.json"
    log = read_eval_log(str(path), resolve_attachments="full")
    [sample] = log.samples or []
    approval = next(e for e in sample.events if isinstance(e, ApprovalEvent))
    assert approval.modified is not None
    events: list[Event] = []
    for event in sample.events:
        if event is approval:
            modified = (
                replace(approval.modified, function="renamed")
                if renamed
                else approval.modified
            )
            event = approval.model_copy(
                update={"decision": decision, "modified": modified}
            )
        elif renamed and isinstance(event, SpanBeginEvent) and event.type == "tool":
            event = event.model_copy(update={"name": "renamed"})
        events.append(event)
    adapter = TypeAdapter(list[Event])
    events = adapter.validate_json(adapter.dump_json(events))
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    # without a version, the renamed tool span reads as a log before 0.3.94
    refusal = (
        r"0\.3\.100 or later"
        if renamed and version is None
        else r"approved call does not match the ToolEvent that ran"
    )
    with pytest.raises(
        ValueError,
        match=rf"{refusal}.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            sample.messages,
            events,
            pool,
            sample_uuid=sample.uuid or "sample",
            eval_info=EvalInfo(version, False),
        )


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("version", [None, "unknown"])
def test_unknown_version_modified_approval_is_refused(
    inputs: str, version: str | None
) -> None:
    messages, events, pool = _historical_approval_events(inputs, "modify", True)
    with pytest.raises(
        ValueError,
        match=r"approved call does not match the ToolEvent that ran.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            messages,
            events,
            pool,
            sample_uuid="sample",
            eval_info=EvalInfo(version, False),
        )


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_older_unmodified_approval_still_replays(inputs: str) -> None:
    messages, events, pool = _historical_approval_events(inputs, "approve", True)
    replay = steps_from_events(
        messages,
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo("0.3.100", False),
    )
    tool_steps = [
        step.step
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ]
    assert [step.call.arguments for step in tool_steps] == [
        {"x": 1, "y": 1},
        {"x": 1, "y": 1},
    ]
    assert isinstance(tool_steps[1], AfterToolCall)
    assert tool_steps[1].result.text == "2"


@pytest.mark.parametrize("version", [None, "unknown"])
@pytest.mark.parametrize("serialized", [False, True])
def test_unknown_version_nested_modified_approval_is_refused_as_an_earlier_log(
    version: str | None, serialized: bool
) -> None:
    _, events, _ = _historical_approval_events("expanded", "modify", True)
    approval = next(e for e in events if isinstance(e, ApprovalEvent))
    outer = ToolEvent(id="outer", function="outer", arguments={}, events=[approval])
    if serialized:
        outer = ToolEvent.model_validate_json(outer.model_dump_json())
    with pytest.raises(
        ValueError,
        match="0.3.100 or later.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            [], [outer], [], sample_uuid="sample", eval_info=EvalInfo(version, False)
        )


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("decision", ["reject", "terminate"])
@pytest.mark.parametrize(
    "version,reconstruct",
    [
        ("0.3.100", False),
        ("0.3.276", False),
        ("0.3.277rc1", False),
        (None, False),
        ("unknown", False),
        ("0.3.277", True),
        ("0.3.300", True),
    ],
)
def test_approval_decision_without_tool_event_respects_log_version(
    inputs: str,
    decision: str,
    version: str | None,
    reconstruct: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    messages, events, pool = _historical_approval_events(inputs, decision, True)
    assert not any(isinstance(event, ToolEvent) for event in events)
    replay = steps_from_events(
        messages,
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo(version, False),
        human_approvers=("human",),
    )
    assert not [step for step in replay if step.stage.startswith("tool")]
    later = next(
        step for step in replay if step.stage == "model_input" and step.id == "m2"
    )
    decisions = list(later.step.human_decisions or [])
    assert [recorded.decided.report.action for recorded in decisions] == (
        [decision] if reconstruct else []
    )
    if reconstruct:
        assert decisions[0].step_id == "c1"
    warnings = [
        record.message
        for record in caplog.records
        if "Skipped human decisions from ApprovalEvents" in record.message
    ]
    assert len(warnings) == (0 if reconstruct else 1)


@pytest.mark.parametrize("human_approvers", [(), ("other",)])
def test_old_log_warns_only_for_selected_human_approvals(
    human_approvers: tuple[str, ...], caplog: pytest.LogCaptureFixture
) -> None:
    messages, events, pool = _historical_approval_events("expanded", "reject", True)
    steps_from_events(
        messages,
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo("0.3.100", False),
        human_approvers=human_approvers,
    )
    assert not [
        record
        for record in caplog.records
        if "Skipped human decisions from ApprovalEvents" in record.message
    ]


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize(
    "approval,sentinel_x,event_x,before_x,after_x",
    [
        (False, None, 1, 1, 1),
        (True, None, 7, 7, 7),
        (False, 9, 9, 1, 9),
        (True, 9, 9, 7, 9),
        (True, 1, 1, 7, 1),
    ],
)
def test_recorded_sentinel_change_controls_executed_arguments(
    inputs: str,
    approval: bool,
    sentinel_x: int | None,
    event_x: int,
    before_x: int,
    after_x: int,
) -> None:
    messages, events, pool = _historical_approval_events(inputs, "modify", True)
    if not approval:
        events = [event for event in events if not isinstance(event, ApprovalEvent)]
    tool = next(event for event in events if isinstance(event, ToolEvent))
    tool.arguments = {"x": event_x, "y": 1}
    if sentinel_x is not None:
        proposal = ToolCall(id="c1", function="addition", arguments={"x": 1, "y": 1})
        check: list[Event] = [
            SpanBeginEvent(
                id="check", name="probe", type="sentinel", parent_id="agent"
            ),
            SentinelEvent(
                factory="probe",
                path="probe",
                function="check",
                step_id="c1",
                conversation="agent",
                stage="tool_call",
                kind="decision",
                status="reported",
                action="modify",
                modified=replace(proposal, arguments={"x": sentinel_x, "y": 1}),
                span_id="check",
            ),
            SpanEndEvent(id="check"),
        ]
        begin = next(
            index
            for index, event in enumerate(events)
            if isinstance(event, SpanBeginEvent) and event.id == "tool"
        )
        events[begin:begin] = check
    adapter = TypeAdapter(list[Event])
    events = adapter.validate_json(adapter.dump_json(events))
    replay = steps_from_events(
        messages,
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo("0.3.277", sentinel_x is not None),
        human_approvers=("human",),
    )
    assert [
        step.step.call.arguments["x"]
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ] == [before_x, after_x]


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_sentinel_modify_does_not_match_a_different_json_argument_type(
    inputs: str, caplog: pytest.LogCaptureFixture
) -> None:
    messages, events, pool = _historical_approval_events(inputs, "approve", True)
    events = [event for event in events if not isinstance(event, ApprovalEvent)]
    proposal = ToolCall(id="c1", function="addition", arguments={"x": 1, "y": 1})
    check: list[Event] = [
        SpanBeginEvent(id="check", name="probe", type="sentinel", parent_id="agent"),
        SentinelEvent(
            factory="probe",
            path="probe",
            function="check",
            step_id="c1",
            conversation="agent",
            stage="tool_call",
            kind="decision",
            status="reported",
            action="modify",
            modified=replace(proposal, arguments={"x": True, "y": 1}),
            span_id="check",
        ),
        SpanEndEvent(id="check"),
    ]
    begin = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, SpanBeginEvent) and event.id == "tool"
    )
    events[begin:begin] = check
    adapter = TypeAdapter(list[Event])
    events = adapter.validate_json(adapter.dump_json(events))
    with caplog.at_level(logging.WARNING):
        replay = steps_from_events(
            messages,
            events,
            pool,
            sample_uuid="sample",
            eval_info=EvalInfo("0.3.277", True),
        )
    # the modify's x=True doesn't match the ToolEvent's x=1, so the call is
    # skipped as one whose tool rewrote its modify's arguments
    assert not any(
        isinstance(step.step, BeforeToolCall | AfterToolCall) for step in replay
    )
    assert replay_warnings(caplog) == [UNMATCHED_MODIFY.format("'c1'")]


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("decision", ["reject", "terminate"])
@pytest.mark.parametrize("reused_id", [True, False])
@pytest.mark.parametrize("later_approval", [True, False])
def test_a_prior_decision_survives_a_later_execution_with_reused_id(
    inputs: str, decision: str, reused_id: bool, later_approval: bool
) -> None:
    from inspect_ai._sentinel import _replay

    messages, events, _ = _historical_approval_events("expanded", decision, True)
    del events[-2:]
    later_id = "c1" if reused_id else "c2"
    proposal = ToolCall(id=later_id, function="addition", arguments={"x": 2, "y": 1})
    later = linked_call("m3", "agent", messages, "Try again", None, proposal)
    later.tools = [ToolInfo(name="addition", description="Add numbers")]
    result = ChatMessageTool(content="3", tool_call_id=later_id, function="addition")
    final = linked_call(
        "m4", "agent", [*messages, later.output.message, result], "Done", None
    )
    events.append(later)
    if later_approval:
        events.append(
            ApprovalEvent(
                message="Try again",
                call=proposal,
                approver="human",
                decision="approve",
                span_id="agent",
            )
        )
    events.extend(
        [
            SpanBeginEvent(
                id="later-tool", name="addition", type="tool", parent_id="agent"
            ),
            ToolEvent(
                id=later_id,
                function="addition",
                arguments=proposal.arguments,
                result="3",
                message_id=result.id,
                span_id="later-tool",
            ),
            SpanEndEvent(id="later-tool"),
            final,
            SpanEndEvent(id="agent"),
            SpanEndEvent(id="solvers"),
        ]
    )
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    adapter = TypeAdapter(list[Event])
    events = adapter.validate_json(adapter.dump_json(events))
    replay = steps_from_events(
        [*messages, later.output.message, result, final.output.message],
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo("0.3.277", False),
        human_approvers=("human",),
    )
    intervening = next(
        step for step in replay if step.stage == "model_input" and step.id == "m2"
    )
    assert [
        recorded.decided.report.action
        for recorded in intervening.step.human_decisions or []
    ] == [decision]
    assert [step.stage for step in replay if step.stage.startswith("tool")] == [
        "tool_call",
        "tool_result",
    ]


@tool
def times_out() -> Tool:
    async def execute() -> str:
        """Run out of time."""
        raise TimeoutError()

    return execute


def test_a_tool_s_own_timeout_keeps_its_result_step() -> None:
    replay = assert_replay_equals_live(
        tool_loop(times_out()), outputs(call("times_out"), done())
    )
    assert [s.stage for s in replay if s.stage.startswith("tool")] == [
        "tool_call",
        "tool_result",
    ]


# review pass 2: grouping by input, the rules each stated case pins, ids,
# lookups and malformed ranges


@solver
def r7_generates_two_different_inputs_at_once() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()

        async def ask(text: str) -> ModelOutput:
            return await model.generate([ChatMessageUser(content=text)])

        await tg_collect([partial(ask, "first"), partial(ask, "second")])
        return state

    return solve


def test_overlapping_generates_with_different_inputs_keep_their_retries_apart() -> None:
    _Interleaved.requests = 0
    _Interleaved.second = anyio.Event()
    replay = assert_replay_equals_live(
        r7_generates_two_different_inputs_at_once(), "r7_interleaved/model"
    )
    assert len([s for s in replay if s.stage == "model_output"]) == 2


@solver
def r7_carries_on_after_a_failed_batch() -> Solver:
    """Two turns; a batch that raises is caught and the run continues."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        tools = state.tools
        for _ in range(2):
            output = await model.generate(state.messages, tools)
            state.messages.append(output.message)
            if not output.message.tool_calls:
                break
            try:
                result = await execute_tools(state.messages, tools)
                state.messages.extend(result.messages)
            except Exception:
                state.messages.append(ChatMessageUser(content="carry on"))
        return state

    return solve


@tool
def raises_value_error() -> Tool:
    async def execute() -> str:
        """Fail with an error that escapes the call's own handling."""
        raise ValueError("not a tool error")

    return execute


@pytest.mark.parametrize(
    "failing,name", [(explodes, "explodes"), (raises_value_error, "raises_value_error")]
)
def test_a_batch_that_raised_appends_nothing_when_the_scaffold_carries_on(
    failing: Callable[[], Tool], name: str
) -> None:
    # explodes() records failed; a ValueError escaping call_tool_task is
    # finalised by its stage as a cancelled call that failed
    replay = assert_replay_equals_live(
        [use_tools(failing()), r7_carries_on_after_a_failed_batch()],
        outputs(call(name), done()),
    )
    assert not [s for s in replay if s.stage == "tool_result"]


class _FailsOnce(MockLLM):
    """The first request fails with an error that is not retried."""

    requests = 0

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: Any,
        config: GenerateConfig,
    ) -> Any:
        _FailsOnce.requests += 1
        if _FailsOnce.requests == 1:
            raise RuntimeError("provider down")
        return done()


@modelapi(name="r7_fails_once")
def r7_fails_once() -> type[ModelAPI]:
    return _FailsOnce


@solver
def r7_retries_with_a_changed_input() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        try:
            await model.generate([ChatMessageUser(content="first try")])
        except RuntimeError:
            pass
        state.output = await model.generate([ChatMessageUser(content="second try")])
        return state

    return solve


def test_a_retry_with_a_changed_input_is_a_generate_of_its_own() -> None:
    _FailsOnce.requests = 0
    replay = assert_replay_equals_live(
        r7_retries_with_a_changed_input(), "r7_fails_once/model"
    )
    assert [s.stage for s in replay] == ["model_input", "model_input", "model_output"]


@solver
def r7_runs_a_helpers_call_in_its_region() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        tools = [addition()]
        with model_origin("helper"):
            output = await get_model().generate(state.messages, tools)
            await execute_tools([*state.messages, output.message], tools)
        state.output = await get_model().generate(state.messages)
        return state

    return solve


def test_a_call_run_in_a_final_region_has_no_tool_steps() -> None:
    replay = assert_replay_equals_live(
        r7_runs_a_helpers_call_in_its_region(),
        outputs(call("addition", x=1, y=1), done()),
        # a model_origin() region is not in the span tree, so without origins
        # the helper's call is a turn and its calls are checked
        inferred="a model_origin() region",
    )
    assert not [s for s in replay if s.stage.startswith("tool")]


@scorer(metrics=[])
def r7_scores_with_a_tool_loop() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        tools = [addition()]
        output = await get_model().generate("Check the sum.", tools)
        await execute_tools(
            [ChatMessageUser(content="Check the sum."), output.message], tools
        )
        return Score(value=1)

    return score


def test_a_task_scorer_s_tool_calls_have_no_tool_steps() -> None:
    replay = assert_replay_equals_live(
        generate(),
        outputs(done(), call("addition", x=1, y=1)),
        scorer=r7_scores_with_a_tool_loop(),
    )
    assert not [s for s in replay if s.stage.startswith("tool")]


@scorer(metrics=[])
def r7_scores_with_a_helper_tool() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        tools = [asks_a_helper()]
        output = await get_model().generate("Check the sum.", tools)
        await execute_tools(
            [ChatMessageUser(content="Check the sum."), output.message], tools
        )
        return Score(value=1)

    return score


@scorer(metrics=[])
def r7_scores_in_an_agent_span() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        async with span("checker", type="agent"):
            tools = [asks_a_helper()]
            output = await get_model().generate("Check the sum.", tools)
            await execute_tools(
                [ChatMessageUser(content="Check the sum."), output.message], tools
            )
        return Score(value=1)

    return score


@pytest.mark.parametrize("arrangement", ["helper_tool", "agent_span"])
def test_a_task_scorer_s_nested_calls_have_no_tool_steps_without_origins(
    arrangement: str,
) -> None:
    # Ransom's fourth review: the scorers' scope is final live, through a
    # tool whose helper model proposes and runs a call, directly or inside an
    # agent span; with origins removed their calls are a scorer's, and none
    # has tool steps
    replay = assert_replay_equals_live(
        generate(),
        outputs(done(), call("asks_a_helper")),
        scorer=r7_scores_with_a_helper_tool()
        if arrangement == "helper_tool"
        else r7_scores_in_an_agent_span(),
    )
    assert [s.stage for s in replay] == ["model_input", "model_output"]


@scorer(metrics=[])
def r7_scores_with_a_prefilled_call() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        prefilled = ChatMessageAssistant(content="", tool_calls=[addition_call("p")])
        asked: list[ChatMessage] = [ChatMessageUser(content="Check."), prefilled]
        result = await execute_tools(asked, [addition()])
        await get_model().generate([*asked, *result.messages])
        return Score(value=1)

    return score


def test_a_pre_filled_call_a_scorer_runs_has_no_tool_steps() -> None:
    # review of 06bf969be: a call no model call made, run in the scorers'
    # final scope, was taken as checked, with origins recorded or not
    replay = assert_replay_equals_live(
        generate(),
        outputs(done(), done("ok")),
        scorer=r7_scores_with_a_prefilled_call(),
    )
    assert [s.stage for s in replay] == ["model_input", "model_output"]


def test_a_log_from_before_tool_spans_is_refused() -> None:
    # Inspect 0.3.43 recorded the scorer phase with StepEvents, but cannot
    # supply the native tool spans required for reliable replay.
    log = read_eval_log(
        str(Path(__file__).parent.parent / "log" / "test_list_logs" / "custom.eval"),
        resolve_attachments="full",
    )
    [sample] = log.samples or []
    with pytest.raises(
        ValueError,
        match="0.3.100 or later.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            sample.messages,
            sample.events,
            [],
            sample_uuid=sample.uuid or "sample",
            eval_info=EvalInfo.from_eval(log.eval),
        )


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("versioned", [True, False])
def test_the_archived_0_3_99_log_is_refused(inputs: str, versioned: bool) -> None:
    # Inspect 0.3.99 ran each solver in a top-level span, with no solvers span;
    # without its version the layout alone refuses it
    from inspect_ai._sentinel import _replay

    path = Path(__file__).parent / "fixtures" / "approval_modified_0.3.99.json"
    log = read_eval_log(str(path), resolve_attachments="full")
    [sample] = log.samples or []
    events: list[Event] = list(sample.events)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    with pytest.raises(
        ValueError,
        match="0.3.100 or later.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            sample.messages,
            events,
            pool,
            sample_uuid=sample.uuid or "sample",
            eval_info=EvalInfo.from_eval(log.eval)
            if versioned
            else EvalInfo(None, False),
        )


@scorer(metrics=[])
def constant() -> Scorer:
    async def apply(state: TaskState, target: Target) -> Score:
        return Score(value=1)

    return apply


def rescored(log: EvalLog, action: Literal["append", "overwrite"] | None) -> EvalLog:
    from inspect_ai import score

    if action is None:
        return log
    return score(log.model_copy(deep=True), constant(), action=action, display="none")


def replay_sample(
    log: EvalLog, origins: bool, inputs: str, versioned: bool = True
) -> list["ReplayStep"]:
    from inspect_ai._sentinel import _replay

    [sample] = log.samples or []
    sample = EvalSample.model_validate_json(sample.model_dump_json())
    events = sample.events if origins else without_origins(sample.events)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    return steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "sample",
        eval_info=EvalInfo.from_eval(log.eval) if versioned else EvalInfo(None, False),
    )


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("action", ["append", "overwrite"])
@pytest.mark.parametrize("approval", ["unchanged", "none"])
def test_a_rescored_then_retried_0_3_99_sample_is_refused(
    inputs: str, action: Literal["append", "overwrite"], approval: str
) -> None:
    # Ransom's review 37 B1: rescoring adds a top-level scorers span to an
    # older sample, which a retried eval keeps under a newer header; the
    # approval is left unchanged so only the layout refuses it
    from inspect_ai._sentinel import _replay

    path = Path(__file__).parent / "fixtures" / "approval_modified_0.3.99.json"
    log = rescored(read_eval_log(str(path), resolve_attachments="full"), action)
    [sample] = log.samples or []
    sample = EvalSample.model_validate_json(sample.model_dump_json())
    assert any(
        isinstance(e, SpanBeginEvent) and e.parent_id is None and e.name == "scorers"
        for e in sample.events
    )
    events: list[Event] = [
        e.model_copy(update={"decision": "approve", "modified": None})
        if isinstance(e, ApprovalEvent)
        else e
        for e in sample.events
        if approval == "unchanged" or not isinstance(e, ApprovalEvent)
    ]
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    with pytest.raises(
        ValueError,
        match="0.3.100 or later.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            sample.messages,
            events,
            pool,
            sample_uuid=sample.uuid or "sample",
            eval_info=EvalInfo("0.3.200", False),
        )


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("origins", [True, False])
@pytest.mark.parametrize("cleanup", [False, True])
@pytest.mark.parametrize("action", ["append", "overwrite"])
@pytest.mark.parametrize("shape", ["call", "parallel", "handoff", "store_handoff"])
def test_a_rescored_log_replays_its_tool_stages(
    shape: str,
    action: Literal["append", "overwrite"],
    cleanup: bool,
    origins: bool,
    inputs: str,
) -> None:
    # Review of 76e89a08b: rescoring rebuilds the events from the span tree,
    # which moves each ToolEvent after its tool span's end; review of
    # bf13d1da7: a handoff whose agent writes to the store ends with a
    # StoreEvent after its tool span
    from inspect_ai.solver import chain

    @agent
    def writer() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            """Record the answer in the store."""
            store().set("answer", 2)
            state.output = done("2")
            return state

        return execute

    @solver
    def cleans_up() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await get_model().generate("cleanup")
            return state

        return solve

    async def cleanup_chain(state: TaskState) -> None:
        async def no_generate(*args: Any, **kwargs: Any) -> TaskState:
            raise AssertionError("cleanup does not generate")

        await chain(cleans_up())(state, no_generate)

    tools: list[Tool] = {
        "handoff": [
            handoff(helper(outputs(call("addition", x=2, y=3), done("helper done"))))
        ],
        "store_handoff": [handoff(writer())],
    }.get(shape, [addition()])
    first = {
        "call": call("addition", x=1, y=1),
        "parallel": calls(
            ("addition", {"x": 1, "y": 1}), ("addition", {"x": 2, "y": 2})
        ),
        "handoff": call("transfer_to_helper"),
        "store_handoff": call("transfer_to_writer"),
    }[shape]
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=tool_loop(*tools),
        cleanup=cleanup_chain if cleanup else None,
    )
    log = eval(task, model=outputs(first, done(), done("cleaned")))[0]
    assert log.status == "success", log.error
    log = read_eval_log(str(log.location), resolve_attachments="full")
    tool_calls = len(first.message.tool_calls or []) + (shape == "handoff")

    def stages(
        log: EvalLog, versioned: bool = True
    ) -> list[tuple[str, str, tuple[str, int], Any]]:
        return [
            (s.stage, s.id, s.segment, comparable(s.step))
            for s in replay_sample(log, origins, inputs, versioned)
        ]

    before = stages(log)
    assert [stage for stage, *_ in before].count("tool_result") == tool_calls
    after = rescored(log, action)
    if shape == "store_handoff":
        assert (after.samples or [])[0].store == {"answer": 2}
    assert stages(after) == before
    assert stages(after, versioned=False) == stages(log, versioned=False)


@pytest.mark.parametrize("action", [None, "append", "overwrite"])
@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("versioned", [True, False])
def test_an_archived_0_3_100_log_replays(
    inputs: str, versioned: bool, action: Literal["append", "overwrite"] | None
) -> None:
    # Inspect 0.3.100's solvers and scorers spans keep the scorer's model call
    # out of the agent's turns in a log without origins
    path = Path(__file__).parent / "fixtures" / "scored_0.3.100.json"
    log = read_eval_log(str(path), resolve_attachments="full")
    assert log.eval.packages["inspect_ai"] == "0.3.100"
    replay = replay_sample(rescored(log, action), True, inputs, versioned)
    assert [s.stage for s in replay] == [
        "model_input",
        "model_output",
        "tool_call",
        "tool_result",
        "model_input",
        "model_output",
    ]


@pytest.mark.parametrize("grouping", ["target", "rollback"])
@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_a_stored_timeline_groups_uuid_less_events(inputs: str, grouping: str) -> None:
    # Ransom's 39th review B2: condensing expanded inputs replaces the model
    # events a stored timeline holds, which are keyed by identity without a uuid
    from inspect_ai._sentinel import _replay

    path = Path(__file__).parent / "fixtures" / "scored_0.3.100.json"
    [sample] = read_eval_log(str(path), resolve_attachments="full").samples or []
    events = list(sample.events)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    first, second = [
        TimelineEvent(event=e)
        for e in events
        if isinstance(e, ModelEvent) and e.span_id is not None and e.uuid is None
    ][:2]
    root = TimelineSpan(id="target", name="target", content=[first])
    if grouping == "target":
        root.content.append(second)
    else:
        root.branches.append(
            TimelineSpan(id="rollback", name="rollback", content=[second])
        )
    replay = steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "sample",
        eval_info=EvalInfo("0.3.100", False),
        timeline=Timeline(name="target", description="", root=root),
    )

    assert [s.step.conversation for s in replay if s.stage == "model_input"] == [
        "target",
        "target" if grouping == "target" else "rollback",
    ]


def earlier_layout(layout: str, wrapped: bool) -> tuple[list[ChatMessage], list[Event]]:
    """A model call in a solver span, a scorer span, or between a scorer's steps; `wrapped` puts the span in the `solvers` or `scorers` span, as Inspect 0.3.100 does."""
    user = ChatMessageUser(content="Solve it.")
    if layout == "scorer_step":
        call = linked_call("m1", None, [user], "Solved.", None)
        return [user, call.output.message], [
            StepEvent(action="begin", type="scorer", name="match"),
            call,
            StepEvent(action="end", type="scorer", name="match"),
        ]
    call = linked_call("m1", "work", [user], "Solved.", None)
    kind = "solver" if layout == "solver_span" else "scorer"
    phase = f"{kind}s"
    events: list[Event] = [
        SpanBeginEvent(
            id="work", name="work", type=kind, parent_id=phase if wrapped else None
        ),
        call,
        SpanEndEvent(id="work"),
    ]
    if wrapped:
        events = [
            SpanBeginEvent(id=phase, name=phase, type=phase),
            *events,
            SpanEndEvent(id=phase),
        ]
    return [user, call.output.message], events


@pytest.mark.parametrize("layout", ["solver_span", "scorer_span", "scorer_step"])
@pytest.mark.parametrize("version", [None, "unknown", "0.3.99", "0.3.100", "0.3.200"])
def test_a_log_in_a_layout_before_0_3_100_is_refused(
    layout: str, version: str | None
) -> None:
    # Ransom's review 21 B1 and B2: an agent or scorer outside the solvers or
    # scorers span cannot be told apart, so the log is refused; a retried
    # eval keeps such samples under a newer header
    messages, events = earlier_layout(layout, wrapped=False)
    with pytest.raises(
        ValueError,
        match="0.3.100 or later.*Replay this transcript from its messages instead",
    ):
        steps_from_events(
            messages,
            events,
            [],
            sample_uuid="sample",
            eval_info=EvalInfo(version, False),
        )


@pytest.mark.parametrize(
    "layout,stages",
    [("solver_span", ["model_input", "model_output"]), ("scorer_span", [])],
)
@pytest.mark.parametrize("version", [None, "unknown", "0.3.100"])
def test_a_log_in_the_0_3_100_layout_replays(
    layout: str, stages: list[str], version: str | None
) -> None:
    messages, events = earlier_layout(layout, wrapped=True)
    replay = steps_from_events(
        messages, events, [], sample_uuid="sample", eval_info=EvalInfo(version, False)
    )
    assert [s.stage for s in replay] == stages


def linked_call(
    uuid: str,
    span_id: str | None,
    input: list[ChatMessage],
    text: str,
    origin: str | None,
    *calls: ToolCall,
) -> ModelEvent:
    return ModelEvent(
        uuid=uuid,
        span_id=span_id,
        model="mockllm/model",
        origin=origin,
        input=input,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(
            model="mockllm/model",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=text, tool_calls=list(calls) or None
                    ),
                    stop_reason="tool_calls" if calls else "stop",
                )
            ],
        ),
    )


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("shape", ["fork", "candidate"])
def test_executed_tool_keeps_stages_when_producing_call_is_discarded(
    shape: str, inputs: str
) -> None:
    from inspect_ai._sentinel import _replay

    opening: list[ChatMessage] = [ChatMessageUser(content="Start the task")]
    first = linked_call("first", "agent", opening, "First answer", None)
    carried = [*opening, first.output.message]
    tool_call = ToolCall(id="discarded-tool", function="lookup", arguments={})
    if shape == "fork":
        discarded_input = carried
        kept = linked_call("kept", "agent", carried, "Kept answer", None)
        continued_input = [*carried, kept.output.message]
    else:
        kept = linked_call("kept", "agent", carried, "Kept answer", None)
        discarded_input = [ChatMessageUser(content="Side question")]
        continued_input = [*carried, kept.output.message]
    discarded = linked_call(
        "discarded", "agent", discarded_input, "Looking up", None, tool_call
    )
    discarded.tools = [ToolInfo(name="lookup", description="Look up an answer")]
    continued = linked_call("continued", "agent", continued_input, "Done", None)
    events: list[Event] = [
        SpanBeginEvent(id="agent", name="agent", type="agent"),
        first,
        *([kept] if shape == "candidate" else []),
        discarded,
        SpanBeginEvent(
            id="tool-discarded", name="lookup", type="tool", parent_id="agent"
        ),
        imported_tool_event(tool_call, 0, "tool-discarded"),
        SpanEndEvent(id="tool-discarded"),
        *([kept] if shape == "fork" else []),
        continued,
        SpanEndEvent(id="agent"),
    ]

    def replay(recorded: bool) -> list[ReplayStep]:
        chosen = [
            event.model_copy(update={"origin": "agent"})
            if recorded and isinstance(event, ModelEvent)
            else event
            for event in events
        ]
        pool: list[ChatMessage] = []
        if inputs == "pooled":
            chosen, pool = _replay._condensed(chosen, [])
        return steps_from_events(
            [],
            chosen,
            pool,
            sample_uuid="sample",
            eval_info=EvalInfo(inspect_ai_version="0.3.200", sentinel=False),
        )

    inferred = replay(False)
    recorded = replay(True)
    assert "discarded" not in [s.id for s in inferred if s.stage == "model_input"]
    assert (
        tool_steps(inferred)
        == tool_steps(recorded)
        == [
            ("tool_call", "discarded-tool", "lookup", {}, None),
            (
                "tool_result",
                "discarded-tool",
                "lookup",
                {},
                "result of discarded-tool in turn 0",
            ),
        ]
    )
    # Inferred conversation history omits the discarded generate. Other
    # tool-stage fields match after ignoring regenerated message ids.
    assert not [
        f.name
        for ours, theirs in zip(
            [s for s in inferred if s.stage.startswith("tool")],
            [s for s in recorded if s.stage.startswith("tool")],
        )
        for f in dataclasses.fields(ours.step)
        if f.name != "history"
        and comparable(getattr(ours.step, f.name), ids=False)
        != comparable(getattr(theirs.step, f.name), ids=False)
    ]


def side_calls(
    count: int, span_id: str | None, origin: str | None, tooled: bool
) -> list[ModelEvent]:
    """`count` calls, each but the first carrying on the one before it; `tooled`, each makes a tool call under a system prompt of its own."""
    input: list[ChatMessage] = [ChatMessageUser(content="Grade the answer.")]
    if tooled:
        input.insert(0, ChatMessageSystem(content="You are a grader."))
    calls: list[ModelEvent] = []
    for n in range(count):
        look = [ToolCall(id=f"g{n}", function="look", arguments={})] if tooled else []
        call = linked_call(f"s{n}", span_id, input, f"Graded {n}.", origin, *look)
        calls.append(call)
        input = [*input, call.output.message, ChatMessageUser(content="Go on.")]
    return calls


def region_with_side_calls(
    region: str, count: int, recorded: bool, tooled: bool
) -> tuple[list[ChatMessage], list[Event]]:
    """An agent's turns and `count` linked calls in a scorer, sentinel, or tool region. `tooled` gives the agent and helper calls different system prompts."""
    agent = "agent" if recorded else None
    opening: list[ChatMessage] = [ChatMessageUser(content="Solve it.")]
    if tooled:
        opening.insert(0, ChatMessageSystem(content="You are a solver."))
    if region == "tool":
        call = ToolCall(id="c1", function="check", arguments={})
        m1 = linked_call("m1", "agent", opening, "Checking.", agent, call)
        result = ChatMessageTool(content="ok", tool_call_id="c1", function="check")
        m2 = linked_call(
            "m2", "agent", [*opening, m1.output.message, result], "Solved.", agent
        )
        helpers = side_calls(count, "tool-c1", "tool" if recorded else None, tooled)
        events = solving(
            [
                SpanBeginEvent(id="agent", name="agent", type="agent"),
                m1,
                SpanBeginEvent(
                    id="tool-c1", name="check", type="tool", parent_id="agent"
                ),
                *helpers,
                ToolEvent(
                    id="c1",
                    function="check",
                    arguments={},
                    result="ok",
                    span_id="tool-c1",
                ),
                SpanEndEvent(id="tool-c1"),
                m2,
                SpanEndEvent(id="agent"),
            ]
        )
        return [*opening, m1.output.message, result, m2.output.message], events
    m1 = linked_call("m1", "agent", opening, "Solved.", agent)
    messages: list[ChatMessage] = [*opening, m1.output.message]
    if region == "scorer":
        graders = side_calls(count, "match", "scorer" if recorded else None, tooled)
        m1.span_id = None
        return messages, [
            *solving([m1]),
            SpanBeginEvent(id="scorers", name="scorers", type="scorers"),
            SpanBeginEvent(
                id="match", name="match", type="scorer", parent_id="scorers"
            ),
            *graders,
            SpanEndEvent(id="match"),
            SpanEndEvent(id="scorers"),
        ]
    monitors = side_calls(count, "check", "helper" if recorded else None, tooled)
    return (
        messages,
        solving(
            [
                SpanBeginEvent(id="agent", name="agent", type="agent"),
                m1,
                SpanBeginEvent(
                    id="check", name="probe", type="sentinel", parent_id="agent"
                ),
                *monitors,
                SpanEndEvent(id="check"),
                SpanEndEvent(id="agent"),
            ]
        ),
    )


@pytest.mark.parametrize("tooled", [False, True])
@pytest.mark.parametrize("count", [1, 2, 3])
@pytest.mark.parametrize("region", ["scorer", "sentinel", "tool"])
def test_linked_calls_outside_the_agent_s_turns_leave_its_turns(
    region: str, count: int, tooled: bool
) -> None:
    # Ransom's sixth review B1: calls a region shows are not the agent's (a
    # scorer's, a sentinel's, or a tool's) are left out of continuity, so
    # linked ones cannot make
    # the agent's turn utility; replay without origins gives the steps it
    # gives with them. Review 7 B1: tool-calling ones under another system
    # prompt cannot set the prompt the agent's turns are classified by
    def steps(recorded: bool) -> list[tuple[str, str]]:
        messages, events = region_with_side_calls(region, count, recorded, tooled)
        return [
            (s.stage, s.id)
            for s in steps_from_events(
                messages,
                events,
                [],
                sample_uuid="sample",
                eval_info=EvalInfo(inspect_ai_version="0.3.200", sentinel=False),
            )
        ]

    inferred = steps(recorded=False)

    assert inferred == steps(recorded=True)
    assert ("model_input", "m1") in inferred
    assert not any(id.startswith("s") for _, id in inferred)


@solver
def r7_carries_on_after_a_refusal() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        try:
            await model.generate(
                state.messages, config=GenerateConfig(fail_on_refusal=True)
            )
        except ModelRefusalError:
            pass
        state.output = await model.generate(state.messages)
        return state

    return solve


def test_a_refusal_raised_under_fail_on_refusal_has_no_after_step() -> None:
    replay = assert_replay_equals_live(
        r7_carries_on_after_a_refusal(),
        outputs(
            ModelOutput.from_content(
                "mockllm/model", "I refuse", stop_reason="content_filter"
            ),
            done(),
        ),
    )
    assert [s.stage for s in replay] == ["model_input", "model_input", "model_output"]


@solver
def r7_continues_after_a_retried_refusal() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        try:
            await model.generate(
                state.messages, config=GenerateConfig(fail_on_refusal=True)
            )
        except ModelRefusalError:
            pass
        output = await model.generate(state.messages)
        state.messages.extend([output.message, ChatMessageUser(content="And 2 + 2?")])
        state.output = await model.generate(state.messages)
        return state

    return solve


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
def test_a_refusal_raised_under_fail_on_refusal_is_a_failed_call_in_continuity(
    inputs: str,
) -> None:
    # Ransom's review 26 B1: a refused call R, its retry S on the same input,
    # then a call continuing S; without origins continuity took R's refusal
    # as an answer and made R utility, dropping its model_input step
    from inspect_ai._sentinel import _replay

    model = outputs(
        ModelOutput.from_content(
            "mockllm/model", "I refuse", stop_reason="content_filter"
        ),
        done("2"),
        done(),
    )
    seen: dict[str, Step] = {}
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=r7_continues_after_a_retried_refusal(),
        sentinel=[r7_probe(seen, copies=True)],
    )
    log = eval(task, model=model)[0]
    assert log.status == "success", log.error
    recorded = assert_logged_replay_equals_live(log, seen)
    assert [s.stage for s in recorded] == [
        "model_input",
        "model_input",
        "model_output",
        "model_input",
        "model_output",
    ]
    sample = logged_sample(log)
    refused = next(e for e in sample.events if isinstance(e, ModelEvent))
    assert refused.output.stop_reason == "content_filter"
    events: list[Event] = without_origins(sample.events)
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    inferred = steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
    )
    assert [(s.stage, s.id) for s in inferred] == [(s.stage, s.id) for s in recorded]
    assert ("model_input", refused.uuid) in [(s.stage, s.id) for s in inferred]


def test_a_superseded_human_decision_is_withdrawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve").install(monkeypatch)
    seen: dict[str, Step] = {}
    log = run_logged(
        tool_loop(addition()),
        agent_model(2),
        sentinel=[r7_probe(seen), h_ask("tool_call", ["approve", "reject"])],
    )
    events = logged_sample(log).events
    first = next(
        e
        for e in events
        if isinstance(e, SentinelEvent) and e.factory == "inspect_sentinel/human"
    )
    assert first.action == "proceed"
    # a layer above the person superseded the decision with its own action
    superseded = first.model_copy(update={"status": "superseded", "path": ""})
    at = events.index(first) + 1
    replay = replay_events(log, [*events[:at], superseded, *events[at:]])
    second = [s for s in replay if s.stage == "tool_call"][1]
    assert second.step.human_decisions == ()
    assert [
        d.stage
        for d in [s for s in replay_events(log, events) if s.stage == "tool_call"][
            1
        ].step.human_decisions
        or []
    ] == ["tool_call"]


@pytest.mark.parametrize(
    "version,truncated",
    [
        (None, None),
        ("0.3.100", False),
        ("0.3.262.dev32+g5ea5c5ce1", False),
        ("0.4", False),
        ("1!0.1", False),
        # a version that does not parse is taken as current
        ("unknown", False),
    ],
)
def test_a_log_without_a_version_cannot_tell_whether_output_was_cut(
    version: str | None, truncated: bool | None
) -> None:
    log = run_logged(tool_loop(addition()), agent_model())
    sample = logged_sample(log)
    replay = steps_from_events(
        sample.messages,
        sample.events,
        [],
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo(inspect_ai_version=version, sentinel=True),
    )
    [after] = [s.step for s in replay if isinstance(s.step, AfterToolCall)]
    assert after.truncated is truncated


def context_viewer(call: ToolCall) -> ToolCallView:
    return ToolCallView(
        context=ToolCallContent(format="text", content="adding for the user"),
        call=ToolCallContent(format="text", content=f"add {call.arguments}"),
    )


@tool(viewer=context_viewer)
def viewed_addition() -> Tool:
    async def execute(x: int, y: int) -> str:
        """Add two numbers.

        Args:
            x: First number to add.
            y: Second number to add.
        """
        return str(x + y)

    return execute


def test_an_approvers_view_replays_whole() -> None:
    replay = assert_replay_equals_live(
        tool_loop(viewed_addition()),
        outputs(call("viewed_addition", x=1, y=2), done()),
        approval=[ApprovalPolicy(d3_approver([]), "*")],
    )
    [before] = [s.step for s in replay if isinstance(s.step, BeforeToolCall)]
    # the approval recorded the whole view; a ToolEvent holds only its call
    assert before.view.context is not None
    assert before.view.context.content == "adding for the user"


class ClickOptions(BaseModel):
    button: str = "left"


def r7_click_viewer(call: ToolCall) -> ToolCallView:
    """A context that depends on the call's arguments: the page, with the element clicked marked."""
    element_id = call.arguments.get("element_id")
    page = [
        f"{'*' if n == element_id else ' '} [{n}] button 'item {n}'"
        for n in range(1, 9)
    ]
    return ToolCallView(context=ToolCallContent(format="text", content="\n".join(page)))


@tool(viewer=r7_click_viewer)
def r7_click() -> Tool:
    async def execute(element_id: int, options: ClickOptions | None = None) -> str:
        """Click an element.

        Args:
            element_id: ID of the element to click.
            options: How to click it.
        """
        return f"clicked {element_id}"

    return execute


@approver
def r7_clicks(decision: str, element_id: int) -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        if decision == "modify":
            return Approval(
                decision="modify",
                modified=replace(
                    call, arguments={**call.arguments, "element_id": element_id}
                ),
            )
        return Approval(decision="approve")

    return approve


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("origins", [True, False])
@pytest.mark.parametrize("decision", ["approve", "modify"])
@pytest.mark.parametrize("changed", [False, True])
def test_an_approvals_context_replays_only_for_the_call_it_viewed(
    inputs: str, origins: bool, decision: str, changed: bool
) -> None:
    """An approval's view is of the call it was shown; a changed call's context is not recorded."""
    from inspect_ai._sentinel import _replay

    seen: dict[str, Step] = {}
    task = Task(
        dataset=[Sample(input="Click item 1", target="")],
        solver=tool_loop(r7_click()),
        sentinel=[r7_probe(seen, copies=True)],
        approval=[
            ApprovalPolicy(
                r7_clicks("modify" if changed else decision, 7 if changed else 1),
                "*",
            )
        ],
    )
    model = outputs(call("r7_click", element_id=1, options={}), done())
    log = eval(task, model=model)[0]
    assert log.status == "success", log.error
    assert_logged_replay_equals_live(log, seen)
    sample = logged_sample(log)
    [(_, live)] = [
        (key, step)
        for key, step in live_steps(sample, seen).items()
        if key[0] == "tool_call"
    ]
    assert live.view.context is not None
    clicked = "7" if changed else "1"
    assert f"* [{clicked}] button" in live.view.context.content

    # with `changed`, an approve whose call differs from the one that ran is a
    # synthetic log (live refuses it); it shows the decision does not matter
    events: list[Event] = [
        event.model_copy(update={"decision": decision})
        if isinstance(event, ApprovalEvent)
        else event
        for event in (sample.events if origins else without_origins(sample.events))
    ]
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    adapter = TypeAdapter(list[Event])
    events = adapter.validate_json(adapter.dump_json(events))
    replay = steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
    )
    [before] = [s.step for s in replay if isinstance(s.step, BeforeToolCall)]
    # validation fills in the options' defaults before the approver sees the call
    assert before.call.arguments == {
        "element_id": int(clicked),
        "options": {"button": "left"},
    }
    if changed:
        assert before.view.context is None
    else:
        assert comparable(before.view.context) == comparable(live.view.context)


@protocol
def r7_clicks_elsewhere() -> Protocol:
    async def rewrite(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        modified = replace(
            step.call, arguments={**step.call.arguments, "element_id": 3}
        )
        return Decision(action="modify", modified=modified, explanation="elsewhere")

    return rewrite


@pytest.mark.parametrize("inputs", ["expanded", "pooled"])
@pytest.mark.parametrize("origins", [True, False])
def test_an_approvals_view_replays_when_only_a_sentinel_changes_the_call(
    inputs: str, origins: bool
) -> None:
    # Ransom's review 31 B2: the approver approves the call unchanged, then a
    # sentinel modifies it; the before-tool stage was handed the approval's view
    from inspect_ai._sentinel import _replay

    seen: dict[str, Step] = {}
    task = Task(
        dataset=[Sample(input="Click item 1", target="")],
        solver=tool_loop(r7_click()),
        sentinel=[r7_probe(seen, copies=True), r7_clicks_elsewhere()],
        approval=[ApprovalPolicy(r7_clicks("approve", 1), "*")],
    )
    model = outputs(call("r7_click", element_id=1, options={}), done())
    log = eval(task, model=model)[0]
    assert log.status == "success", log.error
    sample = logged_sample(log)
    [tool_event] = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert tool_event.arguments["element_id"] == 3
    [(_, live)] = [
        (key, step)
        for key, step in live_steps(sample, seen).items()
        if key[0] == "tool_call"
    ]
    assert live.view.context is not None
    assert "* [1] button" in live.view.context.content
    assert_logged_replay_equals_live(log, seen)

    events: list[Event] = list(
        sample.events if origins else without_origins(sample.events)
    )
    pool: list[ChatMessage] = []
    if inputs == "pooled":
        events, pool = _replay._condensed(events, [])
    adapter = TypeAdapter(list[Event])
    events = adapter.validate_json(adapter.dump_json(events))
    replay = steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
    )
    [before] = [s.step for s in replay if isinstance(s.step, BeforeToolCall)]
    assert before.call.arguments["element_id"] == 1
    assert comparable(before.view.context) == comparable(live.view.context)
    assert comparable(before.view.call) == comparable(live.view.call)


def test_a_result_is_the_message_the_tool_event_names() -> None:
    from inspect_ai._sentinel._replay import _Driver

    logged = ChatMessageTool(
        id="m1", content="as the model saw it", tool_call_id="c1", function="f"
    )
    driver = _Driver([], [], [logged], "sample", EvalInfo(None, True), None, ())
    event = ToolEvent(id="c1", function="f", arguments={}, result="", message_id="m1")
    assert driver._result(event) is logged
    unknown = event.model_copy(update={"message_id": "m2", "result": "rebuilt"})
    rebuilt = driver._result(unknown)
    assert (rebuilt.id, rebuilt.text) == ("m2", "rebuilt")


@pytest.mark.parametrize("ran, edited", [(1, True), (0, False), (0, 1)])
def test_a_result_is_the_copy_the_call_returned(ran: int, edited: int | bool) -> None:
    """Of a tool message's copies under one id, the result is the one equal to the call's, by JSON."""
    from inspect_ai._sentinel._replay import _Driver

    def text(value: int | bool) -> ContentText:
        return ContentText(text="ok", internal={"n": value})

    def copy(value: int | bool) -> ChatMessageTool:
        return ChatMessageTool(
            id="m1", content=[text(value)], tool_call_id="c1", function="f"
        )

    edit, original = copy(edited), copy(ran)
    driver = _Driver([], [], [edit, original], "sample", EvalInfo(None, True), None, ())
    event = ToolEvent(
        id="c1", function="f", arguments={}, result=[text(ran)], message_id="m1"
    )
    assert driver._result(event) is original


def nudged_inputs(turns: int) -> list[Event]:
    """An append-only conversation whose scaffold stamps its turn on each nudge: equal content, a pool row each."""
    system = ChatMessageSystem(content="Be helpful.")
    sent: list[ChatMessage] = [system]
    events: list[Event] = []
    for turn in range(turns):
        sent.append(ChatMessageUser(content="continue", metadata={"turn": turn}))
        events.append(turn_event(list(sent)))
        sent.append(ChatMessageAssistant(content=f"answer {turn}"))
    return events


def test_metadata_stamped_nudges_keep_the_fold_linear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._sentinel import _replay

    info = EvalInfo(inspect_ai_version=None, sentinel=False)
    works = []
    for turns in (100, 200):
        condensed, pool = _replay._condensed(nudged_inputs(turns), [])
        works.append(replay_work(monkeypatch, [], condensed, pool, "sample", info))
    small, large = works
    assert_linear(small, large)


@pytest.mark.parametrize("refs", [[(0, 1000)], [(-2, 0)], [(3, 1)]])
def test_input_ranges_outside_the_pool_fail_the_replay(
    refs: list[tuple[int, int]],
) -> None:
    from inspect_ai._sentinel import _replay

    log = run_logged(tool_loop(addition()), agent_model())
    sample = logged_sample(log)
    events, pool = _replay._condensed(sample.events, [])
    turn = next(e for e in events if isinstance(e, ModelEvent))
    turn.input_refs = refs
    with pytest.raises(MalformedLogError, match="outside the pool"):
        steps_from_events(
            sample.messages,
            events,
            pool,
            sample_uuid=sample.uuid or "",
            eval_info=EvalInfo.from_eval(log.eval),
        )


@tool
def cancelled_by_its_operator() -> Tool:
    async def execute() -> str:
        """Cancel this call as an operator would, while it runs."""
        [event] = [
            e
            for e in transcript().events
            if isinstance(e, ToolEvent) and e.function == "cancelled_by_its_operator"
        ]
        event._cancel()
        await anyio.sleep(10)
        return "never"

    return execute


def test_an_operator_cancel_is_a_known_difference() -> None:
    # known difference (design call 2): an operator's cancel records the same
    # timeout error as a tool's own timeout, so replay builds the after-stage
    # step a timeout has, which the cancelled call never reached live
    seen: dict[str, Step] = {}
    log = run_logged(
        tool_loop(cancelled_by_its_operator()),
        outputs(call("cancelled_by_its_operator"), done()),
        sentinel=[r7_probe(seen)],
    )
    assert log.samples
    live = set(live_steps(log.samples[0], seen))
    replay = {(s.stage, s.id) for s in replayed(log)}
    [call_id] = [id for stage, id in live if stage == "tool_call"]
    assert replay - live == {("tool_result", call_id)}
    assert live <= replay


def test_a_task_scorer_s_unrecorded_tool_calls_have_no_tool_steps() -> None:
    # with every instance abstaining no SentinelEvent records the stage, so
    # replay decides from the producer's region alone
    seen: list[Any] = []
    log = run_logged(
        generate(),
        outputs(done(), call("addition", x=1, y=1)),
        sentinel=[r7_counts_tool_calls(seen)],
        scorer=r7_scores_with_a_tool_loop(),
    )
    assert not seen
    assert not [s for s in replayed(log) if s.stage == "tool_call"]


# review pass 3: concurrent batches, misses, shared range indexes, suffixes


@tool(parallel=False)
def synchronised(
    a1_started: Any, b1_started: Any, a2_started: Any, b_done: Any
) -> Tool:
    async def execute(kind: str) -> str:
        """Return `kind` once the other agent has reached its point.

        Args:
            kind: Which call this is.
        """
        if kind == "A1":
            a1_started.set()
            await b1_started.wait()
        elif kind == "A2":
            a2_started.set()
            await b_done.wait()
        else:
            b1_started.set()
            await a2_started.wait()
        return kind

    return execute


@solver
def r7_runs_batches_concurrently(
    tools: list[Tool], a1_started: Any, b_done: Any
) -> Solver:
    """Two agents in one conversation: B's batch and its next turn run while A's batch is between its calls."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()

        async def a() -> None:
            input: list[ChatMessage] = [ChatMessageUser(content="first")]
            output = await model.generate(input, tools)
            await execute_tools([*input, output.message], tools)

        async def b() -> None:
            await a1_started.wait()
            input: list[ChatMessage] = [ChatMessageUser(content="second")]
            output = await model.generate(input, tools)
            result = await execute_tools([*input, output.message], tools)
            await model.generate([*input, output.message, *result.messages], tools)
            b_done.set()

        await tg_collect([a, b])
        return state

    return solve


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_batches_that_overlap_replay_as_they_ran(
    backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    a1_started, b1_started, a2_started, b_done = (
        anyio.Event(),
        anyio.Event(),
        anyio.Event(),
        anyio.Event(),
    )
    tools = [synchronised(a1_started, b1_started, a2_started, b_done)]
    log = run_logged(
        r7_runs_batches_concurrently(tools, a1_started, b_done),
        outputs(
            calls(
                ("synchronised", {"kind": "A1"}),
                ("synchronised", {"kind": "A2"}),
                turn=1,
            ),
            calls(("synchronised", {"kind": "B1"}), turn=2),
            done("C"),
        ),
        # two threads in one span: continuity follows the one carried on, so
        # without origins the other's turn is utility
        inferred="two threads in one conversation",
    )
    sample = logged_sample(log)
    recorded = replay_events(log, sample.events)
    inferred = replay_events(log, without_origins(sample.events))
    assert tool_steps(inferred) == tool_steps(recorded)
    assert len([s for s in inferred if s.stage == "tool_call"]) == 3
    assert len([s for s in inferred if s.stage == "tool_result"]) == 3


def inserted_block_inputs(turns: int) -> tuple[list[ModelEvent], list[ChatMessage]]:
    """A history stored as single-row ranges, then an input with a block of new messages before all of it."""
    pool: list[ChatMessage] = []
    for n in range(turns):
        pool.append(ChatMessageUser(content=f"kept {n}"))
        pool.append(ChatMessageAssistant(content=f"between {n}"))
    pool.extend(ChatMessageUser(content=f"inserted {n}") for n in range(turns))
    kept = [(2 * n, 2 * n + 1) for n in range(turns)]
    block = (2 * turns, 3 * turns)
    return [turn_event([], kept), turn_event([], [block, *kept])], pool


def test_a_block_inserted_before_fragmented_history_keeps_the_fold_linear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = EvalInfo(inspect_ai_version=None, sentinel=False)
    small, large = (
        replay_work(monkeypatch, [], *inserted_block_inputs(turns), "sample", info)
        for turns in (200, 400)
    )
    assert_linear(small, large)


def test_a_model_call_s_range_index_is_built_once_for_all_its_calls() -> None:
    proposals = calls(*[("addition", {"x": n, "y": 1}) for n in range(50)])
    log = run_logged(tool_loop(addition()), outputs(proposals, done()))
    replay = replayed(log)
    turn = next(s.step for s in replay if s.stage == "model_input")
    tool_inputs = {
        id(s.step.input)
        for s in replay
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
    }
    assert tool_inputs == {id(turn.input)}


class _CountingList(list[Any]):
    reads = 0

    def __getitem__(self, index: Any) -> Any:
        _CountingList.reads += 1
        return super().__getitem__(index)

    def __iter__(self) -> Any:
        for item in super().__iter__():
            _CountingList.reads += 1
            yield item


@pytest.mark.parametrize("length", [200, 400])
def test_reading_a_view_s_end_reads_only_the_end(length: int) -> None:
    items = _CountingList(range(length))
    view = ListView(items, length)
    _CountingList.reads = 0
    assert list(view[-3:]) == [length - 3, length - 2, length - 1]
    assert _CountingList.reads == 3


# review pass 4: reordered history


def reordered_inputs(turns: int) -> tuple[list[ModelEvent], list[ChatMessage]]:
    """A history stored as single-row ranges, then the same history with a middle message moved to the front."""
    pool: list[ChatMessage] = []
    for n in range(turns):
        pool.append(ChatMessageUser(content=f"kept {n}"))
        pool.append(ChatMessageAssistant(content=f"between {n}"))
    kept = [(2 * n, 2 * n + 1) for n in range(turns)]
    middle = turns // 2
    moved = [kept[middle], *kept[:middle], *kept[middle + 1 :]]
    return [turn_event([], kept), turn_event([], moved)], pool


def test_history_reordered_to_put_a_middle_message_first_keeps_the_fold_linear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = EvalInfo(inspect_ai_version=None, sentinel=False)
    small, large = (
        replay_work(monkeypatch, [], *reordered_inputs(turns), "sample", info)
        for turns in (200, 400)
    )
    assert_linear(small, large)


# review pass 5: contents stored under many rows, and overlapping ranges


def rebuilt_opening_with_stamped_nudges(turns: int) -> list[Event]:
    """Each input: a system prompt rebuilt for the turn, a nudge stamped with the turn, and an unchanged tail."""
    return [
        turn_event(
            [
                ChatMessageSystem(content=f"prompt {turn}"),
                ChatMessageUser(content="continue", metadata={"turn": turn}),
                ChatMessageUser(content="tail"),
            ]
        )
        for turn in range(turns)
    ]


def test_a_content_stored_under_many_rows_keeps_the_fold_linear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._sentinel import _replay

    info = EvalInfo(inspect_ai_version=None, sentinel=False)
    works = []
    for turns in (200, 400):
        condensed, pool = _replay._condensed(
            rebuilt_opening_with_stamped_nudges(turns), []
        )
        works.append(replay_work(monkeypatch, [], condensed, pool, "sample", info))
    small, large = works
    assert_linear(small, large)


def nested_suffix_inputs(n: int) -> tuple[list[ModelEvent], list[ChatMessage]]:
    """Inputs that repeat their own suffixes, as inspect_ai's writer stores them (`[(0, n), (1, n), ...]`), each after an opening rebuilt for the turn."""
    pool: list[ChatMessage] = [ChatMessageUser(content=f"body {k}") for k in range(n)]
    pool.extend(ChatMessageSystem(content=f"prompt {turn}") for turn in range(n))
    body = [(k, n) for k in range(n)]
    events = [turn_event([], [(n + turn, n + turn + 1), *body]) for turn in range(n)]
    return events, pool


@pytest.mark.parametrize("n", [20, 40])
def test_an_input_that_repeats_its_own_suffixes_costs_its_overlaps(
    n: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a known limit: an input whose stored ranges overlap is indexed per range
    # and segment it covers, n(n + 1) / 2 entries for n nested suffixes, and
    # each changed opening indexes the previous input again, so this shape
    # costs n**3 / 2 for n**2 stored ranges; inspect_ai's writer stores an
    # input this way only when the input repeats its own messages
    info = EvalInfo(inspect_ai_version=None, sentinel=False)
    events, pool = nested_suffix_inputs(n)
    work = replay_work(monkeypatch, [], events, pool, "sample", info)
    assert work.entries == (n - 1) * (n * (n + 1) // 2 + 1)


# R7 PR 1c (#6004): a sink's on_start names the span a generate runs under


def replay_under_on_start(
    monkeypatch: pytest.MonkeyPatch, solver: Solver, model: Any = None
) -> tuple[list["ReplayStep"], dict[tuple[str, str], str | None]]:
    """Compare live and replay for a run whose sink attributes calls to sub-agent spans.

    Returns:
        The replayed steps, and for each, the parent of the sentinel span replay checked it in.
    """
    from inspect_ai._sentinel import _replay

    parents: dict[tuple[str, str], str | None] = {}
    built = _replay._Driver._built

    def recording(
        self: Any, step_id: str, stage: SentinelStage, step: Any, span: str | None
    ) -> None:
        parents[(stage, step_id)] = (
            self.begins[span][1].parent_id if span is not None else None
        )
        built(self, step_id, stage, step, span)

    monkeypatch.setattr(_replay._Driver, "_built", recording)
    replay = assert_replay_equals_live(
        solver, model or "mockllm/model", sample=Sample(input="Hi.")
    )
    return replay, parents


def generate_steps(replay: Sequence["ReplayStep"]) -> dict[str, list["ReplayStep"]]:
    """Each conversation's generate steps, in order."""
    found: dict[str, list[ReplayStep]] = {}
    for step in replay:
        if step.stage in ("model_input", "model_output"):
            found.setdefault(step.step.conversation, []).append(step)
    return found


def test_an_on_start_sub_agent_call_replays_in_its_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay, parents = replay_under_on_start(
        monkeypatch, d3_attributes_a_call_to_a_sub_agent(_StartingSink("sub-agent"))
    )
    by_conversation = generate_steps(replay)
    assert set(by_conversation) == {"outer", "sub-agent"}
    sub_input, sub_output = by_conversation["sub-agent"]
    assert sub_input.id == sub_output.id
    assert not sub_input.step.history
    assert [m.text for m in sub_output.step.history or []] == ["Sub-agent turn."]
    # its steps are found in the sentinel spans live opened in the sub-agent
    assert parents[("model_input", sub_input.id)] == "sub-agent"
    assert parents[("model_output", sub_output.id)] == "sub-agent"
    assert sub_input.segment == ("sub-agent", 0)


def test_an_on_start_sub_agent_call_s_retries_replay_as_one_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay, parents = replay_under_on_start(
        monkeypatch,
        d3_attributes_a_call_to_a_sub_agent(_StartingSink("sub-agent"), retry=True),
        "d3_retrying/model",
    )
    sub_input, sub_output = generate_steps(replay)["sub-agent"]
    assert parents[("model_input", sub_input.id)] == "sub-agent"
    assert parents[("model_output", sub_output.id)] == "sub-agent"


def test_parallel_on_start_sub_agent_calls_replay_with_their_histories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def by_input(input: list[ChatMessage]) -> str:
        return "sub-agent" if input[-1].text == "Sub A." else "sub-agent-2"

    replay, parents = replay_under_on_start(
        monkeypatch,
        d3_attributes_a_call_to_a_sub_agent(
            _StartingSink(by_input), ["Sub A.", "Sub B."], parallel=True
        ),
    )
    by_conversation = generate_steps(replay)
    assert set(by_conversation) == {"outer", "sub-agent", "sub-agent-2"}
    for conversation, text in (("sub-agent", "Sub A."), ("sub-agent-2", "Sub B.")):
        sub_input, sub_output = by_conversation[conversation]
        assert [m.text for m in sub_output.step.history or []] == [text]
        assert parents[("model_input", sub_input.id)] == conversation


def test_a_person_s_approval_of_a_bridged_host_call_reaches_later_turns() -> None:
    log = run_logged(
        as_solver(r7_bridged_scaffold("report")),
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="host",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
            done(),
        ),
        approval=[ApprovalPolicy(r7_decides("approve"), "*")],
    )
    sample = logged_sample(log)
    [approver_name] = {
        e.approver for e in sample.events if isinstance(e, ApprovalEvent)
    }
    replay = steps_from_events(
        sample.messages,
        sample.events,
        [],
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
        human_approvers=(approver_name,),
    )
    # the host call's tool steps are rebuilt from the conversation, and the
    # steps after the person's approval see it
    assert [s.stage for s in replay] == [
        "model_input",
        "model_output",
        "tool_call",
        "tool_result",
        "model_input",
        "model_output",
    ]
    assert not replay[2].step.human_decisions
    for step in replay[3:]:
        [decision] = step.step.human_decisions or []
        assert (decision.step_id, decision.decided.report.action) == (
            "host",
            "proceed",
        )


async def r7_host_bridge(state: AgentState) -> tuple[Any, list[Any]]:
    """A sandbox bridge serving `addition` on the host, and the scaffold's declaration of it."""
    from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge

    bridge = SandboxAgentBridge(
        state=state,
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=8080,
        model=None,
        bridged_tools={"host": {"addition": addition()}},
    )
    [served] = bridge.served_tools.values()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "mcp__host__addition",
                "description": served.description,
                "parameters": served.parameters.model_dump(exclude_none=True),
            },
        }
    ]
    return bridge, tools


@agent
def r7_defers_a_bridged_host_call(
    native_first: bool, native: str = "addition"
) -> Agent:
    """A bridged call proposed, then a native call (`addition`, or `explodes`, which raises) generated under its id, before either runs."""

    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )
        from inspect_ai.agent._bridge.sandbox.service import call_tool

        bridge, tools = await r7_host_bridge(state)
        messages = [{"role": "user", "content": "What is 1 + 1?"}]
        completion = await inspect_completions_api_request(
            {"model": "inspect", "messages": messages, "tools": tools}, None, bridge
        )
        [proposed] = completion.choices[0].message.tool_calls or []
        assert proposed.type == "function"
        native_tools = (
            [addition(), explodes()]
            if native == "both"
            else [explodes() if native == "explodes" else addition()]
        )
        history: list[ChatMessage] = [ChatMessageUser(content="What is 5 + 5?")]
        output = await get_model().generate(history, tools=native_tools)
        history.append(output.message)

        async def host() -> None:
            # the bridge checks the result when the next request carries it
            result = await call_tool(bridge)(
                "host", "addition", json.loads(proposed.function.arguments)
            )
            await inspect_completions_api_request(
                {
                    "model": "inspect",
                    "messages": [
                        *messages,
                        completion.choices[0].message.model_dump(exclude_none=True),
                        {
                            "role": "tool",
                            "tool_call_id": proposed.id,
                            "content": str(result),
                        },
                    ],
                    "tools": tools,
                },
                None,
                bridge,
            )

        async def native_call() -> None:
            try:
                await execute_tools(history, native_tools)
            except RuntimeError:
                assert native in ("explodes", "both")

        for step in (native_call, host) if native_first else (host, native_call):
            await step()
        return state

    return execute


@pytest.mark.parametrize("native_first", [False, True])
def test_a_native_call_run_while_a_bridged_call_waits_keeps_its_tool_steps(
    native_first: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r7_defers_a_bridged_host_call(native_first)),
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
            r7_tool_calls(
                ToolCall(id="shared", function="addition", arguments={"x": 5, "y": 5})
            ),
            done(),
        ),
        sentinel=[r7_probe(seen, copies=True)],
        # the bridge's request reporting the result follows the native turn
        inferred="two threads in one conversation",
    )
    live = [
        ((e.stage, e.step_id), seen[e.explanation or ""])
        for e in logged_sample(log).events
        if isinstance(e, SentinelEvent) and e.path == "r7_probe"
    ]
    # the bridge checked the call before the native call was generated, and
    # its result, once reported, around the native call's checks
    bridged = [
        n
        for n, (_, step) in enumerate(live)
        if isinstance(step, BeforeToolCall | AfterToolCall)
        and step.call.arguments == {"x": 1, "y": 1}
    ]
    native = [
        n
        for n, (_, step) in enumerate(live)
        if isinstance(step, BeforeToolCall | AfterToolCall)
        and step.call.arguments == {"x": 5, "y": 5}
    ]
    [_, turn, _] = [n for n, (key, _) in enumerate(live) if key[0] == "model_input"]
    assert bridged[0] < turn < native[0]
    assert (bridged[1] > native[1]) is native_first
    replay = assert_replay_rebuilds_bridge_steps(
        log,
        seen,
        lambda step: step.call.arguments == {"x": 5, "y": 5},
        HOST_DIFFERENCES,
    )
    assert len(tool_step_calls(replay)) == 4
    assert len(bridged_steps(log, replay)) == 2
    assert bridged_call_ids(log, replay) == ["shared"]
    assert replay_warnings(caplog) == []


@agent
def r9_native_before_a_filtered_bridge_call() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )

        native_tool = addition()
        history: list[ChatMessage] = [ChatMessageUser(content="native")]
        output = await get_model().generate(history, tools=[native_tool])
        history.append(output.message)

        bridge, tools = await r7_host_bridge(state)

        async def replace_response(
            model: Any, output: ModelOutput, generate_input: Any
        ) -> ModelOutput | None:
            if not output.message.tool_calls:
                return None
            return r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            )

        bridge.response_filter = replace_response
        await inspect_completions_api_request(
            {
                "model": "inspect",
                "messages": [{"role": "user", "content": "bridge"}],
                "tools": tools,
            },
            None,
            bridge,
        )
        await inspect_completions_api_request(
            {
                "model": "inspect",
                "messages": [{"role": "user", "content": "INTERLEAVED"}],
            },
            None,
            bridge,
        )
        await execute_tools(history, [native_tool])
        return state

    return execute


def test_a_native_call_under_a_filtered_bridge_proposal_s_id_keeps_its_tool_steps(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r9_native_before_a_filtered_bridge_call()),
        outputs(
            r7_tool_calls(
                ToolCall(id="shared", function="addition", arguments={"x": 5, "y": 5})
            ),
            r7_tool_calls(
                ToolCall(
                    id="raw", function="mcp__host__addition", arguments={"x": 1, "y": 1}
                )
            ),
            done("INTERLEAVED"),
        ),
        sentinel=[r7_probe(seen, copies=True)],
    )
    events = logged_sample(log).events
    live = [
        seen[event.explanation or ""]
        for event in events
        if isinstance(event, SentinelEvent)
        and event.path == "r7_probe"
        and event.stage == "tool_call"
    ]
    native = next(step for step in live if step.call.arguments == {"x": 5, "y": 5})
    native_report = next(
        i
        for i, event in enumerate(events)
        if isinstance(event, SentinelEvent)
        and event.path == "r7_probe"
        and event.stage == "tool_call"
        and seen[event.explanation or ""].call.arguments == {"x": 5, "y": 5}
    )
    interleaved_event = next(
        i
        for i, event in enumerate(events)
        if isinstance(event, ModelEvent) and event.output.message.text == "INTERLEAVED"
    )
    assert native_report > interleaved_event
    assert any(message.text == "INTERLEAVED" for message in native.history)

    # replay shows the call the model wrote ("raw"), not the response filter's
    # replacement the bridge checked ("shared")
    steps = assert_replay_rebuilds_bridge_steps(
        log,
        seen,
        lambda step: step.call.arguments == {"x": 5, "y": 5},
        unbuilt=1,
        extra=1,
    )
    assert [
        (s.stage, s.id.split("/")[-1], called(s).arguments)
        for s in steps
        if s.stage.startswith("tool")
    ] == [
        ("tool_call", "raw", {"x": 1, "y": 1}),
        ("tool_call", "shared", {"x": 5, "y": 5}),
        ("tool_result", "shared", {"x": 5, "y": 5}),
    ]
    assert bridged_call_ids(log, steps) == ["raw"]
    assert replay_warnings(caplog) == []


@agent(name="r10_handoff", description="Handle the requested task.")
def r10_handoff() -> Agent:
    async def execute(state: AgentState, task: str) -> AgentState:
        """Handle a task.

        Args:
            state: Agent state.
            task: Task to handle.
        """
        state.messages.append(ChatMessageAssistant(content=task))
        return state

    return execute


@protocol
def r10_modify_handoff() -> Protocol:
    async def modify(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.call.function == "transfer_to_r10_handoff":
            return Decision(
                action="modify",
                modified=replace(step.call, arguments={"task": "modified"}),
            )
        return None

    return modify


@agent
def r10_bridged_proposal_before_native_handoff() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )

        bridge, tools = await r7_host_bridge(state)
        await inspect_completions_api_request(
            {
                "model": "inspect",
                "messages": [{"role": "user", "content": "bridge"}],
                "tools": tools,
            },
            None,
            bridge,
        )
        handoff_tool = handoff(r10_handoff())
        history: list[ChatMessage] = [ChatMessageUser(content="native")]
        output = await get_model().generate(history, tools=[handoff_tool])
        history.append(output.message)
        await execute_tools(history, [handoff_tool])
        return state

    return execute


@pytest.mark.parametrize("case", ["modify", "human"])
def test_a_native_handoff_under_a_bridged_call_s_id_keeps_its_tool_steps(
    case: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    seen: dict[str, Step] = {}
    sentinel: list[Any] = [r7_probe(seen, copies=True)]
    if case == "modify":
        sentinel.append(r10_modify_handoff())
    else:
        Panel("approve", "handoff approved").install(monkeypatch)
        sentinel.append(h_ask("tool_call", ["approve", "reject"]))
    log = run_logged(
        as_solver(r10_bridged_proposal_before_native_handoff()),
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
            r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="transfer_to_r10_handoff",
                    arguments={"task": "original"},
                )
            ),
        ),
        sentinel=sentinel,
    )
    events = logged_sample(log).events
    live = [
        seen[event.explanation or ""]
        for event in events
        if isinstance(event, SentinelEvent)
        and event.path == "r7_probe"
        and event.stage == "tool_call"
    ]
    native = next(
        step for step in live if step.call.function == "transfer_to_r10_handoff"
    )
    replay = assert_replay_rebuilds_bridge_steps(
        log,
        seen,
        lambda step: step.call.function == "transfer_to_r10_handoff",
        HOST_DIFFERENCES,
    )
    rebuilt = [
        step
        for step in replay
        if step.stage in ("tool_call", "tool_result")
        and step not in bridged_steps(log, replay)
    ]
    assert native.call.arguments == {"task": "original"}
    if case == "modify":
        assert any(
            isinstance(event, SentinelEvent)
            and event.action == "modify"
            and event.modified is not None
            and event.modified.arguments == {"task": "modified"}
            for event in events
        )
    else:
        assert any(
            isinstance(event, SentinelEvent)
            and event.factory == "inspect_sentinel/human"
            and event.explanation == "handoff approved"
            for event in events
        )
    assert rebuilt[0].stage == "tool_call"
    assert dict(rebuilt[0].recorded_answers) == (
        {}
        if case == "modify"
        else {"human": HumanAnswer(decision="approve", reason="handoff approved")}
    )
    assert bridged_call_ids(log, replay) == ["shared"]
    assert replay_warnings(caplog) == []


@agent
def r11_helper_handoff_after_bridge(native_origin: str) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )

        bridge, tools = await r7_host_bridge(state)
        request = {
            "model": "inspect",
            "messages": [{"role": "user", "content": "bridge"}],
            "tools": tools,
        }
        await inspect_completions_api_request(request, None, bridge)
        handoff_tool = handoff(r10_handoff())
        history: list[ChatMessage] = [ChatMessageUser(content="native helper")]
        if native_origin == "agent":
            output = await get_model().generate(history, tools=[handoff_tool])
        else:
            with model_origin("helper"):
                output = await get_model().generate(history, tools=[handoff_tool])
        history.append(output.message)

        async def replace_response(
            model: Any, output: ModelOutput, generate_input: Any
        ) -> ModelOutput:
            return r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="mcp__host__addition",
                    arguments={"x": 2, "y": 2},
                )
            )

        bridge.response_filter = replace_response
        await inspect_completions_api_request(request, None, bridge)
        with model_origin("helper"):
            await execute_tools(history, [handoff_tool])
        return state

    return execute


@pytest.mark.parametrize("native_origin", ["agent", "helper"])
@pytest.mark.parametrize("human", [False, True])
def test_a_helper_handoff_never_takes_a_bridge_check(
    human: bool,
    native_origin: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, Step] = {}
    sentinel: list[Any] = [r7_probe(seen, copies=True)]
    if human:
        Panel("approve", "bridge approved").install(monkeypatch)
        sentinel.append(h_ask("tool_call", ["approve", "reject"]))
    log = run_logged(
        as_solver(r11_helper_handoff_after_bridge(native_origin)),
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
            r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="transfer_to_r10_handoff",
                    arguments={"task": "helper original"},
                )
            ),
            r7_tool_calls(
                ToolCall(
                    id="raw",
                    function="mcp__host__addition",
                    arguments={"x": 2, "y": 2},
                )
            ),
        ),
        sentinel=sentinel,
        # a model_origin() region is not in the span tree, so without origins
        # the helper's call is a turn
        inferred="a model_origin() region" if native_origin == "helper" else None,
    )
    live = [step for step in seen.values() if isinstance(step, BeforeToolCall)]
    assert not any(step.call.function == "transfer_to_r10_handoff" for step in live)
    all_replay = replayed(log)
    replay = [step for step in all_replay if step.stage == "tool_call"]
    native = [
        step
        for step in replay
        if isinstance(step.step, BeforeToolCall)
        and step.step.call.function == "transfer_to_r10_handoff"
    ]
    if human:
        assert any(
            decision.step_id == "shared"
            for step in all_replay
            for decision in step.step.human_decisions or []
        )
    # live checks a call by the region that runs it, replay by its producer's
    # (a known difference), so a handoff a turn proposed has a step with no
    # check of its own
    assert len(native) == (1 if native_origin == "agent" else 0)
    assert not any(step.recorded_answers for step in native)
    # the filter's other call under the id is handed over under a fresh one
    bridged = bridged_call_ids(log, all_replay)
    assert bridged[0] == "shared" and len(bridged) == 2
    assert replay_warnings(caplog) == []


@agent
def r11_prefilled_after_filtered_bridge(native_id: str) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )

        bridge, tools = await r7_host_bridge(state)

        async def replace_response(
            model: Any, output: ModelOutput, generate_input: Any
        ) -> ModelOutput:
            return r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            )

        bridge.response_filter = replace_response
        await inspect_completions_api_request(
            {
                "model": "inspect",
                "messages": [{"role": "user", "content": "bridge"}],
                "tools": tools,
            },
            None,
            bridge,
        )
        state.messages.append(
            ChatMessageAssistant(
                content="prefilled",
                tool_calls=[
                    ToolCall(
                        id=native_id, function="addition", arguments={"x": 5, "y": 5}
                    )
                ],
            )
        )
        await execute_tools(state.messages, [addition()])
        return state

    return execute


@pytest.mark.parametrize("human", [False, True])
@pytest.mark.parametrize("native_id", ["shared", "native"])
def test_a_prefilled_native_call_beside_a_bridge_keeps_its_tool_steps(
    human: bool,
    native_id: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, Step] = {}
    sentinel: list[Any] = [r7_probe(seen, copies=True)]
    if human:
        Panel("approve", "approved").install(monkeypatch)
        sentinel.append(h_ask("tool_call", ["approve", "reject"]))
    log = run_logged(
        as_solver(r11_prefilled_after_filtered_bridge(native_id)),
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="raw",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            )
        ),
        sentinel=sentinel,
    )
    live = [
        step
        for step in seen.values()
        if isinstance(step, BeforeToolCall)
        and step.call.function == "addition"
        and step.call.arguments == {"x": 5, "y": 5}
    ]
    assert len(live) == 1 and live[0].input is None
    replay = replayed(log)
    native_steps = [
        step
        for step in replay
        if step.stage in ("tool_call", "tool_result")
        and step not in bridged_steps(log, replay)
    ]
    # under the bridge's id or its own
    assert [step.stage for step in native_steps] == ["tool_call", "tool_result"]
    assert isinstance(native_steps[0].step, BeforeToolCall)
    assert native_steps[0].step.call.arguments == live[0].call.arguments
    if human:
        assert dict(native_steps[0].recorded_answers) == {
            "human": HumanAnswer(decision="approve", reason="approved")
        }
    # the bridge's call is the one the model wrote, not the filter's
    assert [s.id.split("/")[-1] for s in bridged_steps(log, replay)] == ["raw"]
    assert replay_warnings(caplog) == []


def test_a_native_result_check_inside_its_invocation_is_replayed() -> None:
    log = run_logged(
        as_solver(r7_defers_a_bridged_host_call(native_first=True, native="both")),
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
            r7_tool_calls(
                ToolCall(
                    id="native_ok", function="addition", arguments={"x": 5, "y": 5}
                ),
                ToolCall(id="shared", function="explodes", arguments={}),
            ),
        ),
        sentinel=[r7_probe({}), r7_bridge_result_outcome("terminate")],
    )
    native_results = [
        step.step for step in replayed(log) if isinstance(step.step, AfterToolCall)
    ]
    assert len(native_results) == 1
    assert native_results[0].call.id == "native_ok"
    assert native_results[0].result.text == "10"


@reviewer
def r7_reviewer_logs_a_model_call() -> Reviewer:
    async def review_result(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        await get_model("mockllm/reviewer").generate("Review this result")
        return Review(decision="continue")

    return review_result


def test_a_native_result_check_follows_an_interleaved_reviewer_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._sentinel import _replay

    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r7_defers_a_bridged_host_call(native_first=True, native="both")),
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="host",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
            r7_tool_calls(
                ToolCall(
                    id="native_ok", function="addition", arguments={"x": 5, "y": 5}
                ),
                ToolCall(id="other", function="explodes", arguments={}),
            ),
        ),
        sentinel=[r7_probe(seen, copies=True), r7_bridge_result_outcome("terminate")],
        review=[ReviewPolicy(r7_reviewer_logs_a_model_call(), "addition")],
        # a reviewer's model call is not in a tool span, so without origins it
        # is a turn, as an approver's is
        inferred="a reviewer's model call",
    )
    sample = logged_sample(log)
    [recorded_span] = [
        event.span_id
        for event in sample.events
        if isinstance(event, SentinelEvent)
        and event.stage == "tool_result"
        and event.step_id == "native_ok"
        and event.path == "r7_probe"
    ]
    assert recorded_span is not None
    reviewer_event = next(
        index
        for index, event in enumerate(sample.events)
        if isinstance(event, ModelEvent) and event.model == "mockllm/reviewer"
    )
    result_begin = next(
        index
        for index, event in enumerate(sample.events)
        if isinstance(event, SpanBeginEvent) and event.id == recorded_span
    )
    tool_event = next(
        index
        for index, event in enumerate(sample.events)
        if isinstance(event, ToolEvent) and event.id == "native_ok"
    )
    tool_begin = sample.events[tool_event - 1]
    assert isinstance(tool_begin, SpanBeginEvent) and tool_begin.type == "tool"
    tool_span = tool_begin.id
    tool_end = next(
        index
        for index, event in enumerate(sample.events)
        if isinstance(event, SpanEndEvent) and event.id == tool_span
    )
    assert tool_end < reviewer_event < result_begin
    selected: list[tuple[str, str | None]] = []
    built = _replay._Driver._built

    def record(
        self: Any, step_id: str, stage: SentinelStage, step: Step, span: str | None
    ) -> None:
        if stage == "tool_result":
            selected.append((step_id, span))
        built(self, step_id, stage, step, span)

    monkeypatch.setattr(_replay._Driver, "_built", record)
    replayed(log)
    assert selected == [("native_ok", recorded_span)]


@protocol
def r7_bridge_result_outcome(outcome: str) -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.call.arguments == {"x": 1, "y": 1} or step.call.function == "echo":
            if outcome == "terminate":
                return Decision.terminate("stop host result")
        return None

    return after


@monitor
def r7_bridge_result_failure() -> MonitorGroup:
    async def after(context: Context, step: AfterToolCall) -> Observation | None:
        if step.call.arguments == {"x": 1, "y": 1} or step.call.function == "echo":
            raise RuntimeError("host result failed")
        return None

    return MonitorGroup(after)


@pytest.mark.parametrize("bridge_outcome", ["normal", "terminate", "fail"])
def test_a_native_call_under_a_host_call_s_id_keeps_its_tool_steps(
    bridge_outcome: str, caplog: pytest.LogCaptureFixture
) -> None:
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r7_defers_a_bridged_host_call(native_first=True)),
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="shared",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
            r7_tool_calls(
                ToolCall(id="shared", function="addition", arguments={"x": 5, "y": 5})
            ),
            done(),
        ),
        sentinel=[
            r7_probe(seen, copies=True),
            r7_bridge_result_outcome(bridge_outcome),
            *([r7_bridge_result_failure()] if bridge_outcome == "fail" else []),
        ],
        # the bridge's request reporting the result follows the native turn
        inferred="two threads in one conversation"
        if bridge_outcome != "terminate"
        else None,
    )
    events = logged_sample(log).events
    live = [
        (e.stage, seen[e.explanation or ""].call.arguments)
        for e in events
        if isinstance(e, SentinelEvent)
        and e.path == "r7_probe"
        and e.stage.startswith("tool")
    ]
    assert live == [
        ("tool_call", {"x": 1, "y": 1}),
        ("tool_call", {"x": 5, "y": 5}),
        ("tool_result", {"x": 5, "y": 5}),
        ("tool_result", {"x": 1, "y": 1}),
    ]
    # a sentinel that ended the sample at the host call's result kept the
    # result from the model, so the call has no result step
    ended = bridge_outcome == "terminate"
    replay = assert_replay_rebuilds_bridge_steps(
        log,
        seen,
        lambda step: step.call.arguments == {"x": 5, "y": 5},
        HOST_DIFFERENCES,
        unbuilt=1 if ended else 0,
    )
    assert [(stage, args) for stage, _, args in tool_step_calls(replay)] == [
        ("tool_call", {"x": 1, "y": 1}),
        ("tool_call", {"x": 5, "y": 5}),
        ("tool_result", {"x": 5, "y": 5}),
        *([] if ended else [("tool_result", {"x": 1, "y": 1})]),
    ]
    assert bridged_call_ids(log, replay) == ["shared"]
    assert replay_warnings(caplog) == []


@agent
def r7_scaffold_reports_after_a_failed_native_call(outcome: str) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import inspect_completions_api_request

        bridge, tools = await r7_host_bridge(state)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo text",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                },
            }
        )
        messages: list[Any] = [{"role": "user", "content": "echo"}]
        completion = await inspect_completions_api_request(
            {"model": "inspect", "messages": messages, "tools": tools}, None, bridge
        )
        [proposed] = completion.choices[0].message.tool_calls or []
        messages.append(completion.choices[0].message.model_dump(exclude_none=True))
        history: list[ChatMessage] = [ChatMessageUser(content="native")]
        native_tool = explodes()
        output = await get_model().generate(history, tools=[native_tool])
        history.append(output.message)
        with pytest.raises(RuntimeError, match="boom"):
            await execute_tools(history, [native_tool])
        messages.append(
            {"role": "tool", "tool_call_id": proposed.id, "content": "scaffold result"}
        )
        if outcome == "terminate":
            with pytest.raises(TerminateSampleError, match="stop host result"):
                await inspect_completions_api_request(
                    {"model": "inspect", "messages": messages, "tools": tools},
                    None,
                    bridge,
                )
        else:
            await inspect_completions_api_request(
                {"model": "inspect", "messages": messages, "tools": tools}, None, bridge
            )
        return state

    return execute


def test_a_scaffold_result_never_becomes_a_failed_native_call_s_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    for outcome in ("normal", "terminate"):
        seen: dict[str, Step] = {}
        log = run_logged(
            as_solver(r7_scaffold_reports_after_a_failed_native_call(outcome)),
            outputs(
                r7_tool_calls(
                    ToolCall(id="shared", function="echo", arguments={"text": "x"})
                ),
                r7_tool_calls(ToolCall(id="shared", function="explodes", arguments={})),
                done(),
            ),
            sentinel=[r7_probe(seen, copies=True), r7_bridge_result_outcome(outcome)],
            # the bridge's thread and the native one share a span: where the
            # bridge's carries on after the native turn, continuity follows it,
            # so without origins the native turn is utility
            inferred=(
                "two threads in one conversation" if outcome == "normal" else None
            ),
        )
        live = [
            (event.stage, seen[event.explanation or ""].call.function)
            for event in logged_sample(log).events
            if isinstance(event, SentinelEvent)
            and event.path == "r7_probe"
            and event.stage.startswith("tool")
        ]
        assert live == [
            ("tool_call", "echo"),
            ("tool_call", "explodes"),
            ("tool_result", "echo"),
        ]
        caplog.clear()
        ended = outcome == "terminate"
        replay = assert_replay_rebuilds_bridge_steps(
            log,
            seen,
            lambda step: step.call.function == "explodes",
            unbuilt=1 if ended else 0,
        )
        # the failed native call has no result step; the scaffold's result is
        # its own call's, where it reached the model
        assert [
            (stage, function) for stage, function, _ in tool_step_calls(replay)
        ] == [
            ("tool_call", "echo"),
            ("tool_call", "explodes"),
            *([] if ended else [("tool_result", "echo")]),
        ]
        assert bridged_call_ids(log, replay) == ["shared"]
        assert replay_warnings(caplog) == []


def test_a_result_only_sentinel_s_bridge_check_never_becomes_a_native_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = run_logged(
        as_solver(r7_scaffold_reports_after_a_failed_native_call("terminate")),
        outputs(
            r7_tool_calls(
                ToolCall(id="shared", function="echo", arguments={"text": "x"})
            ),
            r7_tool_calls(ToolCall(id="shared", function="explodes", arguments={})),
            done(),
        ),
        sentinel=[r7_bridge_result_outcome("terminate")],
    )
    stages = [
        event.stage
        for event in logged_sample(log).events
        if isinstance(event, SentinelEvent) and event.stage.startswith("tool")
    ]
    assert stages == ["tool_result"]
    # the failed native call has no result step, and the scaffold's call none
    # either, as the sentinel ended the sample before its result reached the
    # model
    replay = replayed(log)
    assert [(stage, function) for stage, function, _ in tool_step_calls(replay)] == [
        ("tool_call", "echo"),
        ("tool_call", "explodes"),
    ]
    assert bridged_call_ids(log, replay) == ["shared"]
    assert replay_warnings(caplog) == []


@reviewer
def r7_holds_result_review(
    reviewing: anyio.Event,
    released: anyio.Event,
    decision: Literal["continue", "terminate", "raise"] = "continue",
) -> Reviewer:
    async def review_result(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        reviewing.set()
        await released.wait()
        if decision == "raise":
            raise RuntimeError("review service unavailable")
        return Review(decision=decision)

    return review_result


@monitor
def r7_holds_native_result(gate: dict[str, anyio.Event]) -> MonitorGroup:
    """Hold the check of the native result `2` until the gate is released, then abstain."""

    async def after_call(context: Context, step: AfterToolCall) -> Observation | None:
        if step.result.text == "2":
            gate["reviewing"].set()
            await gate["released"].wait()
        return None

    return MonitorGroup(after_call)


OrphanHold = Literal[
    "review",
    "terminating review",
    "failing review",
    "check",
    "check after a yielding allocator",
]


@agent
def r7_reports_orphan_result_after_native_call(
    held: OrphanHold | None, gate: dict[str, anyio.Event] | None = None
) -> Agent:
    """A bridge reporting an orphan result under a native call's id: after the native call failed, or while its successful result is held in a review (that continues, terminates or raises) or in its sentinel check (`r7_holds_native_result` with `gate`), which can begin after a span-id allocator awaited a sibling's span."""

    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import inspect_completions_api_request

        bridge, tools = await r7_host_bridge(state)
        history: list[ChatMessage] = [ChatMessageUser(content="native")]
        native_tool = addition() if held is not None else explodes()
        output = await get_model().generate(history, tools=[native_tool])
        history.append(output.message)

        async def report_orphan() -> None:
            messages: list[dict[str, Any]] = [
                {"role": "user", "content": "orphan"},
                {
                    "role": "tool",
                    "tool_call_id": "shared",
                    "name": "echo",
                    "content": "orphan result",
                },
            ]
            with pytest.raises(TerminateSampleError, match="stop orphan"):
                await inspect_completions_api_request(
                    {"model": "inspect", "messages": messages, "tools": tools},
                    None,
                    bridge,
                )

        async def held_native_call() -> None:
            assert held is not None
            reviewing, released = anyio.Event(), anyio.Event()
            if gate is not None:
                gate.update(reviewing=reviewing, released=released)
            review = (
                []
                if held.startswith("check")
                else [
                    ReviewPolicy(
                        r7_holds_result_review(
                            reviewing,
                            released,
                            "terminate"
                            if held == "terminating review"
                            else "raise"
                            if held == "failing review"
                            else "continue",
                        ),
                        "addition",
                    )
                ]
            )

            async def native() -> None:
                try:
                    await execute_tools(history, [native_tool], review=review)
                except TerminateSampleError:
                    raise
                except RuntimeError:
                    # the scaffold carries on after its reviewer failed
                    assert held == "failing review"

            async def orphan() -> None:
                await reviewing.wait()
                try:
                    await report_orphan()
                finally:
                    released.set()

            async with anyio.create_task_group() as tg:
                tg.start_soon(native)
                tg.start_soon(orphan)

        if held == "check after a yielding allocator":
            # the native result check's span id waits while a sibling records a
            # span, so that span, not the check, follows the native tool span
            requested, allocated = anyio.Event(), anyio.Event()

            async def allocate(
                name: str, parent_id: str | None, requested_id: str | None
            ) -> str:
                if name == "sentinel" and not requested.is_set():
                    requested.set()
                    await allocated.wait()
                return requested_id or uuid()

            async def sibling() -> None:
                await requested.wait()
                async with span("orchestrator", type="rpc"):
                    pass
                allocated.set()

            with span_id_provider(allocate):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(sibling)
                    await held_native_call()
        elif held is not None:
            await held_native_call()
        else:
            with pytest.raises(RuntimeError, match="boom"):
                await execute_tools(history, [native_tool])
            await report_orphan()
        state.output = await get_model().generate(state.messages)
        return state

    return execute


@protocol
def r7_terminate_orphan_result() -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.result.text == "orphan result":
            return Decision.terminate("stop orphan")
        return None

    return after


@pytest.mark.parametrize("held", [None, "review"])
def test_an_orphan_bridge_result_under_a_native_call_s_id_is_not_its_result(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    held: OrphanHold | None,
) -> None:
    Panel("approve", "allowed").install(monkeypatch)
    seen: dict[str, Step] = {}
    native_call = (
        ToolCall(id="shared", function="addition", arguments={"x": 1, "y": 1})
        if held
        else ToolCall(id="shared", function="explodes", arguments={})
    )
    log = run_logged(
        as_solver(r7_reports_orphan_result_after_native_call(held)),
        outputs(r7_tool_calls(native_call), done()),
        sentinel=[
            r7_probe(seen, copies=True),
            h_ask("tool_result", ["approve", "reject"]),
            r7_terminate_orphan_result(),
        ],
    )
    sample = logged_sample(log)
    live = [
        (event.stage, seen[event.explanation or ""].call.function)
        for event in sample.events
        if isinstance(event, SentinelEvent)
        and event.path == "r7_probe"
        and event.stage.startswith("tool")
    ]
    native = next(
        event
        for event in sample.events
        if isinstance(event, ToolEvent) and event.id == "shared"
    )
    if held:
        # the orphan's check, then the native call's, both while the native
        # call awaited its result review
        assert live == [
            ("tool_call", "addition"),
            ("tool_result", ""),
            ("tool_result", "addition"),
        ]
        assert native.failed is not True
    else:
        assert live == [("tool_call", "explodes"), ("tool_result", "")]
        assert native.failed is True
    assert (
        sum(
            call.id == "shared"
            for event in sample.events
            if isinstance(event, ModelEvent)
            for call in event.output.message.tool_calls or []
        )
        == 1
    )

    # no bridged model call proposed the orphan, so replay has no step for it
    replay = assert_replay_rebuilds_bridge_steps(
        log, seen, lambda step: step.call.function != "", unbuilt=1
    )
    assert [(stage, function) for stage, function, _ in tool_step_calls(replay)] == (
        [("tool_call", "addition"), ("tool_result", "addition")]
        if held
        else [("tool_call", "explodes")]
    )
    assert all(
        step.step.result.text == "2"
        for step in replay
        if isinstance(step.step, AfterToolCall)
    )
    model_steps = [step.step for step in replay if step.stage.startswith("model")]
    assert [len(step.human_decisions or []) for step in model_steps] == (
        [0, 0, 2, 2] if held else [0, 0, 1, 1]
    )
    # nothing was rebuilt from the bridge's model calls
    assert replay_warnings(caplog) == []


@protocol(name="inspect_sentinel/human")
def r7_asks_about_orphan_result() -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.result.text == "orphan result":
            return answered(
                await context.host.ask_human(step, (), ["approve", "reject"])
            )
        return None

    return after


@pytest.mark.parametrize(
    "held",
    [
        "review",
        "terminating review",
        "failing review",
        "check",
        "check after a yielding allocator",
    ],
)
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_an_orphan_result_s_approval_never_reaches_a_native_result(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    held: OrphanHold,
    backend: str,
) -> None:
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    Panel("approve", "orphan approval").install(monkeypatch)
    gate: dict[str, anyio.Event] = {}
    log = run_logged(
        as_solver(r7_reports_orphan_result_after_native_call(held, gate)),
        outputs(
            r7_tool_calls(
                ToolCall(id="shared", function="addition", arguments={"x": 1, "y": 1})
            ),
            done(),
        ),
        sentinel=[
            r7_holds_native_result(gate),
            r7_asks_about_orphan_result(),
            r7_terminate_orphan_result(),
        ],
    )
    sample = logged_sample(log)
    begins = {e.id: e for e in sample.events if isinstance(e, SpanBeginEvent)}
    results = [
        (event.span_id, event.path)
        for event in sample.events
        if isinstance(event, SentinelEvent) and event.stage == "tool_result"
    ]
    # the orphan's check alone, in a bridge check's span: the native call's
    # abstained, or its reviewer ended the call before it
    assert [path for _, path in results] == ["human", "r7_terminate_orphan_result"]
    [orphan_span] = {span for span, _ in results}
    assert orphan_span is not None
    assert begins[orphan_span].name == "sentinel_bridge"
    native = next(
        event
        for event in sample.events
        if isinstance(event, ToolEvent) and event.id == "shared"
    )
    failed = held in ("terminating review", "failing review")
    assert native.failed is (True if failed else None)
    if held == "check after a yielding allocator":
        assert any(begin.type == "rpc" for begin in begins.values())

    replay = replayed(log)
    assert [(stage, function) for stage, function, _ in tool_step_calls(replay)] == [
        ("tool_call", "addition"),
        *([] if failed else [("tool_result", "addition")]),
    ]
    # the person approved the orphan, never the native result
    assert not any(step.recorded_answers for step in replay)
    # and the turn after it, which a terminating review ends the sample before,
    # sees that decision
    [*_, last] = [step.step for step in replay if step.stage.startswith("model")]
    assert [
        (decision.stage, decision.step_id, decision.decided.report.explanation)
        for decision in last.human_decisions or []
    ] == (
        []
        if held == "terminating review"
        else [("tool_result", "shared", "orphan approval")]
    )
    # no bridged model call proposed the orphan, so nothing was rebuilt
    assert replay_warnings(caplog) == []


@agent
def r7_reuses_one_native_call_id(turns: int) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        for turn in range(turns):
            output = await get_model().generate(state.messages, tools=[addition()])
            state.messages.append(output.message)
            result = await execute_tools(state.messages, [addition()])
            state.messages.extend(result.messages)
        return state

    return execute


def reused_id_replay_work(
    turns: int, monkeypatch: pytest.MonkeyPatch
) -> tuple[int, list[tuple[str, int, str | None]]]:
    """Span lookups while replaying serial native calls under one id, and the tool steps built.

    Replay rejects a second step under one id (`_built`), so the steps are
    collected in its place.
    """
    from inspect_ai._sentinel import _replay

    seen: dict[str, Step] = {}
    # not run_logged, whose replays would reject the second step
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=as_solver(r7_reuses_one_native_call_id(turns)),
        sentinel=[r7_probe(seen)],
    )
    log = eval(
        task,
        model=outputs(
            *[
                r7_tool_calls(
                    ToolCall(
                        id="shared", function="addition", arguments={"x": n, "y": 1}
                    )
                )
                for n in range(turns)
            ]
        ),
    )[0]
    assert log.status == "success", log.error

    class Counted(dict[Any, Any]):
        reads = 0

        def __getitem__(self, key: Any) -> Any:
            Counted.reads += 1
            return super().__getitem__(key)

        def get(self, key: Any, default: Any = None) -> Any:
            Counted.reads += 1
            return super().get(key, default)

    original = _replay._Driver.__init__

    def counting_init(driver: Any, *args: Any, **kwargs: Any) -> None:
        original(driver, *args, **kwargs)
        driver.begins = Counted()
        driver.ends = Counted()

    built: list[tuple[str, int, str | None]] = []

    def collect(
        driver: Any, step_id: str, stage: str, step: Step, span: str | None
    ) -> None:
        if stage.startswith("tool"):
            built.append((stage, step.call.arguments["x"], span))

    with monkeypatch.context() as patch:
        patch.setattr(_replay._Driver, "__init__", counting_init)
        patch.setattr(_replay._Driver, "_built", collect)
        replayed(log)
    return Counted.reads, built


def test_native_calls_reusing_one_id_keep_their_checks_in_linear_span_lookups(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    small, _ = reused_id_replay_work(12, monkeypatch)
    large, built = reused_id_replay_work(24, monkeypatch)
    assert large <= 2.2 * small, (small, large)
    assert [(stage, n) for stage, n, _ in built] == [
        (stage, n) for n in range(24) for stage in ("tool_call", "tool_result")
    ]
    spans = [span for _, _, span in built]
    assert None not in spans and len(set(spans)) == len(spans)
    assert "inspect_ai._sentinel._replay" not in {
        record.name for record in caplog.records
    }


@agent
def r7_allocates_span_ids_with_a_yield(bridged: bool, orchestrated: bool) -> Agent:
    """Three parallel native calls (`ordered_addition`) under a span-id provider that awaits, after a bridged host call with `bridged`.

    With `orchestrated`, the provider holds each native tool span until all
    three calls have been checked, and each result check until all three calls
    have run, so other calls' events separate every check from its tool span.
    """

    async def execute(state: AgentState) -> AgentState:
        checked, ran = anyio.Event(), anyio.Event()
        arrived = {"tool": 0, "result": 0}

        async def gather(stage: str, released: anyio.Event) -> None:
            arrived[stage] += 1
            if arrived[stage] == 3:
                released.set()
            await released.wait()

        async def allocate(
            name: str, parent_id: str | None, requested_id: str | None
        ) -> str:
            await anyio.lowlevel.checkpoint()
            if not orchestrated:
                pass
            elif name == "ordered_addition":
                await gather("tool", checked)
            elif name == "sentinel" and checked.is_set():
                await gather("result", ran)
            return requested_id or uuid()

        with span_id_provider(allocate):
            if bridged:
                state = await r7_runs_a_bridged_host_tool()(state)
            tool = ordered_addition()
            output = await get_model().generate(state.messages, tools=[tool])
            state.messages.append(output.message)
            result = await execute_tools(state.messages, [tool])
            state.messages.extend(result.messages)
        return state

    return execute


def native_checks_apart(sample: EvalSample) -> set[str]:
    """The stages at which some native call's check is not adjacent to its tool span."""
    events = sample.events
    begins = {
        event.id: index
        for index, event in enumerate(events)
        if isinstance(event, SpanBeginEvent)
    }
    ends = {
        event.id: index
        for index, event in enumerate(events)
        if isinstance(event, SpanEndEvent)
    }
    checks = {
        (event.stage, event.step_id): event.span_id
        for event in events
        if isinstance(event, SentinelEvent) and event.span_id is not None
    }
    apart: set[str] = set()
    for index, event in enumerate(events):
        if not isinstance(event, ToolEvent) or event.metadata:
            continue
        tool_span = cast(SpanBeginEvent, events[index - 1]).id
        before = checks[("tool_call", event.id)]
        after = checks[("tool_result", event.id)]
        if ends[before] != begins[tool_span] - 1:
            apart.add("tool_call")
        if begins[after] != ends[tool_span] + 1:
            apart.add("tool_result")
    return apart


PARALLEL_NATIVE_CALLS = calls(
    *[("ordered_addition", {"x": n, "y": 10}) for n in (1, 2, 3)]
)


@pytest.mark.parametrize("orchestrated", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_native_checks_replay_under_a_span_id_provider_that_yields(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    backend: str,
    orchestrated: bool,
) -> None:
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r7_allocates_span_ids_with_a_yield(False, orchestrated)),
        outputs(PARALLEL_NATIVE_CALLS),
        sentinel=[r7_probe(seen, copies=True)],
    )
    if orchestrated:
        assert native_checks_apart(logged_sample(log)) == {
            "tool_call",
            "tool_result",
        }
    with caplog.at_level(logging.WARNING):
        replay = assert_logged_replay_equals_live(log, seen)
    assert len([step for step in replay if step.stage.startswith("tool")]) == 6
    assert "inspect_ai._sentinel._replay" not in {
        record.name for record in caplog.records
    }


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_native_checks_under_a_span_id_provider_that_yields_beside_a_bridge_replay(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    backend: str,
) -> None:
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r7_allocates_span_ids_with_a_yield(True, orchestrated=True)),
        outputs(call("mcp__host__addition", x=1, y=1), PARALLEL_NATIVE_CALLS),
        sentinel=[r7_probe(seen, copies=True)],
    )
    sample = logged_sample(log)
    assert native_checks_apart(sample) == {"tool_call", "tool_result"}
    with caplog.at_level(logging.WARNING):
        replay = assert_replay_rebuilds_bridge_steps(
            log,
            seen,
            lambda step: step.call.function == "ordered_addition",
            HOST_DIFFERENCES,
        )
    assert len(tool_step_calls(replay)) == 6 + len(bridged_steps(log, replay))
    [host] = [e.id for e in sample.events if isinstance(e, ToolEvent) and e.metadata]
    assert bridged_call_ids(log, replay) == [host]
    assert replay_warnings(caplog) == []


@agent
def r6_executes_one_of_two_native_proposals() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        tool = addition()
        await get_model().generate(state.messages, tools=[tool])
        output = await get_model().generate(state.messages, tools=[tool])
        state.messages.append(output.message)
        result = await execute_tools(state.messages, [tool])
        state.messages.extend(result.messages)
        return state

    return execute


def test_unused_native_candidate_does_not_hide_native_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r6_executes_one_of_two_native_proposals()),
        outputs(
            r7_tool_calls(
                ToolCall(id="shared", function="addition", arguments={"x": 1, "y": 1})
            ),
            r7_tool_calls(
                ToolCall(id="shared", function="addition", arguments={"x": 2, "y": 2})
            ),
        ),
        sentinel=[r7_probe(seen)],
    )
    live = [
        seen[event.explanation or ""]
        for event in logged_sample(log).events
        if isinstance(event, SentinelEvent)
        and event.path == "r7_probe"
        and event.stage.startswith("tool")
    ]
    assert [type(step) for step in live] == [BeforeToolCall, AfterToolCall]
    replay = [
        step
        for step in replayed(log)
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ]
    assert [type(step.step) for step in replay] == [BeforeToolCall, AfterToolCall]
    for actual, rebuilt in zip(live, replay):
        assert_step_equals_live((rebuilt.stage, rebuilt.id), rebuilt, actual)
    assert replay_warnings(caplog) == []


def test_human_decision_at_shared_id_result_reaches_later_replay_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve", "allowed").install(monkeypatch)
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r7_scaffold_reports_after_a_failed_native_call("normal")),
        outputs(
            r7_tool_calls(
                ToolCall(id="shared", function="echo", arguments={"text": "x"})
            ),
            r7_tool_calls(ToolCall(id="shared", function="explodes", arguments={})),
            done(),
        ),
        sentinel=[
            r7_probe(seen, copies=True),
            h_ask("tool_result", ["approve", "reject"]),
        ],
        # as in test_a_scaffold_result_never_becomes_a_failed_native_call_s_result
        inferred="two threads in one conversation",
    )
    live = [
        seen[event.explanation or ""]
        for event in logged_sample(log).events
        if isinstance(event, SentinelEvent)
        and event.path == "r7_probe"
        and event.stage.startswith("model")
    ]
    replay = replayed(log)
    model_steps = [step.step for step in replay if step.stage.startswith("model")]
    # the failed native call has no result step; the scaffold's call has its
    # own, rebuilt from the conversation
    assert [
        (s.stage, s.id.split("/")[-1])
        for s in replay
        if isinstance(s.step, AfterToolCall)
    ] == [("tool_result", "shared")]
    assert bridged_steps(log, replay)[-1].stage == "tool_result"
    assert [len(step.human_decisions or []) for step in live] == [0, 0, 0, 0, 1, 1]
    assert [len(step.human_decisions or []) for step in model_steps] == [
        0,
        0,
        0,
        0,
        1,
        1,
    ]
    for actual, rebuilt in zip(live, model_steps):
        assert comparable(rebuilt.human_decisions) == comparable(actual.human_decisions)


@agent
def r7_runs_a_host_call_outside_its_producer() -> Agent:
    """A bridged conversation in an agent span of its own, whose host call the service runs in the enclosing span."""

    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )
        from inspect_ai.agent._bridge.sandbox.service import call_tool

        bridge, tools = await r7_host_bridge(state)
        messages: list[Any] = [{"role": "user", "content": "What is 1 + 1?"}]

        async def request() -> Any:
            completion = await inspect_completions_api_request(
                {"model": "inspect", "messages": messages, "tools": tools}, None, bridge
            )
            message = completion.choices[0].message
            messages.append(message.model_dump(exclude_none=True))
            return message.tool_calls or []

        outer, outer_agent = current_span_id(), current_agent_span_id()
        assert outer is not None
        async with span("producer", type="agent"):
            [proposed] = await request()
            with in_span(outer, outer_agent):
                result = await call_tool(bridge)(
                    "host", "addition", json.loads(proposed.function.arguments)
                )
            messages.append(
                {"role": "tool", "tool_call_id": proposed.id, "content": str(result)}
            )
            await request()
        return state

    return execute


class HostDecision(NamedTuple):
    log: EvalLog
    events: list[Event]
    producer: str
    decided: SentinelEvent
    live: list[Step]


def r7_host_decision_outside_its_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> HostDecision:
    """A person's approval of a host call's result, checked in the producer's conversation from outside its span; `live` is the model steps as the probe saw them."""
    Panel("approve", "allowed").install(monkeypatch)
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r7_runs_a_host_call_outside_its_producer()),
        outputs(
            r7_tool_calls(
                ToolCall(
                    id="cross",
                    function="mcp__host__addition",
                    arguments={"x": 1, "y": 1},
                )
            ),
            done(),
        ),
        sentinel=[
            r7_probe(seen, copies=True),
            h_ask("tool_result", ["approve", "reject"]),
        ],
    )
    events = logged_sample(log).events
    begins = {e.id: e for e in events if isinstance(e, SpanBeginEvent)}
    [producer] = [e.id for e in begins.values() if e.name == "producer"]
    [ran] = [e for e in events if isinstance(e, ToolEvent)]
    [decided] = [
        e
        for e in events
        if isinstance(e, SentinelEvent) and e.factory == "inspect_sentinel/human"
    ]
    assert decided.conversation == producer
    assert ran.span_id is not None and begins[ran.span_id].parent_id != producer
    live = [
        seen[e.explanation or ""]
        for e in events
        if isinstance(e, SentinelEvent)
        and e.path == "r7_probe"
        and e.stage.startswith("model")
    ]
    assert [len(s.human_decisions or []) for s in live] == [0, 0, 1, 1]
    return HostDecision(log, list(events), producer, decided, live)


@pytest.mark.parametrize("stored_timeline", [False, True])
def test_a_person_s_decision_at_a_host_call_run_outside_its_producer_s_span_reaches_later_turns(
    monkeypatch: pytest.MonkeyPatch, stored_timeline: bool
) -> None:
    log, events, producer, _, _ = r7_host_decision_outside_its_producer(monkeypatch)
    turns = [e for e in events if isinstance(e, ModelEvent)]
    timeline = Timeline(
        name="target",
        description="",
        root=TimelineSpan(
            id="target",
            name="target",
            content=[TimelineEvent(event=e) for e in turns],
        ),
    )
    replay = replay_events(
        log, events, **({"timeline": timeline} if stored_timeline else {})
    )
    # a timeline that does not place the decision gives it the conversation
    # of the model call that proposed the host call; the rebuilt result step
    # comes before the request that carries the result, after the bridge's
    # check of it settled
    assert [(s.stage, len(s.step.human_decisions or [])) for s in replay] == [
        ("model_input", 0),
        ("model_output", 0),
        ("tool_call", 0),
        ("tool_result", 1),
        ("model_input", 1),
        ("model_output", 1),
    ]
    assert {s.step.conversation for s in replay} == {
        "target" if stored_timeline else producer
    }


def test_a_person_s_decision_at_a_host_call_stays_in_the_branch_a_timeline_places_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log, events, _, decided, _ = r7_host_decision_outside_its_producer(monkeypatch)
    first, second = [e for e in events if isinstance(e, ModelEvent)]
    # the first turn and the decision in one conversation, the second turn in
    # a branch of its own
    timeline = Timeline(
        name="split",
        description="",
        root=TimelineSpan(
            id="first",
            name="first",
            content=[TimelineEvent(event=e) for e in events if e is not second],
            branches=[
                TimelineSpan(
                    id="second",
                    name="second",
                    content=[TimelineEvent(event=second)],
                )
            ],
        ),
    )
    assert any(
        item.event is decided
        for item in timeline.root.content
        if isinstance(item, TimelineEvent)
    )
    replay = replay_events(log, events, timeline=timeline)
    # the host call's result reached the model in another conversation, so
    # its call has no result step
    assert [
        (s.stage, s.step.conversation, len(s.step.human_decisions or []))
        for s in replay
    ] == [
        ("model_input", "first", 0),
        ("model_output", "first", 0),
        ("tool_call", "first", 0),
        ("model_input", "second", 0),
        ("model_output", "second", 0),
    ]


class NumberedPanel:
    """A person who approves every question, numbering each answer by the call it is about (`answer #n for <id>`)."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def acp(**kwargs: object) -> Approval | None:
            return None

        async def panel(
            message: str,
            call: ToolCall,
            view: ToolCallView,
            history: object,
            choices: list[str],
        ) -> Approval:
            self.asked.append(call.id)
            return Approval(
                decision="approve",
                explanation=f"answer #{len(self.asked)} for {call.id}",
            )

        monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
        monkeypatch.setattr(approver_module, "panel_approval", panel)

    def answer(self, call_id: str, which: int) -> str:
        """The explanation of the person's answer about `call_id`: `which` is an index into those answers."""
        numbers = [n for n, asked in enumerate(self.asked, 1) if asked == call_id]
        return f"answer #{numbers[which]} for {call_id}"


R12_ECHO: Any = {
    "type": "function",
    "function": {
        "name": "echo",
        "description": "Echo the text.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
}


async def r12_scaffold_turns(state: AgentState, create: Any) -> None:
    """A scaffold handed the agent's history: it runs `echo` itself and asks again."""
    from inspect_ai.model._openai import messages_to_openai

    messages: list[Any] = await messages_to_openai(state.messages)
    for _ in range(3):
        completion = await create(messages)
        message = completion.choices[0].message
        messages.append(message.model_dump(exclude_none=True))
        if not message.tool_calls:
            return
        for tool_call in message.tool_calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.loads(tool_call.function.arguments)["text"],
                }
            )


@agent(name="bridged", description="Continue in a bridged scaffold.")
def r12_bridged() -> Agent:
    """An in-process bridged scaffold continuing the conversation it is handed."""

    async def execute(state: AgentState) -> AgentState:
        from openai import AsyncOpenAI

        async with agent_bridge(state) as bridge:
            async with AsyncOpenAI(api_key="sk-test") as client:

                async def create(messages: list[Any]) -> Any:
                    return await client.chat.completions.create(
                        model="inspect", messages=messages, tools=[R12_ECHO]
                    )

                await r12_scaffold_turns(state, create)
            return bridge.state

    return execute


@agent
def r12_sandbox_bridged() -> Agent:
    """The sandbox bridge's request path, without a container."""

    async def execute(state: AgentState) -> AgentState:
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )
        from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge

        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=8080,
            model=None,
        )

        async def create(messages: list[Any]) -> Any:
            return await inspect_completions_api_request(
                {"model": "inspect", "messages": messages, "tools": [R12_ECHO]},
                None,
                bridge,
            )

        await r12_scaffold_turns(state, create)
        return bridge.state

    return execute


@agent
def r12_react_then_bridges(bridges: int) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        state = await react(tools=[addition()], submit=False)(state)
        for _ in range(bridges):
            state = await r12_bridged()(state)
        return state

    return execute


R12_NATIVE = ToolCall(id="native_add", function="addition", arguments={"x": 1, "y": 1})
R12_TRANSFER = ToolCall(
    id="native_transfer", function="transfer_to_bridged", arguments={}
)


def r12_echo(call_id: str) -> ModelOutput:
    return r7_tool_calls(
        ToolCall(id=call_id, function="echo", arguments={"text": call_id})
    )


class HandedOver(NamedTuple):
    solver: Solver | list[Solver]
    outputs: list[ModelOutput]
    bridge_calls: list[str]
    """The calls the scaffolds ran."""
    native_answers: dict[str, int]
    """The native calls, each with which of the person's answers about it its own check got."""


def r12_handed_over(flow: str) -> HandedOver:
    """Native calls, then a bridge handed their history: the flows of a native solver or agent continuing into a bridged one."""
    native = [r7_tool_calls(R12_NATIVE), done("native done")]
    bridge = [r12_echo("bridge_echo"), done("bridge done")]
    first = {"native_add": 0}
    if flow == "as_solver":
        return HandedOver(
            [use_tools(addition()), generate(), as_solver(r12_bridged())],
            native + bridge,
            ["bridge_echo"],
            first,
        )
    if flow == "react_then_bridge":
        return HandedOver(
            as_solver(r12_react_then_bridges(1)),
            native + bridge,
            ["bridge_echo"],
            first,
        )
    if flow == "handoff":
        # the transfer's result is checked after the handoff returns
        return HandedOver(
            as_solver(react(tools=[addition(), handoff(r12_bridged())], submit=False)),
            [r7_tool_calls(R12_NATIVE), r7_tool_calls(R12_TRANSFER), *bridge, done()],
            ["bridge_echo"],
            {"native_add": 0, "native_transfer": -1},
        )
    if flow == "sandbox":
        return HandedOver(
            [use_tools(addition()), generate(), as_solver(r12_sandbox_bridged())],
            native + bridge,
            ["bridge_echo"],
            first,
        )
    assert flow == "two_bridges"
    return HandedOver(
        as_solver(r12_react_then_bridges(2)),
        [*native, *bridge, r12_echo("bridge_echo2"), done("bridge2 done")],
        ["bridge_echo", "bridge_echo2"],
        first,
    )


R12_FLOWS = ["as_solver", "react_then_bridge", "handoff", "sandbox", "two_bridges"]


@pytest.mark.parametrize("flow", R12_FLOWS)
def test_native_calls_handed_to_a_bridge_keep_their_own_checks(
    flow: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    person = NumberedPanel()
    person.install(monkeypatch)
    handed = r12_handed_over(flow)
    seen: dict[str, Step] = {}
    log = run_logged(
        handed.solver,
        outputs(*handed.outputs),
        sentinel=[r7_probe(seen, copies=True), h_ask("tool_result", ["approve"])],
    )
    sample = logged_sample(log)
    begins = {e.id: e for e in sample.events if isinstance(e, SpanBeginEvent)}
    native_ids = set(handed.native_answers)
    # the person is asked once about each result: a bridge does not check the
    # results it was handed (the handoff's transfer, before the native call's
    # own check; an earlier bridge's) again
    assert sorted(person.asked) == sorted([*native_ids, *handed.bridge_calls])
    # each scaffold call is checked in a bridge check's span
    assert {
        begins[e.span_id].name
        for e in sample.events
        if isinstance(e, SentinelEvent)
        and e.span_id is not None
        and e.step_id in handed.bridge_calls
    } == {"sentinel_bridge"}

    # a scaffold call's rebuilt result step comes before the request carrying
    # the result, so after the person's decision at the bridge's check of it,
    # which live's step preceded
    replay = assert_replay_rebuilds_bridge_steps(
        log,
        seen,
        lambda step: step.call.id in native_ids,
        ["tool_result.human_decisions"],
    )
    scaffold = bridged_steps(log, replay)
    assert [s.id.split("/")[-1] for s in scaffold] == [
        call_id for call_id in handed.bridge_calls for _ in ("call", "result")
    ]
    assert not any(step.recorded_answers for step in scaffold)
    rebuilt = [
        (step.stage, step.id)
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
        and step not in scaffold
    ]
    assert sorted(rebuilt) == sorted(
        (stage, call_id)
        for call_id in native_ids
        for stage in ("tool_call", "tool_result")
    )
    for step in replay:
        if step.stage == "tool_result" and step not in scaffold:
            assert dict(step.recorded_answers) == {
                "human": HumanAnswer(
                    decision="approve",
                    reason=person.answer(step.id, handed.native_answers[step.id]),
                )
            }
    assert replay_warnings(caplog) == []


R13_HELPER = ToolCall(id="helper_add", function="addition", arguments={"x": 2, "y": 3})


def r13_helper_filter(helper: str) -> Any:
    """A bridge request filter that, on the first request, runs a native tool loop (or a native agent) in a conversation of its own, then lets the request through."""
    ran: list[bool] = []

    async def run_helper(
        model: Any,
        messages: list[ChatMessage],
        tools: list[Any],
        tool_choice: Any,
        config: Any,
    ) -> None:
        if ran:
            return None
        ran.append(True)
        conversation: list[ChatMessage] = [ChatMessageUser(content="helper task")]
        if helper == "agent":
            await react(tools=[addition()], submit=False)(
                AgentState(messages=conversation)
            )
            return None
        assert helper == "tool_loop"
        while True:
            output = await get_model().generate(conversation, tools=[addition()])
            conversation.append(output.message)
            if not output.message.tool_calls:
                return None
            results, _ = await execute_tools(conversation, [addition()])
            conversation.extend(results)

    return run_helper


@agent
def r13_filtered(bridge: str, helper: str) -> Agent:
    """A scaffold whose bridge's request filter runs a native helper."""

    async def execute(state: AgentState) -> AgentState:
        from openai import AsyncOpenAI

        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )
        from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge

        request_filter = r13_helper_filter(helper)
        if bridge == "sandbox":
            sandbox_bridge = SandboxAgentBridge(
                state=state,
                filter=request_filter,
                retry_refusals=None,
                compaction=None,
                port=8080,
                model=None,
            )

            async def create_sandbox(messages: list[Any]) -> Any:
                return await inspect_completions_api_request(
                    {"model": "inspect", "messages": messages, "tools": [R12_ECHO]},
                    None,
                    sandbox_bridge,
                )

            await r12_scaffold_turns(state, create_sandbox)
            return sandbox_bridge.state

        assert bridge == "in_process"
        async with agent_bridge(state, filter=request_filter) as in_process:
            async with AsyncOpenAI(api_key="sk-test") as client:

                async def create(messages: list[Any]) -> Any:
                    return await client.chat.completions.create(
                        model="inspect", messages=messages, tools=[R12_ECHO]
                    )

                await r12_scaffold_turns(state, create)
            return in_process.state

    return execute


@pytest.mark.parametrize("helper", ["tool_loop", "agent"])
@pytest.mark.parametrize("bridge", ["in_process", "sandbox"])
def test_a_native_helper_in_a_bridge_request_filter_keeps_its_tool_steps(
    bridge: str, helper: str
) -> None:
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r13_filtered(bridge, helper)),
        outputs(r7_tool_calls(R13_HELPER), done("helper done"), done("bridge done")),
        sentinel=[r7_probe(seen, copies=True)],
    )
    sample = logged_sample(log)
    # the helper's generations ran under the bridge's routing
    assert all(
        event.requested_model == "inspect"
        for event in sample.events
        if isinstance(event, ModelEvent)
    )
    # the helper's conversation is not in the scaffold's history
    assert all(
        "helper" not in message.text
        for message in sample.messages
        if not isinstance(message, ChatMessageTool)
    )
    assert "helper_add" not in {
        call.id
        for message in sample.messages
        if isinstance(message, ChatMessageAssistant)
        for call in message.tool_calls or []
    }

    replay = assert_replay_rebuilds_bridge_steps(
        log, seen, lambda step: step.call.id == "helper_add"
    )
    rebuilt = [
        step for step in replay if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ]
    assert [(step.stage, step.id) for step in rebuilt] == [
        ("tool_call", "helper_add"),
        ("tool_result", "helper_add"),
    ]
    # the producer's context, which assert_replay_skips_bridge_steps has
    # checked equals live's
    for step in rebuilt:
        assert step.step.input and step.step.input[-1].text == "helper task"
        assert [tool.name for tool in step.step.tools or []] == ["addition"]
        assert step.step.tool_choice is not None


@approver
def rejects_first_call() -> Approver:
    decided: list[str] = []

    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        decided.append(call.id)
        return Approval(decision="reject" if len(decided) == 1 else "approve")

    return approve


def test_an_approver_refused_call_leaves_a_later_same_id_call_its_result_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # after Ransom's review 5810823986: the refused call took the result check
    # of the later call that ran under its id
    Panel("approve", "the sum is right").install(monkeypatch)
    proposed = ModelOutput.for_tool_call(
        "mockllm/model",
        tool_name="addition",
        tool_arguments={"x": 1, "y": 1},
        tool_call_id="call_0",
    )
    seen: dict[str, Step] = {}
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[use_tools(addition()), generate()],
        approval=[ApprovalPolicy(rejects_first_call(), "*")],
        sentinel=[
            r7_probe(seen, copies=True),
            h_ask("tool_result", ["approve"]),
        ],
    )
    log = eval(
        task,
        model=outputs(proposed, proposed, done()),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    assert log.location and log.location.endswith(".json")
    refused, ran = [e for e in logged_sample(log).events if isinstance(e, ToolEvent)]
    assert refused.error is not None and refused.error.type == "approval"
    assert ran.error is None

    replay = assert_logged_replay_equals_live(log, seen)
    [result] = [step for step in replay if step.stage == "tool_result"]
    assert dict(result.recorded_answers) == {
        "human": HumanAnswer(decision="approve", reason="the sum is right")
    }


def _nested(depth: int) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for _ in range(depth):
        value = {"deeper": value}
    return value


# a first call that never runs, each rejected another way; the model then
# corrects it under the same id, as a provider that repeats ids sends it
NEVER_RAN: dict[str, ToolCall] = {
    "invalid_arguments": ToolCall(
        id="call_0", function="keep", arguments={"payload": "bad"}
    ),
    "malformed_json": ToolCall(
        id="call_0",
        function="keep",
        arguments={},
        parse_error="Error parsing the following tool call arguments: {",
    ),
    "too_deep": ToolCall(
        id="call_0", function="keep", arguments={"payload": _nested(101)}
    ),
    "unknown_tool": ToolCall(id="call_0", function="missing", arguments={}),
}


@pytest.mark.parametrize("watched", ["calls_and_results", "results"])
@pytest.mark.parametrize("rejected", list(NEVER_RAN))
def test_a_call_that_never_ran_leaves_a_later_same_id_call_its_result_check(
    rejected: str, watched: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # after Ransom's review 5869595286: a call rejected before it ran took the
    # result check, and the person's answer, of the corrected call under its id
    Panel("approve", "the corrected call is fine").install(monkeypatch)

    @tool
    def keep() -> Tool:
        async def execute(payload: dict[str, Any]) -> str:
            """Keep a payload.

            Args:
                payload: The payload to keep.
            """
            return "kept"

        return execute

    def proposes(call: ToolCall) -> ModelOutput:
        return ModelOutput(
            model="mockllm/model",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content="", tool_calls=[call]),
                    stop_reason="tool_calls",
                )
            ],
        )

    corrected = ToolCall(id="call_0", function="keep", arguments={"payload": {}})
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Keep the payload")],
            solver=[use_tools(keep()), generate()],
            sentinel=[
                *([r7_probe(seen, copies=True)] if watched != "results" else []),
                h_ask("tool_result", ["approve"]),
            ],
        ),
        model=outputs(proposes(NEVER_RAN[rejected]), proposes(corrected), done()),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    assert log.location and log.location.endswith(".json")
    first, ran = [e for e in logged_sample(log).events if isinstance(e, ToolEvent)]
    assert first.id == ran.id == "call_0"
    assert first.error is not None and first.error.type == "parsing"
    assert first.failed is None
    assert ran.error is None and ran.arguments == {"payload": {}}

    # read back from the log: the corrected call keeps its result check, the
    # person's answer at it, and that decision in the steps after it
    read = read_eval_log(log.location)
    replay = (
        # with nothing recording the live steps, there are none to compare
        replayed(read)
        if watched == "results"
        else assert_logged_replay_equals_live(read, seen)
    )
    [result] = [step for step in replay if step.stage == "tool_result"]
    assert isinstance(result.step, AfterToolCall)
    assert result.step.call.arguments == {"payload": {}}
    assert dict(result.recorded_answers) == {
        "human": HumanAnswer(decision="approve", reason="the corrected call is fine")
    }
    later = [step.step for step in replay if step.stage == "model_input"][-1]
    assert [
        (decision.step_id, decision.stage) for decision in later.human_decisions or []
    ] == [("call_0", "tool_result")]


@pytest.mark.parametrize("error", [ToolParsingError, ToolApprovalError])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_concurrent_agent_s_refused_same_id_call_leaves_a_call_its_result_check(
    error: type[Exception],
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # agent B's approver-refused call under A's id ends before A's result
    # check begins, and must leave it to A
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    a_started, b_done = anyio.Event(), anyio.Event()

    @tool
    def rendezvous() -> Tool:
        async def execute(kind: str) -> str:
            """Fail once agent B's call was refused.

            Args:
                kind: The agent making the call.
            """
            a_started.set()
            await b_done.wait()
            raise error(f"refused inside {kind}'s tool")

        return execute

    @solver
    def two_agents() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            async def agent_a() -> None:
                await run(react(tools=[rendezvous()], submit=False), "agent A")

            async def agent_b() -> None:
                await a_started.wait()
                await run(
                    react(
                        tools=[rendezvous()],
                        submit=False,
                        approval=[ApprovalPolicy(r7_decides("reject"), "*")],
                    ),
                    "agent B",
                )
                b_done.set()

            await tg_collect([agent_a, agent_b])
            return state

        return solve

    proposed = [
        ModelOutput.for_tool_call(
            "mockllm/model",
            tool_name="rendezvous",
            tool_arguments={"kind": kind},
            tool_call_id="tool_call_0_0",
        )
        for kind in ("A", "B")
    ]
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="run two agents")],
            solver=two_agents(),
            sentinel=[r7_probe(seen, copies=True)],
        ),
        model=outputs(*proposed, done(), done()),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    a, b = [e for e in logged_sample(log).events if isinstance(e, ToolEvent)]
    assert a.arguments == {"kind": "A"} and b.arguments == {"kind": "B"}
    assert a.error is not None and b.error is not None
    assert b.error.type == "approval"

    replay = assert_logged_replay_equals_live(log, seen)
    assert [(stage, arguments) for stage, _, arguments in tool_step_calls(replay)] == [
        ("tool_call", {"kind": "A"}),
        ("tool_result", {"kind": "A"}),
    ]


@reviewer
def checks_with_a_same_id_call(invalid: bool) -> Reviewer:
    async def check(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        helper = get_model(
            "mockllm/review-helper",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    "mockllm/review-helper",
                    tool_name="addition",
                    tool_arguments={"x": "one" if invalid else 1, "y": 1},
                    tool_call_id="tool_call_0_0",
                )
            ],
            memoize=False,
        )
        messages: list[ChatMessage] = [ChatMessageUser(content="Check the result")]
        tools = [addition()]
        proposed = await helper.generate(messages, tools=tools)
        await execute_tools([*messages, proposed.message], tools)
        return Review(decision="continue")

    return check


@pytest.mark.parametrize("invalid", [False, True])
@pytest.mark.parametrize("error", [ToolParsingError, ToolApprovalError])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_result_reviewer_s_same_id_call_leaves_the_reviewed_call_its_result_check(
    invalid: bool,
    error: type[Exception],
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # after the pre-push review of 059291126: the reviewer's call under the
    # reviewed call's id runs between that call's tool span and its result
    # check, and took that check
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    Panel("approve", "reviewed the tool error").install(monkeypatch)

    @tool
    def fails_after_running() -> Tool:
        async def execute() -> str:
            """Raise an error after running."""
            raise error("could not interpret the tool output")

        return execute

    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Run the tool")],
            solver=[use_tools(fails_after_running()), generate()],
            review=[
                ReviewPolicy(checks_with_a_same_id_call(invalid), "fails_after_running")
            ],
            sentinel=[
                r7_probe(seen, copies=True),
                h_ask("tool_result", ["approve"]),
            ],
        ),
        model=outputs(
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="fails_after_running",
                tool_arguments={},
                tool_call_id="tool_call_0_0",
            ),
            done(),
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = [e for e in logged_sample(log).events if isinstance(e, ToolEvent)]
    assert [e.function for e in events] == ["fails_after_running", "addition"]
    assert events[0].error is not None
    assert (events[1].error is not None) == invalid

    # without origins, the reviewer's call reads as an agent call under the
    # same id, so only the replay with origins is compared
    live = live_steps(logged_sample(log), seen)
    replay = replayed(log)
    rebuilt: dict[tuple[str, str], ReplayStep] = {
        (step.stage, step.id): step for step in replay
    }
    assert len(rebuilt) == len(replay) and set(rebuilt) == set(live)
    for key, step in live.items():
        assert_step_equals_live(key, rebuilt[key], step)
    [result] = [step for step in replay if step.stage == "tool_result"]
    assert dict(result.recorded_answers) == {
        "human": HumanAnswer(decision="approve", reason="reviewed the tool error")
    }


# Ransom's round-8 B3 on #5765: a generation in the call's conversation
# proposes its id again while the call's check awaits
_SAME_ID_TURN: dict[str, anyio.Event] = {}


@tool
def read_path() -> Tool:
    async def execute(path: str) -> str:
        """Read a file.

        Args:
            path: The path.
        """
        return f"contents of {path}"

    return execute


@protocol
def r7_modifies_once_a_same_id_turn_completes() -> Protocol:
    async def check(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        _SAME_ID_TURN["started"].set()
        await _SAME_ID_TURN["generated"].wait()
        return Decision(
            action="modify",
            modified=replace(step.call, arguments={"path": "safe.txt"}),
            explanation="safer",
        )

    return check


@solver
def a_same_id_turn_completes_during_a_call_check(again: str | None) -> Solver:
    """Run a call while another turn of its conversation proposes its id: from `again` as a new user message, or from the same input (a cache hit)."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        started, generated = anyio.Event(), anyio.Event()
        _SAME_ID_TURN.update(started=started, generated=generated)
        model = get_model()
        tools = [read_path()]
        messages: list[ChatMessage] = [ChatMessageUser(content="Read the file")]
        first = await model.generate(messages, tools=tools)

        async def run_call() -> None:
            await execute_tools([*messages, first.message], tools)

        async def generate_again() -> None:
            await started.wait()
            await model.generate(
                [*messages, ChatMessageUser(content=again)] if again else messages,
                tools=tools,
            )
            generated.set()

        await tg_collect([run_call, generate_again])
        return state

    return solve


@pytest.mark.parametrize("replies", ["same", "distinct"])
@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_call_check_pairs_with_its_call_when_a_same_id_turn_completes_during_it(
    replies: str,
    approved: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # "same": the second generation returns the first's reply again from the
    # same input, as a cache hit does (one message id); "distinct": another
    # turn, from other input, proposes another call under the id
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    reply, again = (
        ModelOutput.for_tool_call(
            "mockllm/model",
            tool_name="read_path",
            tool_arguments={"path": path},
            tool_call_id="call_x",
            content=content,
        )
        for path, content in [("bad.txt", "Reading it."), ("other.txt", "Other.")]
    )
    if replies == "same":
        again = reply
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Read the file")],
            solver=a_same_id_turn_completes_during_a_call_check(
                "Read it again" if replies == "distinct" else None
            ),
            sentinel=[
                r7_probe(seen, copies=True),
                r7_modifies_once_a_same_id_turn_completes(),
            ],
            approval=[ApprovalPolicy(auto_approver(), "*")] if approved else None,
        ),
        model=outputs(reply, again),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    [ran] = [e for e in events if isinstance(e, ToolEvent)]
    assert ran.arguments == {"path": "safe.txt"}
    proposals = [e for e in events if isinstance(e, ModelEvent)]
    assert len(proposals) == 2
    assert (proposals[0].output.message.id == proposals[1].output.message.id) == (
        replies == "same"
    )

    # the check names the call it judged, so it pairs with it, and with the
    # generation that proposed it: its call, message and input equal live
    with caplog.at_level(logging.WARNING):
        replay = assert_logged_replay_equals_live(log, seen, old_log_differs=True)
    assert "match no tool call" not in caplog.text
    assert [(stage, arguments) for stage, _, arguments in tool_step_calls(replay)] == [
        ("tool_call", {"path": "bad.txt"}),
        ("tool_result", {"path": "safe.txt"}),
    ]
    tool_steps = [
        s.step for s in replay if isinstance(s.step, BeforeToolCall | AfterToolCall)
    ]
    assert len(tool_steps) == 2
    assert {(s.message, s.message_id) for s in tool_steps} == {
        ("Reading it.", proposals[0].output.message.id)
    }
    for step in tool_steps:
        assert [m.text for m in step.input or []] == ["Read the file"]

    # a log without execution ids joins the call to the generation its event
    # names (`call_message_id`), so pairs the check as well; where a cache hit
    # gave both generations that message id, it pairs a call check only after
    # the latest proposal of its id, so the check is orphaned as before
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        old = replay_events(log, without_execution_ids(events))
    if replies == "distinct":
        assert "match no tool call" not in caplog.text
        assert replay_record(old) == replay_record(replay)
    else:
        assert "match no tool call" in caplog.text
        assert [(stage, arguments) for stage, _, arguments in tool_step_calls(old)] == [
            ("tool_call", {"path": "safe.txt"}),
            ("tool_result", {"path": "safe.txt"}),
        ]


@pytest.mark.parametrize("error", [ToolParsingError, ToolApprovalError])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_call_that_raised_after_running_keeps_its_result_check_without_a_call_monitor(
    error: type[Exception],
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #5765's known limit: with no monitor at tool_call, a tool that raised
    # an oversight error after running reads as a call that never ran
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    Panel("approve", "reviewed the tool error").install(monkeypatch)

    @tool
    def fails_after_running() -> Tool:
        async def execute() -> str:
            """Raise an error after running."""
            raise error("could not interpret the tool output")

        return execute

    log = eval(
        Task(
            dataset=[Sample(input="Run the tool")],
            solver=[use_tools(fails_after_running()), generate()],
            review=[
                ReviewPolicy(checks_with_a_same_id_call(False), "fails_after_running")
            ],
            sentinel=[h_ask("tool_result", ["approve"])],
        ),
        model=outputs(
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="fails_after_running",
                tool_arguments={},
                tool_call_id="tool_call_0_0",
            ),
            done(),
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert [e.function for e in runs] == ["fails_after_running", "addition"]

    # the result check names the reviewed call, so the reviewer's call under
    # its id, which ended first, can't take it
    [result] = [step for step in replayed(log) if step.stage == "tool_result"]
    assert isinstance(result.step, AfterToolCall)
    assert result.step.call.function == "fails_after_running"
    assert dict(result.recorded_answers) == {
        "human": HumanAnswer(decision="approve", reason="reviewed the tool error")
    }

    # a log without execution ids gives it to the reviewer's call, as before
    [old] = [
        step
        for step in replay_events(log, without_execution_ids(events))
        if step.stage == "tool_result"
    ]
    assert isinstance(old.step, AfterToolCall)
    assert old.step.call.function == "addition"


@pytest.mark.parametrize("probed", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_call_that_raised_and_its_same_id_retry_replay_as_two_executions(
    probed: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # a tool raises ToolParsingError, and the model retries the call under the
    # same id (a provider that repeats ids), with only a result check, or with
    # a probe at every stage too
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    Panel("approve", "reviewed the run").install(monkeypatch)
    attempts: list[str] = []
    seen: dict[str, Step] = {}

    @tool
    def parse_once() -> Tool:
        async def execute(text: str) -> str:
            """Fail to parse the first input.

            Args:
                text: The input.
            """
            attempts.append(text)
            if len(attempts) == 1:
                raise ToolParsingError("could not parse the input")
            return f"parsed {text}"

        return execute

    log = eval(
        Task(
            dataset=[Sample(input="Parse it")],
            solver=[use_tools(parse_once()), generate()],
            sentinel=[
                *([r7_probe(seen, copies=True)] if probed else []),
                h_ask("tool_result", ["approve"]),
            ],
        ),
        model=outputs(
            *(
                ModelOutput.for_tool_call(
                    "mockllm/model",
                    tool_name="parse_once",
                    tool_arguments={"text": text},
                    tool_call_id="tool_call_0_0",
                )
                for text in ("first", "second")
            ),
            done(),
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert [e.id for e in runs] == ["tool_call_0_0", "tool_call_0_0"]
    assert [e.error.type if e.error else None for e in runs] == ["parsing", None]
    executions = [e.execution_id for e in runs]
    assert None not in executions and executions[0] != executions[1]

    # each run is its own execution: the first keeps the call id, and the
    # retry, whose call id is taken, is named by its execution id
    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    assert replay_warnings(caplog) == []
    answer = {"human": HumanAnswer(decision="approve", reason="reviewed the run")}
    assert [
        (s.stage, s.id, s.step.call.arguments, dict(s.recorded_answers))
        for s in replay
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
    ] == [
        ("tool_call", "tool_call_0_0", {"text": "first"}, {}),
        ("tool_result", "tool_call_0_0", {"text": "first"}, answer),
        ("tool_call", executions[1], {"text": "second"}, {}),
        ("tool_result", executions[1], {"text": "second"}, answer),
    ]
    if probed:
        assert_tool_steps_equal_live_by_execution(log, seen, replay)
        # a log without execution ids, where both runs passed a call check,
        # can't be replayed, as before
        with pytest.raises(MalformedLogError, match="Two tool_call steps"):
            replay_events(log, without_execution_ids(events))
        return

    # a log without execution ids replays the retry alone, warning that the
    # first run's result check matches no call
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        old = replay_events(log, without_execution_ids(events))
    assert "match no tool call" in caplog.text
    assert [
        (s.stage, s.id, s.step.call.arguments)
        for s in old
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
    ] == [
        ("tool_call", "tool_call_0_0", {"text": "second"}),
        ("tool_result", "tool_call_0_0", {"text": "second"}),
    ]


@protocol
def r7_rejects_the_first_call() -> Protocol:
    async def before_call(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.call.arguments.get("text") == "first":
            return Decision(action="reject", explanation="not the first")
        return None

    return before_call


@pytest.mark.parametrize("probed", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_call_rejected_at_tool_call_and_its_same_id_retries_replay_as_executions(
    probed: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # a sentinel rejects a call at tool_call, and the model retries it twice
    # under the same id: the reject pairs through the call check, not a result
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}

    @tool
    def echo() -> Tool:
        async def execute(text: str) -> str:
            """Echo the input.

            Args:
                text: The input.
            """
            return f"echo {text}"

        return execute

    texts = ["first", "second", "third"]
    log = eval(
        Task(
            dataset=[Sample(input="Echo it")],
            solver=[use_tools(echo()), generate()],
            sentinel=[
                *([r7_probe(seen, copies=True)] if probed else []),
                r7_rejects_the_first_call(),
            ],
        ),
        model=outputs(
            *(
                ModelOutput.for_tool_call(
                    "mockllm/model",
                    tool_name="echo",
                    tool_arguments={"text": text},
                    tool_call_id="tool_call_0_0",
                )
                for text in texts
            ),
            done(),
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert [e.id for e in runs] == ["tool_call_0_0"] * 3
    assert [e.error.type if e.error else None for e in runs] == [
        "approval",
        None,
        None,
    ]
    executions = [e.execution_id for e in runs]
    assert None not in executions and len(set(executions)) == 3
    assert [
        e.execution_id
        for e in events
        if isinstance(e, SentinelEvent) and e.action == "reject"
    ] == executions[:1]

    # the rejected call keeps the call id, and each retry is named by its
    # execution id
    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    assert replay_warnings(caplog) == []
    assert [
        (s.stage, s.id, s.step.call.arguments)
        for s in replay
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
    ] == [
        ("tool_call", "tool_call_0_0", {"text": "first"}),
        ("tool_call", executions[1], {"text": "second"}),
        ("tool_result", executions[1], {"text": "second"}),
        ("tool_call", executions[2], {"text": "third"}),
        ("tool_result", executions[2], {"text": "third"}),
    ]
    if probed:
        assert_tool_steps_equal_live_by_execution(log, seen, replay)

    # a log without execution ids can't be replayed, as before
    with pytest.raises(MalformedLogError, match="Two tool_call steps"):
        replay_events(log, without_execution_ids(events))


def assert_tool_steps_equal_live_by_execution(
    log: EvalLog, seen: dict[str, Step], replay: Sequence["ReplayStep"]
) -> None:
    """Compare each replayed native tool step with the one `r7_probe(seen, copies=True)` saw live at its stage and execution: live records two executions of one call id under the same step id."""
    events = logged_sample(log).events
    live = {
        (e.stage, e.execution_id): seen[e.explanation or ""]
        for e in events
        if isinstance(e, SentinelEvent)
        and e.path == "r7_probe"
        and e.stage in ("tool_call", "tool_result")
    }
    # a replayed step's id is its call id, or the execution id of a later
    # execution of that call id
    first: dict[str, str | None] = {}
    for e in events:
        if isinstance(e, ToolEvent):
            first.setdefault(e.id, e.execution_id)
    rebuilt = {
        (s.stage, first.get(s.id, s.id)): s
        for s in replay
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
    }
    assert set(rebuilt) == set(live)
    for (stage, execution), step in live.items():
        assert_step_equals_live(
            (stage, execution or ""), rebuilt[(stage, execution)], step
        )


def test_each_native_run_names_its_approvals_and_steps() -> None:
    # a model that repeats a call id across turns
    repeated = [
        ModelOutput.for_tool_call(
            "mockllm/model",
            tool_name="addition",
            tool_arguments={"x": x, "y": 1},
            tool_call_id="call_0",
        )
        for x in (1, 2)
    ]
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="What is 1 + 1?", target="2")],
            solver=[use_tools(addition()), generate()],
            sentinel=[r7_probe(seen, copies=True)],
            approval=[ApprovalPolicy(auto_approver(), "*")],
        ),
        model=outputs(*repeated, done()),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert [e.id for e in runs] == ["call_0", "call_0"]
    executions = [e.execution_id for e in runs]
    assert None not in executions and executions[0] != executions[1]
    assert [
        e.execution_id for e in events if isinstance(e, ApprovalEvent)
    ] == executions
    for stage in ("tool_call", "tool_result"):
        assert [
            e.execution_id
            for e in events
            if isinstance(e, SentinelEvent) and e.stage == stage
        ] == executions
    assert [
        e.execution_id
        for e in events
        if isinstance(e, SentinelEvent) and e.stage.startswith("model")
    ] == [None] * 6

    # replay names the second run's steps by its execution id, the call id
    # being the first's
    replay = replayed(log)
    assert [
        (s.stage, s.id, s.step.call.arguments)
        for s in replay
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
    ] == [
        ("tool_call", "call_0", {"x": 1, "y": 1}),
        ("tool_result", "call_0", {"x": 1, "y": 1}),
        ("tool_call", executions[1], {"x": 2, "y": 1}),
        ("tool_result", executions[1], {"x": 2, "y": 1}),
    ]
    assert_tool_steps_equal_live_by_execution(log, seen, replay)


@pytest.mark.parametrize("stage", ["tool_call", "tool_result"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_person_s_decisions_at_two_runs_of_one_call_id_keep_its_step_id(
    stage: str, backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a model that repeats a call id across turns, with a person deciding each
    # run at `stage`: later steps see both decisions under the recorded call
    # id, though replay names the second run's steps by its execution id
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    Panel("approve", "the sum is right").install(monkeypatch)
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="What is 1 + 1?", target="2")],
            solver=[use_tools(addition()), generate()],
            sentinel=[
                r7_probe(seen, copies=True),
                h_ask(stage, ["approve"]),
            ],
        ),
        model=outputs(
            *(
                ModelOutput.for_tool_call(
                    "mockllm/model",
                    tool_name="addition",
                    tool_arguments={"x": x, "y": 1},
                    tool_call_id="call_0",
                )
                for x in (1, 2)
            ),
            done(),
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    executions = [e.execution_id for e in events if isinstance(e, ToolEvent)]
    assert None not in executions and executions[0] != executions[1]
    probed = [
        e for e in events if isinstance(e, SentinelEvent) and e.path == "r7_probe"
    ]
    live = [seen[e.explanation or ""] for e in probed]
    assert [(d.stage, d.step_id) for d in live[-1].human_decisions or []] == [
        (stage, "call_0"),
        (stage, "call_0"),
    ]

    replay = replayed(log)
    assert [s.id for s in replay if s.stage == stage] == ["call_0", executions[1]]
    assert [(d.stage, d.step_id) for d in replay[-1].step.human_decisions or []] == [
        (stage, "call_0"),
        (stage, "call_0"),
    ]
    assert [(s.stage, s.step.conversation) for s in replay] == [
        (e.stage, step.conversation) for e, step in zip(probed, live, strict=True)
    ]
    for rebuilt, step in zip(replay, live, strict=True):
        assert comparable(rebuilt.step.human_decisions) == comparable(
            step.human_decisions
        ), rebuilt.id


@tool
def delete_file() -> Tool:
    async def execute(path: str) -> str:
        """Delete a file.

        Args:
            path: The file.
        """
        return f"deleted {path}"

    return execute


def one_response(*calls: tuple[str, str]) -> ModelOutput:
    """A response proposing each (function, path) under the call id `"null"`, as Mistral's converter names calls whose ids the model omitted."""
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content="",
                    tool_calls=[
                        ToolCall(id="null", function=function, arguments={"path": path})
                        for function, path in calls
                    ],
                ),
                stop_reason="tool_calls",
            )
        ],
    )


def replayed_calls(replay: Sequence["ReplayStep"]) -> list[tuple[str, str, Any]]:
    return [
        (s.stage, s.step.call.function, s.step.call.arguments)
        for s in replay
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
    ]


@pytest.mark.parametrize("deleted", ["old.txt", "readme.txt"])
@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_distinct_calls_of_one_response_under_one_id_replay_as_proposed(
    deleted: str,
    approved: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # after Ransom's review 5930221109: replay rebuilt the first call's check
    # with the second call's function; the calls differ in their function
    # alone, or in their arguments too
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Tidy up")],
            solver=[use_tools(read_path(), delete_file()), generate()],
            sentinel=[r7_probe(seen, copies=True)],
            approval=[ApprovalPolicy(auto_approver(), "*")] if approved else None,
        ),
        model=outputs(
            one_response(("read_path", "readme.txt"), ("delete_file", deleted)),
            done(),
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert sorted((e.id, e.function) for e in runs) == [
        ("null", "delete_file"),
        ("null", "read_path"),
    ]

    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    assert replay_warnings(caplog) == []
    by_function = {
        (stage, function): arguments
        for stage, function, arguments in replayed_calls(replay)
    }
    assert by_function == {
        ("tool_call", "read_path"): {"path": "readme.txt"},
        ("tool_result", "read_path"): {"path": "readme.txt"},
        ("tool_call", "delete_file"): {"path": deleted},
        ("tool_result", "delete_file"): {"path": deleted},
    }
    assert_tool_steps_equal_live_by_execution(log, seen, replay)

    # a log without execution ids can't be replayed, as before
    with pytest.raises(MalformedLogError, match="Two tool_call steps"):
        replay_events(log, without_execution_ids(events))


@protocol
def r7_moves_the_read_of_a() -> Protocol:
    async def before_call(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.call.arguments == {"path": "a.txt"}:
            return Decision(
                action="modify",
                modified=replace(step.call, arguments={"path": "b.txt"}),
                explanation="read b instead",
            )
        return None

    return before_call


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_calls_of_one_function_in_one_response_under_one_id_pair_by_arguments(
    approved: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # two calls of one function under one id differ only in their arguments:
    # each execution is paired with the call its recorded arguments name
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Read them")],
            solver=[use_tools(read_path()), generate()],
            sentinel=[r7_probe(seen, copies=True)],
            approval=[ApprovalPolicy(auto_approver(), "*")] if approved else None,
        ),
        model=outputs(
            one_response(("read_path", "a.txt"), ("read_path", "b.txt")), done()
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    assert replay_warnings(caplog) == []
    assert sorted(replayed_calls(replay), key=str) == sorted(
        [
            (stage, "read_path", {"path": path})
            for stage in ("tool_call", "tool_result")
            for path in ("a.txt", "b.txt")
        ],
        key=str,
    )
    assert_tool_steps_equal_live_by_execution(log, seen, replay)


class R7Spec(BaseModel):
    path: str
    mode: str = "r"


@tool
def open_spec() -> Tool:
    async def execute(spec: R7Spec) -> str:
        """Open a file.

        Args:
            spec: The file and its mode.
        """
        return f"opened {spec.path} ({spec.mode})"

    return execute


def open_specs_under_null() -> ModelOutput:
    """A response opening a.txt and b.txt under the call id `"null"`, each spec without the mode validation fills in."""
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="null",
                            function="open_spec",
                            arguments={"spec": {"path": path}},
                        )
                        for path in ("a.txt", "b.txt")
                    ],
                ),
                stop_reason="tool_calls",
            )
        ],
    )


def replayed_under_an_unknown_version(log: EvalLog) -> list["ReplayStep"]:
    """Replay `log` as if its header recorded no inspect_ai version, so its approvals are not taken as the calls they approved."""
    sample = logged_sample(log)
    return steps_from_events(
        sample.messages,
        sample.events,
        [],
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval)._replace(inspect_ai_version=None),
    )


@pytest.mark.parametrize("header", ["recorded", "unknown"])
@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_calls_of_one_function_under_one_id_whose_arguments_validation_changes_replay(
    header: str,
    approved: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # validation fills each call's default, so neither recorded execution's
    # arguments are a proposed call's; the calls differ only in their
    # arguments, which the steps take from the log
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Open them")],
            solver=[use_tools(open_spec()), generate()],
            sentinel=[r7_probe(seen, copies=True)],
            approval=[ApprovalPolicy(auto_approver(), "*")] if approved else None,
        ),
        model=outputs(open_specs_under_null(), done()),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    runs = [e for e in logged_sample(log).events if isinstance(e, ToolEvent)]
    assert sorted((e.arguments for e in runs), key=str) == [
        {"spec": {"path": path, "mode": "r"}} for path in ("a.txt", "b.txt")
    ]

    with caplog.at_level(logging.WARNING):
        replay = (
            replayed(log)
            if header == "recorded"
            else replayed_under_an_unknown_version(log)
        )
    assert replay_warnings(caplog) == []
    if header == "recorded":
        assert_tool_steps_equal_live_by_execution(log, seen, replay)
    else:
        # an unknown version changes fields other than the call (`truncated`)
        assert sorted(replayed_calls(replay), key=str) == sorted(
            [
                (stage, "open_spec", e.arguments)
                for e in runs
                for stage in ("tool_call", "tool_result")
            ],
            key=str,
        )


@protocol
def r7_moves_the_open_of_a() -> Protocol:
    async def before_call(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.call.arguments["spec"]["path"] == "a.txt":
            return Decision(
                action="modify",
                modified=replace(
                    step.call, arguments={"spec": {"path": "c.txt", "mode": "r"}}
                ),
                explanation="open c instead",
            )
        return None

    return before_call


@pytest.mark.parametrize("header", ["recorded", "unknown"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_modified_call_whose_arguments_validation_changes_is_rebuilt_only_from_a_reliable_approval(
    header: str,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # a sentinel modify's tool_call step is built from the call its approval
    # records, which a log of unknown version can't be trusted for: its
    # proposal's arguments would be used, so it is skipped rather than built
    # from whichever call of its function comes first
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Open them")],
            solver=[use_tools(open_spec()), generate()],
            sentinel=[r7_probe(seen, copies=True), r7_moves_the_open_of_a()],
            approval=[ApprovalPolicy(auto_approver(), "*")],
        ),
        model=outputs(open_specs_under_null(), done()),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert sorted((e.arguments for e in runs), key=str) == [
        {"spec": {"path": path, "mode": "r"}} for path in ("b.txt", "c.txt")
    ]

    with caplog.at_level(logging.WARNING):
        replay = (
            replayed(log)
            if header == "recorded"
            else replayed_under_an_unknown_version(log)
        )
    if header == "recorded":
        assert replay_warnings(caplog) == []
        assert_tool_steps_equal_live_by_execution(log, seen, replay)
        return
    [warning] = [w for w in replay_warnings(caplog) if "several calls" in w]
    assert "'null'" in warning
    assert replayed_calls(replay) == [
        (stage, "open_spec", {"spec": {"path": "b.txt", "mode": "r"}})
        for stage in ("tool_call", "tool_result")
    ]


@solver
def r7_prefills_two_calls_under_null() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.messages.append(
            ChatMessageAssistant(
                content="Pre-filled.",
                tool_calls=[
                    ToolCall(id="null", function="read_path", arguments={"path": "a"}),
                    ToolCall(
                        id="null", function="delete_file", arguments={"path": "b"}
                    ),
                ],
            )
        )
        result = await execute_tools(state.messages, state.tools)
        state.messages.extend(result.messages)
        return state

    return solve


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_prefilled_call_under_an_id_a_later_response_reuses_replays_from_its_own_message(
    approved: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # no model call proposed the pre-filled calls, and the model's later
    # response proposes calls under the same id: each pre-filled execution is
    # rebuilt from the message its ToolEvent names
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Tidy up")],
            solver=[
                use_tools(read_path(), delete_file()),
                r7_prefills_two_calls_under_null(),
                generate(),
            ],
            sentinel=[r7_probe(seen, copies=True)],
            approval=[ApprovalPolicy(auto_approver(), "*")] if approved else None,
        ),
        model=outputs(one_response(("delete_file", "c"), ("read_path", "d")), done()),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    runs = [e for e in logged_sample(log).events if isinstance(e, ToolEvent)]
    assert len(runs) == 4 and {e.id for e in runs} == {"null"}
    assert len({e.call_message_id for e in runs}) == 2

    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    assert replay_warnings(caplog) == []
    assert_tool_steps_equal_live_by_execution(log, seen, replay)


@pytest.mark.parametrize("stage", ["tool_call", "tool_result"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_person_s_decisions_at_a_skipped_call_of_a_shared_id_reach_later_steps(
    stage: str,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # the moved call's steps are skipped (no approval shows which call it
    # was), but a person's decision at each still reaches the later steps
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    Panel("approve", "fine").install(monkeypatch)
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Read them")],
            solver=[use_tools(read_path()), generate()],
            sentinel=[
                r7_probe(seen, copies=True),
                r7_moves_the_read_of_a(),
                h_ask(stage, ["approve"]),
            ],
        ),
        model=outputs(
            one_response(("read_path", "a.txt"), ("read_path", "b.txt")), done()
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    probed = [
        e for e in events if isinstance(e, SentinelEvent) and e.path == "r7_probe"
    ]
    last = seen[probed[-1].explanation or ""]
    assert [(d.stage, d.step_id) for d in last.human_decisions or []] == [
        (stage, "null"),
        (stage, "null"),
    ]

    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    assert any("several calls" in w for w in replay_warnings(caplog))
    assert replay[-1].stage == probed[-1].stage
    assert comparable(replay[-1].step.human_decisions) == comparable(
        last.human_decisions
    )


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_modified_call_of_one_response_under_a_shared_id_is_paired_only_by_its_approval(
    approved: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # a sentinel changes the read of a.txt to b.txt, the arguments of the
    # response's other call under its id: its ToolEvent then records the
    # other call's arguments, so only an approval, which records the call
    # before the change, shows which call ran
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Read them")],
            solver=[use_tools(read_path()), generate()],
            sentinel=[r7_probe(seen, copies=True), r7_moves_the_read_of_a()],
            approval=[ApprovalPolicy(auto_approver(), "*")] if approved else None,
        ),
        model=outputs(
            one_response(("read_path", "a.txt"), ("read_path", "b.txt")), done()
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert [e.arguments for e in runs] == [{"path": "b.txt"}] * 2
    moved = next(
        e.execution_id
        for e in events
        if isinstance(e, SentinelEvent) and e.action == "modify"
    )

    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    if approved:
        assert replay_warnings(caplog) == []
        assert_tool_steps_equal_live_by_execution(log, seen, replay)
        return
    # without an approval the moved call's steps are skipped, never rebuilt
    # from the other call
    [warning] = [w for w in replay_warnings(caplog) if "several calls" in w]
    assert "'null'" in warning
    assert replayed_calls(replay) == [
        ("tool_call", "read_path", {"path": "b.txt"}),
        ("tool_result", "read_path", {"path": "b.txt"}),
    ]
    [kept] = [e.execution_id for e in runs if e.execution_id != moved]
    live = {
        e.stage: seen[e.explanation or ""]
        for e in events
        if isinstance(e, SentinelEvent)
        and e.path == "r7_probe"
        and e.execution_id == kept
    }
    for step in replay:
        if isinstance(step.step, BeforeToolCall | AfterToolCall):
            assert_step_equals_live((step.stage, step.id), step, live[step.stage])


def memory_calls_under_null(*calls: dict[str, Any]) -> ModelOutput:
    """A response proposing each `memory()` call under the call id `"null"`."""
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content="",
                    tool_calls=[
                        ToolCall(id="null", function="memory", arguments=arguments)
                        for arguments in calls
                    ],
                ),
                stop_reason="tool_calls",
            )
        ],
    )


@protocol
def r7_moves_memory_a_to_an_unresolved_path() -> Protocol:
    async def before_call(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.call.arguments.get("path") == "/memories/a":
            return Decision(
                action="modify",
                modified=replace(
                    step.call,
                    arguments={**step.call.arguments, "path": "/memories/sub/../c"},
                ),
                explanation="use c instead",
            )
        return None

    return before_call


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("command", ["view", "create"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_modified_memory_call_under_a_shared_id_is_skipped_though_the_tool_resolved_its_path(
    approved: bool,
    command: str,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # after Ransom's review 5931343576: memory() records the modify's path
    # resolved (/memories/c), not as the modify recorded it, so replay missed
    # the modify and rebuilt the moved call's check of /memories/a from the
    # call whose arguments the log records
    from inspect_ai.tool import memory

    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    if command == "view":
        tool = memory(
            initial_data={f"/memories/{name}": name for name in ("a", "b", "c")}
        )
        extra: dict[str, Any] = {}
    else:
        tool = memory()
        extra = {"file_text": "x"}
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Remember")],
            solver=[use_tools(tool), generate()],
            sentinel=[
                r7_probe(seen, copies=True),
                r7_moves_memory_a_to_an_unresolved_path(),
            ],
            approval=[ApprovalPolicy(auto_approver(), "*")] if approved else None,
        ),
        model=outputs(
            memory_calls_under_null(
                *(
                    {"command": command, "path": f"/memories/{name}", **extra}
                    for name in ("a", "b")
                )
            ),
            done(),
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert all(e.error is None for e in runs)
    assert sorted((e.arguments["path"] for e in runs), key=str) == [
        "/memories/b",
        "/memories/c",
    ]
    [modify] = [
        e for e in events if isinstance(e, SentinelEvent) and e.action == "modify"
    ]
    assert modify.modified is not None
    assert modify.modified.arguments["path"] == "/memories/sub/../c"
    moved = modify.execution_id
    assert seen_at(events, seen, "tool_call", moved).call.arguments["path"] == (
        "/memories/a"
    )

    if approved:
        # the approved call is not the call the ToolEvent records, and no
        # recorded modify names that call, so the log is refused, as before
        with pytest.raises(
            ValueError, match="approved call does not match the ToolEvent"
        ):
            replayed(log)
        return
    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    # without an approval the moved call's steps are skipped, never rebuilt
    # from the other call
    [warning] = [w for w in replay_warnings(caplog) if "several calls" in w]
    assert "'null'" in warning
    assert replayed_calls(replay) == [
        (stage, "memory", {"command": command, "path": "/memories/b", **extra})
        for stage in ("tool_call", "tool_result")
    ]
    [kept] = [e.execution_id for e in runs if e.execution_id != moved]
    for step in replay:
        if isinstance(step.step, BeforeToolCall | AfterToolCall):
            assert_step_equals_live(
                (step.stage, step.id), step, seen_at(events, seen, step.stage, kept)
            )

    # without execution ids the calls aren't paired, and the moved call is
    # skipped since its tool recorded other arguments than its modify's
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        replay = replay_events(log, without_execution_ids(events))
    assert replay_warnings(caplog) == [UNMATCHED_MODIFY.format("'null'")]
    assert replayed_calls(replay) == [
        (stage, "memory", {"command": command, "path": "/memories/b", **extra})
        for stage in ("tool_call", "tool_result")
    ]
    for step in replay:
        if isinstance(step.step, BeforeToolCall | AfterToolCall):
            assert_step_equals_live(
                (step.stage, step.id), step, seen_at(events, seen, step.stage, kept)
            )


def seen_at(
    events: Sequence[Event], seen: dict[str, Step], stage: str, execution: str | None
) -> Step:
    """The step `r7_probe(seen, copies=True)` saw live at `stage` of `execution`."""
    [step] = [
        seen[e.explanation or ""]
        for e in events
        if isinstance(e, SentinelEvent)
        and e.path == "r7_probe"
        and e.stage == stage
        and e.execution_id == execution
    ]
    return step


def memory_view(id: str, name: str) -> ToolCall:
    return ToolCall(
        id=id,
        function="memory",
        arguments={"command": "view", "path": f"/memories/{name}"},
    )


@pytest.mark.parametrize("shape", ["other_function", "repeated_id", "unique_id"])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_modified_call_whose_tool_resolved_its_path_is_skipped(
    shape: str,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # a modify the tool rewrote (memory() resolves /memories/sub/../c) matches
    # no ToolEvent, so replay rebuilt the moved call's check from the ToolEvent
    # with no warning: under an id shared with another function's call or
    # repeated across responses (the merge base refuses both logs), and under a
    # unique id (as on main)
    from inspect_ai.tool import memory

    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    responses = {
        "other_function": [
            r7_tool_calls(
                memory_view("null", "a"),
                ToolCall(id="null", function="read_path", arguments={"path": "b"}),
            )
        ],
        "repeated_id": [
            r7_tool_calls(memory_view("r", "a")),
            r7_tool_calls(memory_view("r", "b")),
        ],
        "unique_id": [r7_tool_calls(memory_view("u1", "a"), memory_view("u2", "b"))],
    }[shape]
    moved_id = {"other_function": "null", "repeated_id": "r", "unique_id": "u1"}[shape]
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Remember")],
            solver=[
                use_tools(
                    memory(
                        initial_data={
                            f"/memories/{name}": name for name in ("a", "b", "c")
                        }
                    ),
                    read_path(),
                ),
                generate(),
            ],
            sentinel=[
                r7_probe(seen, copies=True),
                r7_moves_memory_a_to_an_unresolved_path(),
            ],
        ),
        model=outputs(*responses, done()),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert all(e.error is None for e in runs)
    [modify] = [
        e for e in events if isinstance(e, SentinelEvent) and e.action == "modify"
    ]
    assert modify.modified is not None
    assert modify.modified.arguments["path"] == "/memories/sub/../c"
    moved = modify.execution_id
    [moved_run] = [e for e in runs if e.execution_id == moved]
    assert moved_run.id == moved_id
    assert moved_run.arguments["path"] == "/memories/c"
    assert seen_at(events, seen, "tool_call", moved).call.arguments["path"] == (
        "/memories/a"
    )

    with caplog.at_level(logging.WARNING):
        replay = replayed(log)
    assert replay_warnings(caplog) == [UNMATCHED_MODIFY.format(repr(moved_id))]
    # every live step but the moved call's tool steps is rebuilt as live saw it
    live = [
        (e.stage, seen[e.explanation or ""])
        for e in events
        if isinstance(e, SentinelEvent)
        and e.path == "r7_probe"
        and not (e.execution_id == moved and e.stage in ("tool_call", "tool_result"))
    ]
    assert [s.stage for s in replay] == [stage for stage, _ in live]
    for (stage, step), rebuilt in zip(live, replay):
        assert_step_equals_live((stage, rebuilt.id), rebuilt, step)
    other = "read_path" if shape == "other_function" else "memory"
    assert [function for _, function, _ in replayed_calls(replay)] == [other] * 2


@tool
def r7_store_data() -> Tool:
    async def execute(data: dict[str, Any]) -> str:
        """Store data.

        Args:
            data: The data.
        """
        return f"stored {json.dumps(data)}"

    return execute


@protocol
def r7_modifies_data(target: dict[str, Any]) -> Protocol:
    """Modify the call whose arguments are exactly `target` (by `repr`, so `True` is not `1`) to store 2."""

    async def before_call(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if repr(step.call.arguments) == repr(target):
            return Decision(
                action="modify",
                modified=replace(step.call, arguments={"data": {"value": 2}}),
                explanation="store 2 instead",
            )
        return None

    return before_call


@pytest.mark.parametrize(
    "number,other,pairs",
    [
        ({"data": {"value": 1}}, {"data": {"value": True}}, False),
        (
            {"data": {"inner": {"flag": 0}}},
            {"data": {"inner": {"flag": False}}},
            False,
        ),
        ({"data": {"value": [1, 0]}}, {"data": {"value": [1, False]}}, False),
        ({"data": {"value": 1}}, {"data": {"value": 1.0}}, True),
    ],
    ids=["true_1", "nested_false_0", "list_false_0", "float_1"],
)
@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_modified_call_under_a_shared_id_tells_booleans_from_numbers(
    number: dict[str, Any],
    other: dict[str, Any],
    pairs: bool,
    approved: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # after Ransom's review 5932143555: Python equality took the calls for
    # one call, so replay presented the call with the number where live
    # checked the one with the boolean; JSON equality keeps them apart, as
    # it keeps 1 and 1.0 together. Since review 5932732710 the moved call is
    # skipped either way, and the warning shows whether the calls were apart
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Store them")],
            solver=[use_tools(r7_store_data()), generate()],
            sentinel=[r7_probe(seen, copies=True), r7_modifies_data(other)],
            approval=[ApprovalPolicy(auto_approver(), "*")] if approved else None,
        ),
        model=outputs(
            ModelOutput(
                model="mockllm/model",
                choices=[
                    ChatCompletionChoice(
                        message=ChatMessageAssistant(
                            content="",
                            tool_calls=[
                                ToolCall(
                                    id="null",
                                    function="r7_store_data",
                                    arguments=arguments,
                                )
                                for arguments in (number, other)
                            ],
                        ),
                        stop_reason="tool_calls",
                    )
                ],
            ),
            done(),
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert all(e.error is None for e in runs)
    [modify] = [
        e for e in events if isinstance(e, SentinelEvent) and e.action == "modify"
    ]
    moved = modify.execution_id
    [moved_run] = [e for e in runs if e.execution_id == moved]
    assert moved_run.arguments == {"data": {"value": 2}}
    # the JSON round trip keeps the checked call's booleans and floats
    checked = seen_at(events, seen, "tool_call", moved).call.arguments
    assert repr(checked) == repr(other)

    with caplog.at_level(logging.WARNING):
        replay = (replayed_under_an_unknown_version if approved else replayed)(log)
    [kept] = [e.execution_id for e in runs if e.execution_id != moved]
    first = runs[0].execution_id
    rebuilt: dict[tuple[str, str | None], "ReplayStep"] = {
        (s.stage, first if s.id == "null" else s.id): s
        for s in replay
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
    }
    called = {
        key: s.step.call.arguments
        for key, s in rebuilt.items()
        if isinstance(s.step, BeforeToolCall | AfterToolCall)
    }
    expected: dict[tuple[str, str | None], dict[str, Any]] = {
        ("tool_call", kept): number,
        ("tool_result", kept): number,
    }
    # the moved call's steps are skipped, never rebuilt from the other call:
    # the booleans without an approval name no call; with the approval, which
    # names the moved call by its arguments, and for 1 and 1.0, which are one
    # call, no approval replay relies on records the call live checked
    [warning] = replay_warnings(caplog)
    if approved or pairs:
        assert warning == UNRECORDED_CHECK.format("'null'")
    else:
        assert "several calls" in warning
        assert "'null'" in warning
    assert set(rebuilt) == set(expected)
    for key, arguments in expected.items():
        assert repr(called[key]) == repr(arguments), key
    if approved:
        # an unknown version changes fields other than the call (`truncated`)
        return
    for (stage, execution), step in rebuilt.items():
        assert_step_equals_live(
            (stage, step.id), step, seen_at(events, seen, stage, execution)
        )


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_check_with_a_superseded_modify_or_another_decision_pairs_by_arguments(
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # only a reported modify leaves an execution's recorded arguments short of
    # naming its call: a superseded modify, or a reported decision of another
    # action, at its check does not
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    log = eval(
        Task(
            dataset=[Sample(input="Read them")],
            solver=[use_tools(read_path()), generate()],
            sentinel=[r7_probe({})],
        ),
        model=outputs(
            one_response(("read_path", "a.txt"), ("read_path", "b.txt")), done()
        ),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    probe = next(
        e
        for e in events
        if isinstance(e, SentinelEvent)
        and e.path == "r7_probe"
        and e.stage == "tool_call"
    )
    decisions = [
        probe.model_copy(
            update={
                "path": "r7_other",
                "kind": "decision",
                "status": status,
                "action": action,
                "modified": ToolCall(
                    id="null", function="read_path", arguments={"path": "c.txt"}
                )
                if action == "modify"
                else None,
            }
        )
        for status, action in (("superseded", "modify"), ("reported", "proceed"))
    ]
    at = events.index(probe) + 1

    with caplog.at_level(logging.WARNING):
        replay = replay_events(log, [*events[:at], *decisions, *events[at:]])
    assert replay_warnings(caplog) == []
    assert sorted(replayed_calls(replay), key=str) == sorted(
        [
            (stage, "read_path", {"path": path})
            for stage in ("tool_call", "tool_result")
            for path in ("a.txt", "b.txt")
        ],
        key=str,
    )


@protocol
def r7_modifies_the_checked_call(
    checked: dict[str, Any], modified: dict[str, Any]
) -> Protocol:
    """Modify the call checked with exactly the arguments `checked` to `modified`."""

    async def before_call(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if repr(step.call.arguments) == repr(checked):
            return Decision(
                action="modify",
                modified=replace(step.call, arguments=modified),
                explanation="changed",
            )
        return None

    return before_call


class CheckedFormCase(NamedTuple):
    """A call whose tool checks other arguments than the model proposed."""

    tool: Callable[[], Tool]
    proposed: dict[str, Any]
    checked: dict[str, Any]
    modified: dict[str, Any]
    other: dict[str, Any]


def checked_form_case(variant: str) -> CheckedFormCase:
    from inspect_ai.tool import memory

    if variant == "pydantic_default":
        return CheckedFormCase(
            open_spec,
            proposed={"spec": {"path": "a.txt"}},
            checked={"spec": {"path": "a.txt", "mode": "r"}},
            modified={"spec": {"path": "c.txt", "mode": "r"}},
            other={"spec": {"path": "b.txt"}},
        )
    command = "create" if variant == "memory_create" else "view"
    extra = {"file_text": "x"} if command == "create" else {}
    seeded = {f"/memories/{name}": name for name in ("a", "b", "c")}

    def tool() -> Tool:
        if variant == "memory_create":
            return memory()
        return memory(initial_data=seeded, readonly=variant == "memory_readonly_view")

    def path(path: str) -> dict[str, Any]:
        return {"command": command, "path": path, **extra}

    return CheckedFormCase(
        tool,
        proposed=path("/memories/sub/../a"),
        checked=path("/memories/a"),
        modified=path("/memories/c"),
        other=path("/memories/b"),
    )


@pytest.mark.parametrize(
    "variant",
    ["memory_view", "memory_readonly_view", "memory_create", "pydantic_default"],
)
@pytest.mark.parametrize("shape", ["other_function", "repeated_id", "unique_id"])
@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_a_modified_call_whose_checked_arguments_the_log_lacks_is_skipped_under_a_shared_id(
    variant: str,
    shape: str,
    approved: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # after Ransom's review 5932732710: the tool's validation changes the
    # model's arguments (memory() resolves /memories/sub/../a, Pydantic fills
    # a default) before the check, and a sentinel modify then replaces them,
    # so without an approval the log records neither the checked call nor
    # anything to tell it from the proposal; under a shared or repeated id
    # (refused by the merge base) replay rebuilt the check from the proposal
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    case = checked_form_case(variant)
    function = "open_spec" if variant == "pydantic_default" else "memory"

    def proposed(id: str, arguments: dict[str, Any]) -> ToolCall:
        return ToolCall(id=id, function=function, arguments=arguments)

    responses = {
        "other_function": [
            r7_tool_calls(
                proposed("null", case.proposed),
                ToolCall(id="null", function="read_path", arguments={"path": "b"}),
            )
        ],
        "repeated_id": [
            r7_tool_calls(proposed("r", case.proposed)),
            r7_tool_calls(proposed("r", case.other)),
        ],
        "unique_id": [
            r7_tool_calls(proposed("u1", case.proposed), proposed("u2", case.other))
        ],
    }[shape]
    moved_id = {"other_function": "null", "repeated_id": "r", "unique_id": "u1"}[shape]
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Remember")],
            solver=[use_tools(case.tool(), read_path()), generate()],
            sentinel=[
                r7_probe(seen, copies=True),
                r7_modifies_the_checked_call(case.checked, case.modified),
            ],
            approval=[ApprovalPolicy(auto_approver(), "*")] if approved else None,
        ),
        model=outputs(*responses, done()),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert all(e.error is None for e in runs)
    [modify] = [
        e for e in events if isinstance(e, SentinelEvent) and e.action == "modify"
    ]
    moved = modify.execution_id
    [moved_run] = [e for e in runs if e.execution_id == moved]
    assert moved_run.id == moved_id
    assert moved_run.arguments == case.modified
    # live checked the validated call, which differs from the proposal
    checked = seen_at(events, seen, "tool_call", moved).call.arguments
    assert repr(checked) == repr(case.checked)
    assert checked != case.proposed

    skipped = not approved and shape != "unique_id"
    live = [
        (e.stage, seen[e.explanation or ""], e.execution_id)
        for e in events
        if isinstance(e, SentinelEvent)
        and e.path == "r7_probe"
        and not (
            skipped
            and e.execution_id == moved
            and e.stage in ("tool_call", "tool_result")
        )
    ]
    # a log written before execution ids skips the call alike
    for recorded in [events, without_execution_ids(events)] if skipped else [events]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replay_events(log, recorded)
        assert [s.stage for s in replay] == [stage for stage, _, _ in live]
        if not skipped:
            assert replay_warnings(caplog) == []
        else:
            assert replay_warnings(caplog) == [UNRECORDED_CHECK.format(repr(moved_id))]
        for (stage, step, execution), rebuilt in zip(live, replay):
            if not approved and stage == "tool_call" and execution == moved:
                # under a unique id, as on main: rebuilt from the proposal,
                # which the log cannot tell from the checked call
                assert isinstance(rebuilt.step, BeforeToolCall)
                assert rebuilt.step.call.arguments == case.proposed
                assert_step_equals_live(
                    (stage, rebuilt.id),
                    rebuilt,
                    step,
                    differences=["tool_call.call", "tool_call.view"],
                )
                continue
            assert_step_equals_live((stage, rebuilt.id), rebuilt, step)


@approver
def r7_modifies_the_proposal(
    proposed: dict[str, Any], modified: dict[str, Any]
) -> Approver:
    """Modify the call proposed with exactly the arguments `proposed` to `modified`, and approve the rest."""

    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        if repr(call.arguments) == repr(proposed):
            return Approval(
                decision="modify",
                modified=replace(call, arguments=modified),
                explanation="moved",
            )
        return Approval(decision="approve")

    return approve


class ApproverModifiedCase(NamedTuple):
    """A `memory()` call an approver modifies to a path its tool resolves.

    A modify the tool's validation would fill a Pydantic default into is
    refused live, so a tool's canonical arguments are what can change it.
    """

    tool: Callable[[], Tool]
    proposed: dict[str, Any]
    approved: dict[str, Any]
    checked: dict[str, Any]
    modified: dict[str, Any]
    other: dict[str, Any]


def approver_modified_case(variant: str) -> ApproverModifiedCase:
    from inspect_ai.tool import memory

    command = "view" if variant == "readonly_view" else variant
    extras: dict[str, dict[str, Any]] = {
        "create": {"file_text": "x"},
        "str_replace": {"old_str": "text", "new_str": "y"},
        "insert": {"insert_line": 0, "insert_text": "y"},
    }
    extra = extras.get(command, {})
    seeded = {f"/memories/{name}": "text" for name in ("a", "b", "c", "p")}

    def tool() -> Tool:
        if command == "create":
            return memory()
        return memory(initial_data=seeded, readonly=variant == "readonly_view")

    def arguments(name: str) -> dict[str, Any]:
        path = f"/memories/{name}"
        if command == "rename":
            target = f"/memories/{name.rsplit('/', 1)[-1]}2"
            return {"command": command, "old_path": path, "new_path": target}
        return {"command": command, "path": path, **extra}

    return ApproverModifiedCase(
        tool,
        proposed=arguments("p"),
        approved=arguments("sub/../a"),
        checked=arguments("a"),
        modified=arguments("c"),
        other=arguments("b"),
    )


@pytest.mark.parametrize(
    "variant",
    [
        "view",
        "readonly_view",
        "create",
        "str_replace",
        "insert",
        "delete",
        "rename",
    ],
)
@pytest.mark.parametrize("shape", ["other_function", "repeated_id", "unique_id"])
@pytest.mark.parametrize("sentinel_modifies", [True, False])
@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_an_approver_modified_call_a_sentinel_modified_is_skipped_under_a_shared_id(
    variant: str,
    shape: str,
    sentinel_modifies: bool,
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # after Ransom's review 5940838848: the approval records the approver's
    # modify before its tool validated it (memory() resolves
    # /memories/sub/../a), and a sentinel modify then replaces the validated
    # call in the ToolEvent, so the log does not record the call the sentinel
    # checked; under a shared or repeated id (refused by the merge base)
    # replay rebuilt the check from the approval's modify. The control has no
    # sentinel modify, and an approver modify the tool does not rewrite (one
    # it rewrites is refused: `_check_modified_approval`).
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    case = approver_modified_case(variant)
    approved = case.approved if sentinel_modifies else case.checked

    def proposed(id: str, arguments: dict[str, Any]) -> ToolCall:
        return ToolCall(id=id, function="memory", arguments=arguments)

    responses = {
        "other_function": [
            r7_tool_calls(
                proposed("null", case.proposed),
                ToolCall(id="null", function="read_path", arguments={"path": "b"}),
            )
        ],
        "repeated_id": [
            r7_tool_calls(proposed("r", case.proposed)),
            r7_tool_calls(proposed("r", case.other)),
        ],
        "unique_id": [
            r7_tool_calls(proposed("u1", case.proposed), proposed("u2", case.other))
        ],
    }[shape]
    moved_id = {"other_function": "null", "repeated_id": "r", "unique_id": "u1"}[shape]
    seen: dict[str, Step] = {}
    log = eval(
        Task(
            dataset=[Sample(input="Remember")],
            solver=[use_tools(case.tool(), read_path()), generate()],
            sentinel=[
                r7_probe(seen, copies=True),
                *(
                    [r7_modifies_the_checked_call(case.checked, case.modified)]
                    if sentinel_modifies
                    else []
                ),
            ],
            approval=[
                ApprovalPolicy(r7_modifies_the_proposal(case.proposed, approved), "*")
            ],
        ),
        model=outputs(*responses, done()),
        log_format="json",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    events = logged_sample(log).events
    runs = [e for e in events if isinstance(e, ToolEvent)]
    assert all(e.error is None for e in runs), [e.error for e in runs]
    [approval] = [
        e
        for e in events
        if isinstance(e, ApprovalEvent)
        and e.modified is not None
        and e.modified.function == "memory"
    ]
    assert approval.decision == "modify" and approval.modified is not None
    assert approval.modified.arguments == approved
    moved = approval.execution_id
    [moved_run] = [e for e in runs if e.execution_id == moved]
    assert moved_run.id == moved_id
    modifies = [
        e for e in events if isinstance(e, SentinelEvent) and e.action == "modify"
    ]
    assert [e.execution_id for e in modifies] == ([moved] if sentinel_modifies else [])
    assert moved_run.arguments == (case.modified if sentinel_modifies else case.checked)
    # live checked the approver's call as its tool validated it
    checked = seen_at(events, seen, "tool_call", moved).call.arguments
    assert repr(checked) == repr(case.checked)
    assert (checked != approved) == sentinel_modifies

    skipped = sentinel_modifies and shape != "unique_id"
    live = [
        (e.stage, seen[e.explanation or ""], e.execution_id)
        for e in events
        if isinstance(e, SentinelEvent)
        and e.path == "r7_probe"
        and not (
            skipped
            and e.execution_id == moved
            and e.stage in ("tool_call", "tool_result")
        )
    ]
    # a log written before execution ids skips the call alike
    for recorded in [events, without_execution_ids(events)] if skipped else [events]:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            replay = replay_events(log, recorded)
        assert [s.stage for s in replay] == [stage for stage, _, _ in live]
        if skipped:
            assert replay_warnings(caplog) == [UNRECORDED_CHECK.format(repr(moved_id))]
        else:
            assert replay_warnings(caplog) == []
        for (stage, step, execution), rebuilt in zip(live, replay):
            if sentinel_modifies and stage == "tool_call" and execution == moved:
                # under a unique id, as on main: rebuilt from the approval's
                # modify, which the log cannot tell from the checked call
                assert isinstance(rebuilt.step, BeforeToolCall)
                assert rebuilt.step.call.arguments == approved
                assert_step_equals_live(
                    (stage, rebuilt.id),
                    rebuilt,
                    step,
                    differences=["tool_call.call", "tool_call.view"],
                )
                continue
            assert_step_equals_live((stage, rebuilt.id), rebuilt, step)
