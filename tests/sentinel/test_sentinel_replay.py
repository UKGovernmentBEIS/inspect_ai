"""Steps rebuilt from a log (`steps_from_events`) equal the steps live, field by field."""

import bisect
import dataclasses
import random
from collections.abc import Callable, Sequence
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import anyio
import pytest
import tenacity
from pydantic import BaseModel

from inspect_ai import Task, eval
from inspect_ai._sentinel._integration import (
    EvalInfo,
    MalformedLogError,
    steps_from_events,
)
from inspect_ai._sentinel._steps import ListView, PoolView
from inspect_ai._util._async import tg_collect
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import Agent, as_solver, as_tool, handoff, react
from inspect_ai.approval import Approval, ApprovalPolicy, Approver, approver
from inspect_ai.approval._approval import ApprovalDecision
from inspect_ai.dataset import Sample
from inspect_ai.event import (
    ApprovalEvent,
    Event,
    ModelEvent,
    SentinelEvent,
    SpanBeginEvent,
    Timeline,
    TimelineEvent,
    TimelineSpan,
    ToolEvent,
)
from inspect_ai.log import EvalLog, EvalSample, read_eval_log
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
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import (
    Tool,
    ToolCall,
    ToolCallContent,
    ToolCallView,
    ToolInfo,
    tool,
)
from inspect_ai.tool._tool import ToolApprovalError
from inspect_ai.util._span import span

from .test_sentinel_dispatch import (
    _RetriedError,
    _RetryingMockLLM,
    addition,
    addition_call,
    addition_raising_viewer,
    agent_model,
    d3_approver,
    d3_edits_a_sent_message_in_place,
    d3_generates_once,
    d3_memory_path_approver,
    d3_modify,
    d3_public_memory_only,
    d3_reject,
    folding,
    ordered_addition,
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
        HumanAnswer,
        MonitorGroup,
        Observation,
        ReplayStep,
        monitor,
    )
else:
    from test_helpers.fake_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        Context,
        HumanAnswer,
        MonitorGroup,
        Observation,
        ReplayStep,
        monitor,
    )

pytestmark = pytest.mark.usefixtures("fake_sentinel")

Step = Any

# what replay cannot give: the untruncated output is not in the log, and a
# tool's viewer, which supplies a view's context, is not either
ABSENT: dict[str, set[str]] = {"AfterToolCall": {"output"}}


@monitor
def r7_probe(seen: dict[str, Step]) -> MonitorGroup:
    """Record every step it is handed, under a token its observation carries."""

    def probe(step: Step) -> Observation:
        token = str(len(seen))
        seen[token] = step
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


# the fields whose messages come from the log's pool, which keeps the first id
# stored for each content: a message sent again under a new id reads back with
# the first, and equal messages in one history are one row, so one id and one
# object (a known difference)
POOLED = {"input", "history"}


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
    **task_kwargs: Any,
) -> list["ReplayStep"]:
    """Run the eval with a probe watching every stage, rebuild its steps from the log, and compare.

    Args:
        solver: The eval's solver.
        model: Its model.
        sentinel: Instances to run after the probe.
        differences: Fields known to differ, as `"stage.field"`, each a known difference of replay.
        sample: The sample to run.
        status: The status the eval ends with.
        **task_kwargs: More `Task` arguments.
    """
    seen: dict[str, Step] = {}
    task = Task(
        dataset=[sample or Sample(input="What is 1 + 1?", target="2")],
        solver=solver,
        sentinel=[r7_probe(seen), *sentinel],
        **task_kwargs,
    )
    log = eval(task, model=model)[0]
    assert log.status == status, log.error
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
            ids = f.name not in POOLED
            assert comparable(ours, ids) == comparable(theirs, ids), f"{key} {f.name}"
    return replay


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
        # known difference: react's submit appends the answer to the assistant
        # message in place once the call has run, so the log holds the edited
        # text that live's tool steps had not yet seen
        differences=["tool_call.message", "tool_result.message"],
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


