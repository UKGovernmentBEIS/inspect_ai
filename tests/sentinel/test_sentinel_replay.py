"""Steps rebuilt from a log (`steps_from_events`) equal the steps live, field by field."""

import dataclasses
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import anyio
import pytest
import tenacity
from pydantic import BaseModel

from inspect_ai import Task, eval
from inspect_ai._sentinel._replay import EvalInfo, MalformedLogError, steps_from_events
from inspect_ai._util._async import tg_collect
from inspect_ai.agent import Agent, as_solver, as_tool, handoff, react
from inspect_ai.approval import ApprovalPolicy
from inspect_ai.dataset import Sample
from inspect_ai.event import (
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
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    get_model,
    modelapi,
)
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import Tool, ToolCall, ToolInfo, tool
from inspect_ai.util._span import span

from .test_sentinel_dispatch import (
    _RetriedError,
    _RetryingMockLLM,
    addition,
    addition_call,
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


def comparable(value: Any) -> Any:
    """A value with message ids left out: the log's pool keeps the first id stored for each content, so a message sent again under a new id reads back with the first."""
    if isinstance(value, BaseModel) and hasattr(value, "role"):
        return (type(value).__name__, value.model_dump(exclude={"id"}))
    if isinstance(value, BaseModel):
        return value.model_dump()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: comparable(getattr(value, f.name))
            for f in dataclasses.fields(value)
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [comparable(item) for item in value]
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items()}
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
            if f.name == "view":
                ours, theirs = ours.call, theirs.call
            assert comparable(ours) == comparable(theirs), f"{key} {f.name}"
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
            # the hook and the provisional opening; the log has them as sent
            differences=["model_input.input", "model_input.agent_messages"],
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
        + ["model_output.history", "model_input.agent_messages"]
        + ["model_output.agent_messages"],
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


def copied_into_steps(steps: Sequence[Step]) -> int:
    """Elements a builder copied into the steps' conversation fields: any list or tuple there is a copy."""
    copied = 0
    for step in steps:
        for name in SEQUENCES[type(step).__name__]:
            value = getattr(step, name)
            if isinstance(value, list | tuple):
                copied += len(value)
    return copied


@pytest.mark.parametrize("turns", [10, 20])
def test_live_steps_copy_nothing_of_the_conversation(turns: int) -> None:
    seen: dict[str, Step] = {}
    log = long_run(turns, seen)
    assert log.samples
    assert len(seen) > 4 * turns
    assert copied_into_steps(list(seen.values())) == 0


def replay_work(
    turns: int, monkeypatch: pytest.MonkeyPatch
) -> tuple[int, int, int, int]:
    """Pool rows keyed, positions the fold visited, pool size and steps for a run of `turns`."""
    from inspect_ai._sentinel import _replay, _steps

    log = long_run(turns)
    sample = logged_sample(log)
    keyed = visited = 0
    content_key = _steps.content_key
    key = _replay._PooledInput.key

    def counting_content_key(message: Any) -> str:
        nonlocal keyed
        keyed += 1
        return content_key(message)

    def counting_key(self: Any, position: int) -> str:
        nonlocal visited
        visited += 1
        return key(self, position)

    events, pool = _replay._condensed(sample.events, [])
    monkeypatch.setattr(_replay, "content_key", counting_content_key)
    monkeypatch.setattr(_replay._PooledInput, "key", counting_key)
    replay = steps_from_events(
        sample.messages,
        events,
        pool,
        sample_uuid=sample.uuid or "",
        eval_info=EvalInfo.from_eval(log.eval),
    )
    assert any(step.segment[1] for step in replay), "the run has a compaction"
    assert copied_into_steps([step.step for step in replay]) == 0
    return keyed, visited, len(pool), len(replay)


def test_replay_reads_each_pool_row_once_and_folds_linearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyed, visited, pool, steps = replay_work(20, monkeypatch)
    keyed2, visited2, pool2, steps2 = replay_work(40, monkeypatch)
    assert keyed <= pool and keyed2 <= pool2
    assert steps2 <= 2.2 * steps
    assert visited2 <= 2.2 * visited, (visited, visited2)


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
