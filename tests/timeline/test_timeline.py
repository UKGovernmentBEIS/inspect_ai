"""Pytest tests for timeline scenarios.

Each test runs a scenario from generate.py and validates the resulting timeline.
"""

from typing import Any, Callable, NamedTuple

import pytest

from inspect_ai import eval
from inspect_ai.event import Timeline, timeline_build
from inspect_ai.event._timeline import TimelineSpan

from .generate import (
    scenario_deep_nesting,
    scenario_deep_utility,
    scenario_handoff_and_as_tool,
    scenario_multi_turn_agent,
    scenario_nested_sub_agent,
    scenario_parallel_collect,
    scenario_parallel_heterogeneous,
    scenario_parallel_with_nesting,
    scenario_primitive_solvers,
    scenario_sequential_and_parallel,
    scenario_sequential_run,
    scenario_simple_agent,
    scenario_utility_agent,
    validate_deep_nesting,
    validate_deep_utility,
    validate_handoff_and_as_tool,
    validate_multi_turn_agent,
    validate_nested_sub_agent,
    validate_parallel_collect,
    validate_parallel_heterogeneous,
    validate_parallel_with_nesting,
    validate_primitive_solvers,
    validate_sequential_and_parallel,
    validate_sequential_run,
    validate_simple_agent,
    validate_utility_agent,
)


def _run_and_validate(
    scenario_fn: Callable[[], tuple[str, Any, Any]],
    validator_fn: Callable[[Timeline], None],
) -> None:
    name, task, model = scenario_fn()
    log = eval(task, model=model, display="none")[0]
    assert log.status == "success", f"{name}: {log.status}"
    assert log.samples and log.samples[0].events, f"{name}: no events"
    events = log.samples[0].events
    timeline = timeline_build(events)
    validator_fn(timeline)


def test_timeline_simple_agent() -> None:
    _run_and_validate(scenario_simple_agent, validate_simple_agent)


def test_timeline_primitive_solvers() -> None:
    _run_and_validate(scenario_primitive_solvers, validate_primitive_solvers)


def test_timeline_multi_turn_agent() -> None:
    _run_and_validate(scenario_multi_turn_agent, validate_multi_turn_agent)


def test_timeline_nested_sub_agent() -> None:
    _run_and_validate(scenario_nested_sub_agent, validate_nested_sub_agent)


def test_timeline_utility_agent() -> None:
    _run_and_validate(scenario_utility_agent, validate_utility_agent)


def test_timeline_sequential_run() -> None:
    _run_and_validate(scenario_sequential_run, validate_sequential_run)


def test_timeline_parallel_collect() -> None:
    _run_and_validate(scenario_parallel_collect, validate_parallel_collect)


def test_timeline_handoff_and_as_tool() -> None:
    _run_and_validate(scenario_handoff_and_as_tool, validate_handoff_and_as_tool)


def test_timeline_deep_nesting() -> None:
    _run_and_validate(scenario_deep_nesting, validate_deep_nesting)


def test_timeline_parallel_with_nesting() -> None:
    _run_and_validate(scenario_parallel_with_nesting, validate_parallel_with_nesting)


def test_timeline_sequential_and_parallel() -> None:
    _run_and_validate(
        scenario_sequential_and_parallel, validate_sequential_and_parallel
    )


def test_timeline_deep_utility() -> None:
    _run_and_validate(scenario_deep_utility, validate_deep_utility)


def test_timeline_parallel_heterogeneous() -> None:
    _run_and_validate(scenario_parallel_heterogeneous, validate_parallel_heterogeneous)


def test_wrap_utility_uuidless_ids_unique() -> None:
    """Wrapper spans for uuid-less (legacy) events get unique deterministic ids.

    The JSON fixtures can't express this case — event parsing auto-assigns
    uuids — so construct the events directly and clear them.
    """
    from pydantic import TypeAdapter

    from inspect_ai.event import Event
    from inspect_ai.event._timeline import (
        TimelineEvent,
        TimelineSpan,
        _Inputs,
        _wrap_utility_events,
    )

    def warmup_event(ts: str) -> Event:
        event: Event = TypeAdapter(Event).validate_python(
            {
                "event": "model",
                "timestamp": ts,
                "completed": ts,
                "model": "mockllm/model",
                "input": [{"role": "user", "content": "warmup"}],
                "tools": [],
                "tool_choice": "none",
                "config": {"max_tokens": 1},
                "output": {
                    "model": "mockllm/model",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "w"},
                            "stop_reason": "max_tokens",
                        }
                    ],
                },
            }
        )
        event.uuid = None
        return event

    span = TimelineSpan(
        id="agent",
        name="agent",
        span_type="agent",
        content=[
            TimelineEvent(event=warmup_event("2026-01-01T00:00:01Z")),
            TimelineEvent(event=warmup_event("2026-01-01T00:00:02Z")),
        ],
    )
    _wrap_utility_events(span, _Inputs([], None))

    wrappers = [item for item in span.content if isinstance(item, TimelineSpan)]
    assert [w.id for w in wrappers] == ["utility-agent-0", "utility-agent-1"]
    assert all(w.utility for w in wrappers)