def test_a_schema_validation_error_replays_as_it_ran() -> None:
    replay = assert_replay_equals_live(
        tool_loop(addition()), outputs(call("addition", x="one", y=1), done())
    )
    assert [step.stage for step in replay if step.stage.startswith("tool")] == [
        "tool_call"
    ]


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


def test_a_message_edited_in_place_after_it_was_sent_is_a_known_difference() -> None:
    # known difference: the log's earlier ModelEvent holds the edited object, so
    # replay has the message once, as edited, where live has both versions
    assert_replay_equals_live(
        d3_edits_a_sent_message_in_place(),
        "mockllm/model",
        differences=["model_input.input", "model_input.history", "model_output.input"]
        + ["model_output.history"],
    )


def memory_call(path: str) -> ModelOutput:
    return call("memory", command="create", path=path, file_text="x")


def test_an_approvers_modified_memory_path_replays_canonical() -> None:
    from inspect_ai.tool import memory

    replay = assert_replay_equals_live(
        tool_loop(memory()),
        outputs(memory_call("/memories/public/note.txt"), done()),
        sentinel=[d3_public_memory_only()],
        approval=[
            ApprovalPolicy(
                d3_memory_path_approver("/memories/public/../secret.txt"), "*"
            )
        ],
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


def run_logged(
    solver: Solver | list[Solver], model: Any, **task_kwargs: Any
) -> EvalLog:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=solver,
        **task_kwargs,
    )
    log = eval(task, model=model)[0]
    assert log.status == "success", log.error
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


def test_a_log_without_origins_is_not_replayed_yet() -> None:
    log = run_logged(tool_loop(addition()), agent_model())
    events = logged_sample(log).events
    for event in events:
        if isinstance(event, ModelEvent):
            event.origin = None
    with pytest.raises(NotImplementedError, match="origin"):
        replay_events(log, events)


def test_a_log_with_message_based_generate_ids_keeps_its_recorded_ids() -> None:
    seen: dict[str, Step] = {}
    log = run_logged(tool_loop(addition()), agent_model(), sentinel=[r7_probe(seen)])
    events = logged_sample(log).events
    # rewrite the generate stages' ids as sentinel 0.1.x recorded them: the
    # last input message's id before, and the output message's id after
    turns = [e for e in events if isinstance(e, ModelEvent)]
    old: dict[str, tuple[str, str]] = {
        turn.uuid or "": (f"{turn.input[-1].id}:old", turn.output.message.id or "")
        for turn in turns
    }
    for event in events:
        if isinstance(event, SentinelEvent) and event.step_id in old:
            before, after = old[event.step_id]
            event.step_id = before if event.stage == "model_input" else after
    replay = replay_events(log, events)
    assert {(s.stage, s.id) for s in replay if s.stage.startswith("model")} == {
        (stage, id)
        for before, after in old.values()
        for stage, id in (("model_input", before), ("model_output", after))
    }


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
        eval_info=EvalInfo(inspect_ai_version=None, sentinel=False),
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


SEQUENCES = {
    "BeforeGenerate": ("history", "agent_messages", "human_decisions"),
    "AfterGenerate": ("history", "agent_messages", "human_decisions"),
    "BeforeToolCall": (
        "history",
        "agent_messages",
        "human_decisions",
        "input",
        "tools",
    ),
    "AfterToolCall": ("history", "agent_messages", "human_decisions", "input", "tools"),
}


