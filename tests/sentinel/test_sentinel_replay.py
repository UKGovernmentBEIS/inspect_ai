"""Steps rebuilt from a log (`steps_from_events`) equal the steps live, field by field."""

import bisect
import dataclasses
import json
import random
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, cast

import anyio
import pytest
import tenacity
from pydantic import BaseModel, TypeAdapter

from inspect_ai import Task, eval
from inspect_ai._sentinel._integration import (
    EvalInfo,
    MalformedLogError,
    steps_from_events,
)
from inspect_ai._sentinel._steps import ListView, PoolView
from inspect_ai._util._async import tg_collect
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import (
    Agent,
    AgentState,
    agent,
    as_solver,
    as_tool,
    handoff,
    react,
    run,
)
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.approval import Approval, ApprovalPolicy, Approver, approver
from inspect_ai.approval._approval import ApprovalDecision
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
    ModelAPI,
    ModelOutput,
    ModelRefusalError,
    get_model,
    model_origin,
    modelapi,
)
from inspect_ai.model._call_tools import TOOL_CALLS_FAIL_FAST, execute_tools
from inspect_ai.model._providers.mockllm import MockLLM
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
    tool,
)
from inspect_ai.tool._tool import ToolApprovalError, ToolParsingError
from inspect_ai.util import store
from inspect_ai.util._span import span

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
from .test_sentinel_human import Panel, h_ask

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
) -> list["ReplayStep"]:
    """Rebuild the steps of a log that `r7_probe(seen, copies=True)` watched, and compare; then compare those with the steps replayed with the log's origins removed and the turns inferred (`inferred` as for `assert_replay_equals_live`)."""
    assert log.samples
    live = live_steps(log.samples[0], seen)
    replay = replayed(log)
    rebuilt: dict[tuple[str, str], ReplayStep] = {
        (step.stage, step.id): step for step in replay
    }
    assert len(rebuilt) == len(replay)
    assert set(rebuilt) == set(live)
    for key, step in live.items():
        again = rebuilt[key].step
        assert type(again) is type(step), key
        assert rebuilt[key].segment[0] == step.conversation
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
    assert_inferred(log, replay, inferred)
    return replay


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
) -> Agent:
    """A scaffold that declares the host tool as `name` (or calls it through Antigravity's `call_mcp_tool` dispatcher) and runs the call the bridge hands it, after one more model request if `request_before_running`."""

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
        await call_tool(bridge)("host", "addition", arguments)
        return state

    return execute


def test_a_bridged_host_tool_call_has_no_tool_steps() -> None:
    seen: dict[str, Step] = {}
    log = run_logged(
        as_solver(r7_runs_a_bridged_host_tool()),
        outputs(call("mcp__host__addition", x=1, y=1)),
        sentinel=[r7_probe(seen)],
    )
    events = logged_sample(log).events
    [turn] = [e for e in events if isinstance(e, ModelEvent)]
    [ran] = [e for e in events if isinstance(e, ToolEvent)]
    # the host tool ran the model's call, as a native call would
    assert ran.metadata is not None and "bridge" in ran.metadata
    assert [c.id for c in turn.output.message.tool_calls or []] == [ran.id]
    assert ran.error is None
    # the host executor runs no tool stage, so live checked only the generate
    live = [e.stage for e in events if isinstance(e, SentinelEvent)]
    assert live == ["model_input", "model_output"]
    assert [step.stage for step in replayed(log)] == live


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
    """Assert the host tool ran the approved call, and replay gives live's steps; return the approved call."""
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
    assert live == ["model_input", "model_output"]
    expected = [(step.stage, step.id) for step in replayed(log)]
    assert [stage for stage, _ in expected] == live
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
            assert [(s.stage, s.id) for s in replay] == [
                (stage, turn.uuid)
                for turn in turns
                for stage in ["model_input", "model_output"]
            ]
            for step in replay[2:]:
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
            assert len(replay) == 8
            for step in replay:
                decisions = step.step.human_decisions or []
                assert [(d.step_id, d.decided.report.action) for d in decisions] == (
                    []
                    if step.id in (turns[0].uuid, turns[1].uuid)
                    else expected[agents[step.id]]
                ), (inputs, step.stage)
    if not shared_id:
        return
    # recorded outside both agents, the first approval is left unpublished
    outside = [
        e.model_copy(update={"span_id": None}) if e is first else e for e in events
    ]
    replay = replay_inputs(log, outside, "expanded", human_approvers=approvers)
    for step in replay[4:]:
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
            tool_steps = [s for s in replay if s.stage.startswith("tool")]
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


# a log replay cannot read without guessing fails, naming the rule


def test_two_steps_of_a_stage_with_one_id_fail_the_replay() -> None:
    log = run_logged(tool_loop(addition()), agent_model())
    events = logged_sample(log).events
    tool = next(i for i, e in enumerate(events) if isinstance(e, ToolEvent))
    with pytest.raises(MalformedLogError, match="Two tool_call steps"):
        replay_events(log, [*events[: tool + 1], *events[tool - 1 :]])


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
    inputs: str,
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
    replay = steps_from_events(
        messages,
        events,
        pool,
        sample_uuid="sample",
        eval_info=EvalInfo("0.3.277", True),
    )
    tool_steps = [
        step.step
        for step in replay
        if isinstance(step.step, BeforeToolCall | AfterToolCall)
    ]
    assert [step.call.arguments["x"] for step in tool_steps] == [1, 1]
    assert all(type(step.call.arguments["x"]) is int for step in tool_steps)


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