# nothing quadratic: over a log without origins, the continuity rule and the
# bridge flow's agent results read and fingerprint a constant number of
# messages per model call, so twice the turns cost twice the work


class _CountingList(list[Any]):
    reads = 0

    def __getitem__(self, index: Any) -> Any:
        _CountingList.reads += 1
        return super().__getitem__(index)

    def __iter__(self) -> Any:
        for item in super().__iter__():
            _CountingList.reads += 1
            yield item


def _bridged_turns(turns: int, compaction: bool) -> tuple[list[Any], list[Any]]:
    """A main agent with no origins whose turns each hand a task to a bridged sub-agent (`agent-{call id}`) beside a plain tool call, with `compaction` a summary compaction halfway: events whose inputs are ranges of the returned pool."""
    from inspect_ai.event import (
        CompactionEvent,
        ModelEvent,
        SpanBeginEvent,
        SpanEndEvent,
        ToolEvent,
    )
    from inspect_ai.event._pool import _compress_refs
    from inspect_ai.model import (
        ChatCompletionChoice,
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageTool,
        ChatMessageUser,
        GenerateConfig,
        ModelOutput,
    )
    from inspect_ai.tool import ToolCall

    pool: list[Any] = [
        ChatMessageSystem(content="You are the main agent."),
        ChatMessageUser(content="Do the tasks."),
    ]
    events: list[Any] = [
        SpanBeginEvent(id="solvers", name="solvers", type="solvers"),
        SpanBeginEvent(id="main", name="main", type="agent", parent_id="solvers"),
    ]

    def add(message: Any) -> int:
        pool.append(message)
        return len(pool) - 1

    def model(span: str, rows: list[int], output: Any) -> None:
        events.append(
            ModelEvent(
                span_id=span,
                model="mockllm/model",
                input=[],
                input_refs=_compress_refs(rows),
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput(
                    model="mockllm/model",
                    choices=[ChatCompletionChoice(message=output, stop_reason="stop")],
                ),
            )
        )

    history = [0, 1]
    for turn in range(turns):
        if compaction and turn == turns // 2:
            summary = ChatMessageAssistant(content=f"Summary of {turn} turns.")
            model(
                "main", [*history, add(ChatMessageUser(content="Summarize."))], summary
            )
            events.append(CompactionEvent(span_id="main", type="summary"))
            history = [0, add(ChatMessageUser(content=summary.text))]
        task = ToolCall(id=f"task{turn}", function="task", arguments={"n": turn})
        plain = ToolCall(id=f"add{turn}", function="addition", arguments={"n": turn})
        output = ChatMessageAssistant(content="", tool_calls=[task, plain])
        model("main", history, output)
        history = [*history, add(output)]
        sub = f"agent-{task.id}"
        events.append(
            SpanBeginEvent(id=sub, name="sub", type="agent", parent_id="main")
        )
        model(
            sub,
            [
                add(ChatMessageSystem(content="You are a sub-agent.")),
                add(ChatMessageUser(content=f"Task {turn}.")),
            ],
            ChatMessageAssistant(content=f"result {turn}"),
        )
        events.append(SpanEndEvent(id=sub))
        events.append(
            ToolEvent(id=plain.id, function="addition", arguments={}, span_id="main")
        )
        history.append(
            add(ChatMessageTool(content=f"result {turn}", tool_call_id=task.id))
        )
        history.append(add(ChatMessageTool(content="2", tool_call_id=plain.id)))
    model("main", history, ChatMessageAssistant(content="done"))
    events += [SpanEndEvent(id="main"), SpanEndEvent(id="solvers")]
    return events, pool


def _model_events(span: TimelineSpan) -> list[Any]:
    from inspect_ai.event import ModelEvent
    from inspect_ai.event._timeline import TimelineEvent

    return [
        item.event
        for item in span.content
        if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent)
    ]