def assert_views_share_storage(
    steps: Sequence[Step], pool: Sequence[ChatMessage] | None = None
) -> None:
    """Every step's conversation fields are views of lists the conversation keeps, never copies.

    Per conversation, `history` and `human_decisions` are each backed by one list, and live `agent_messages` by at most two (replay's is None; the opening is replaced once, by the input as sent). The tool stages' `input` and `tools` are the producing model call's own lists, one per assistant message, whatever its calls and stages: live, its `ModelEvent`'s; in replay, rows of the one pool.
    """
    backing: dict[tuple[str, str], set[int]] = {}
    generates = {
        step.output.message.id: step
        for step in steps
        if isinstance(step, AfterGenerate) and step.output.choices
    }
    for step in steps:
        for name in ("history", "agent_messages", "human_decisions"):
            value = getattr(step, name)
            if value is not None:
                assert isinstance(value, ListView), (name, type(value))
                backing.setdefault((step.conversation, name), set()).add(
                    id(value._items)
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
        allowed = 2 if name == "agent_messages" else 1
        assert len(lists) <= allowed, (conversation, name, len(lists))


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
    """Each pool row is keyed once, and the fold's work (comparisons, bisections and index entries) is within a constant of what the log stores; with `doubles`, twice the turns cost at most a little over twice the work."""
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


def log_work(turns: int, monkeypatch: pytest.MonkeyPatch) -> Work:
    from inspect_ai._sentinel import _replay

    log = long_run(turns)
    sample = logged_sample(log)
    events, pool = _replay._condensed(sample.events, [])
    return replay_work(
        monkeypatch,
        sample.messages,
        events,
        pool,
        sample.uuid or "",
        EvalInfo.from_eval(log.eval),
    )


def test_replay_reads_each_pool_row_once_and_folds_linearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_linear(log_work(20, monkeypatch), log_work(40, monkeypatch))


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


def test_overlapping_equal_generates_with_interleaved_retries_are_a_known_difference() -> (
    None
):
    # known difference (P4-F2): a generate's later attempts carry no id, so
    # replay groups them by inference, and two overlapping generates with equal
    # input whose retries interleave are grouped wrongly
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
    assert replay != live


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


@monitor
def r7_counts_tool_calls(seen: list[Any]) -> MonitorGroup:
    async def before_call(context: Context, step: BeforeToolCall) -> Observation | None:
        seen.append(step)
        return None

    return MonitorGroup(before_call)


def test_a_tool_that_raises_tool_approval_error_itself_is_a_known_difference() -> None:
    # known difference: with every instance abstaining, the log of a tool that
    # raises ToolApprovalError itself reads as a call rejected before its step
    # was built, so replay gives it no tool steps
    seen: list[Any] = []
    log = run_logged(
        tool_loop(refuses()),
        outputs(call("refuses"), done()),
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
        eval_info=EvalInfo(inspect_ai_version=None, sentinel=False),
        human_approvers=(approver_name,),
    )
    last = [s for s in replay if s.stage == "model_input"][-1]
    decisions = last.step.human_decisions or []
    assert decisions, [s.stage for s in replay]
    assert decisions[0].decided.report.action == action
    # the person decided before the call ran, so its own result step sees it
    for after in [s for s in replay if s.stage == "tool_result"]:
        assert [d.step_id for d in after.step.human_decisions or []][-1:] == [after.id]


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


def test_a_task_scorer_s_tool_calls_are_replayed() -> None:
    replay = assert_replay_equals_live(
        generate(),
        outputs(done(), call("addition", x=1, y=1)),
        scorer=r7_scores_with_a_tool_loop(),
    )
    assert [s.stage for s in replay if s.stage.startswith("tool")] == [
        "tool_call",
        "tool_result",
    ]


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


@pytest.mark.parametrize("version,truncated", [("0.3.30", None), ("0.3.31", False)])
def test_a_log_from_before_the_record_of_cuts_says_it_cannot_tell(
    version: str, truncated: bool | None
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


def test_a_task_scorer_s_unrecorded_tool_calls_are_replayed() -> None:
    # with every instance abstaining no SentinelEvent records the stage, so
    # replay decides from the producer's region alone
    seen: list[Any] = []
    log = run_logged(
        generate(),
        outputs(done(), call("addition", x=1, y=1)),
        sentinel=[r7_counts_tool_calls(seen)],
        scorer=r7_scores_with_a_tool_loop(),
    )
    assert len(seen) == 1
    assert [s.stage for s in replayed(log) if s.stage == "tool_call"] == ["tool_call"]


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
    replay = assert_replay_equals_live(
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
    )
    assert len([s for s in replay if s.stage == "tool_result"]) == 3


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
