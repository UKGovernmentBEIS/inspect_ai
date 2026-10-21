"""Steps rebuilt from a log (`steps_from_events`) equal the steps live, field by field."""

import dataclasses
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel

from inspect_ai import Task, eval
from inspect_ai._sentinel._replay import EvalInfo, steps_from_events
from inspect_ai.dataset import Sample
from inspect_ai.event import SentinelEvent
from inspect_ai.log import EvalLog, EvalSample, read_eval_log
from inspect_ai.model import ChatMessage, ModelOutput, get_model
from inspect_ai.solver import Solver, generate, use_tools

from .test_sentinel_dispatch import addition

if TYPE_CHECKING:
    from inspect_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        Context,
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


def live_steps(sample: EvalSample, seen: dict[str, Step]) -> dict[tuple[str, str], Step]:
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
        return {f.name: comparable(getattr(value, f.name)) for f in dataclasses.fields(value)}
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
    **task_kwargs: Any,
) -> list["ReplayStep"]:
    """Run the eval with a probe watching every stage, rebuild its steps from the log, and compare.

    Args:
        solver: The eval's solver.
        model: Its model.
        sentinel: Instances to run after the probe.
        differences: Fields known to differ, as `"stage.field"`, each a known difference of replay.
        sample: The sample to run.
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
    assert log.samples
    live = live_steps(log.samples[0], seen)
    replay = replayed(log)
    rebuilt = {(step.stage, step.id): step for step in replay}
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
    return ModelOutput.for_tool_call("mockllm/model", tool_name=name, tool_arguments=arguments)


def done(content: str = "done") -> ModelOutput:
    return ModelOutput.from_content("mockllm/model", content=content)


def test_a_tool_loop_replays_as_it_ran() -> None:
    assert_replay_equals_live(
        [use_tools(addition()), generate()],
        outputs(call("addition", x=1, y=1), call("addition", x=2, y=2), done()),
    )