class _TimelineWork(NamedTuple):
    reads: int
    """Messages read from inputs (pool rows, or entries of expanded inputs)."""
    entries: int
    """Entries of the model inputs, expanded."""
    fingerprints: int
    """Messages fingerprinted."""
    compared: int
    """Continuity's comparisons."""


def _timeline_work(
    turns: int, pooled: bool, compaction: bool, monkeypatch: pytest.MonkeyPatch
) -> _TimelineWork:
    from inspect_ai._util.hash import mm3_hash
    from inspect_ai.event import ModelEvent
    from inspect_ai.event import _timeline as timeline
    from inspect_ai.event._pool import resolve_model_event_inputs

    events, pool = _bridged_turns(turns, compaction)
    entries = sum(
        end - start
        for e in events
        if isinstance(e, ModelEvent)
        for start, end in e.input_refs or []
    )
    if not pooled:
        events = [
            e.model_copy(update={"input": _CountingList(e.input)})
            if isinstance(e, ModelEvent)
            else e
            for e in resolve_model_event_inputs(events, pool)
        ]
    fingerprints = compared = 0
    continues = timeline._Continuity._continues

    def counting_hash(text: str) -> str:
        nonlocal fingerprints
        fingerprints += 1
        return mm3_hash(text)

    def counting_continues(self: Any, call: Any, earlier: Any) -> bool:
        nonlocal compared
        compared += 1
        return continues(self, call, earlier)

    _CountingList.reads = 0
    with monkeypatch.context() as patch:
        patch.setattr("inspect_ai.event._timeline.mm3_hash", counting_hash)
        patch.setattr(timeline._Continuity, "_continues", counting_continues)
        built = timeline._timeline_build(
            events, message_pool=_CountingList(pool) if pooled else None
        )
    main = built.root
    results = {
        item.id: item.agent_result
        for item in main.content
        if isinstance(item, TimelineSpan) and item.id.startswith("agent-")
    }
    # the result of the task before a compaction reaches only the summary
    # call, which is utility
    assert results == {
        f"agent-task{turn}": None
        if compaction and turn == turns // 2 - 1
        else f"result {turn}"
        for turn in range(turns)
    }
    utility = [
        event.output.message.text
        for item in main.content
        if isinstance(item, TimelineSpan) and item.id.startswith("utility-")
        for event in _model_events(item)
    ]
    # the summary call is the only one of the main agent's that is not a turn
    assert utility == ([f"Summary of {turns // 2} turns."] if compaction else [])
    return _TimelineWork(_CountingList.reads, entries, fingerprints, compared)


@pytest.mark.parametrize(
    "pooled,compaction", [(True, True), (True, False), (False, False)]
)
def test_continuity_and_agent_results_are_linear(
    pooled: bool, compaction: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    small = _timeline_work(50, pooled, compaction, monkeypatch)
    large = _timeline_work(100, pooled, compaction, monkeypatch)
    for field in ("reads", "fingerprints", "compared"):
        assert getattr(large, field) <= 2.2 * getattr(small, field) + 10, (
            field,
            small,
            large,
        )
    # a handful of messages per model call (each turn makes two)
    assert large.reads <= 10 * 2 * 100


def test_an_agent_result_that_never_follows_its_call_reads_expanded_inputs_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # expanded inputs have no ranges to look a result up in, so once a result
    # is not where its call puts it each later input is read once, for every
    # span still waiting: within the entries the inputs hold, not a scan per
    # span
    work = _timeline_work(100, False, True, monkeypatch)
    assert work.reads <= work.entries + 10 * 2 * 100
    assert (work.fingerprints, work.compared) == (100, 100)


def test_a_fork_at_the_end_goes_to_the_call_in_the_final_messages() -> None:
    import json
    from pathlib import Path

    from pydantic import TypeAdapter

    from inspect_ai.event import Event, ModelEvent
    from inspect_ai.event._timeline import _timeline_build

    fixture = Path(__file__).parent / "fixtures/events/continuity_fork_at_end.json"
    events = TypeAdapter(list[Event]).validate_python(
        json.loads(fixture.read_text())["events"]
    )
    m2 = next(e for e in events if isinstance(e, ModelEvent) and e.uuid == "m2")
    # the main agent's final messages carry on the earlier call of the fork
    final = [*m2.input, m2.output.message]
    root = _timeline_build(events, final_messages=final).root
    utility = [
        event.uuid
        for item in root.content
        if isinstance(item, TimelineSpan) and item.utility
        for event in _model_events(item)
    ]
    assert utility == ["m3"]
