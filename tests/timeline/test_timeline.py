"""Pytest tests for timeline scenarios.

Each test runs a scenario from generate.py and validates the resulting timeline.
"""

from typing import Any, Callable, NamedTuple

import pytest

from inspect_ai import eval
from inspect_ai.event import Timeline, timeline_build
from inspect_ai.event._timeline import TimelineSpan, _timeline_build

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
    looked_up: int
    """Fingerprints continuity looked up."""


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
    fingerprints = looked_up = 0
    fingerprint = timeline._Inputs.fingerprint

    def counting_hash(text: str) -> str:
        nonlocal fingerprints
        fingerprints += 1
        return mm3_hash(text)

    def counting_fingerprint(self: Any, message: Any) -> Any:
        nonlocal looked_up
        looked_up += 1
        return fingerprint(self, message)

    _CountingList.reads = 0
    with monkeypatch.context() as patch:
        patch.setattr("inspect_ai.event._timeline.mm3_hash", counting_hash)
        patch.setattr(timeline._Inputs, "fingerprint", counting_fingerprint)
        built = timeline._timeline_build(
            events,
            message_pool=_CountingList(pool) if pooled else None,
            continuity=True,
        )
    main = built.root
    results = {
        item.id: item.agent_result
        for item in main.content
        if isinstance(item, TimelineSpan) and item.id.startswith("agent-")
    }
    # the result of the task before a compaction reaches only the summary
    # call, which is utility, and is kept (Ransom's review B3)
    assert results == {f"agent-task{turn}": f"result {turn}" for turn in range(turns)}
    utility = [
        event.output.message.text
        for item in main.content
        if isinstance(item, TimelineSpan) and item.id.startswith("utility-")
        for event in _model_events(item)
    ]
    # the summary call is the only one of the main agent's that is not a turn
    assert utility == ([f"Summary of {turns // 2} turns."] if compaction else [])
    return _TimelineWork(_CountingList.reads, entries, fingerprints, looked_up)


@pytest.mark.parametrize(
    "pooled,compaction", [(True, True), (True, False), (False, False)]
)
def test_continuity_and_agent_results_are_linear(
    pooled: bool, compaction: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    small = _timeline_work(50, pooled, compaction, monkeypatch)
    large = _timeline_work(100, pooled, compaction, monkeypatch)
    for field in ("reads", "fingerprints", "looked_up"):
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
    # each call fingerprints one new message and looks up a few
    assert work.fingerprints <= 2 * 100 + 10
    assert work.looked_up <= 8 * 2 * 100


def _reused_bridge_id() -> list[Any]:
    """Two bridge tasks with one tool call id, the second's next input holding both results."""
    from inspect_ai.event import ModelEvent, SpanBeginEvent, SpanEndEvent
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

    def model(span: str, input: list[Any], output: Any) -> ModelEvent:
        return ModelEvent(
            span_id=span,
            model="mockllm/model",
            input=input,
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(
                model="mockllm/model",
                choices=[ChatCompletionChoice(message=output, stop_reason="stop")],
            ),
        )

    def task() -> ChatMessageAssistant:
        call = ToolCall(id="task", function="task", arguments={})
        return ChatMessageAssistant(content="", tool_calls=[call])

    def sub(result: str) -> list[Any]:
        return [
            SpanBeginEvent(id="agent-task", name="sub", type="agent", parent_id="main"),
            model(
                "agent-task",
                [ChatMessageUser(content="Do the task.")],
                ChatMessageAssistant(content=result),
            ),
            SpanEndEvent(id="agent-task"),
        ]

    history: list[Any] = [
        ChatMessageSystem(content="You are the main agent."),
        ChatMessageUser(content="Go."),
    ]
    first, second = task(), task()
    events: list[Any] = [SpanBeginEvent(id="main", name="main", type="agent")]
    events += [model("main", list(history), first), *sub("earlier result")]
    history += [first, ChatMessageTool(content="earlier result", tool_call_id="task")]
    events += [model("main", list(history), second), *sub("new result")]
    history += [second, ChatMessageTool(content="new result", tool_call_id="task")]
    events += [
        model("main", list(history), ChatMessageAssistant(content="done")),
        SpanEndEvent(id="main"),
    ]
    return events


@pytest.mark.parametrize("pooled", [False, True])
def test_a_reused_bridge_call_id_keeps_each_task_s_result(pooled: bool) -> None:
    # Ransom's fifth review B1: the later task's result is the last in the
    # next input, as on main
    from inspect_ai.log import condense_events

    events = _reused_bridge_id()
    if pooled:
        condensed, data = condense_events(events)
        root = _timeline_build(condensed, message_pool=data["messages"]).root
    else:
        root = timeline_build(events).root
    results: list[str | None] = []

    def walk(span: TimelineSpan) -> None:
        for item in span.content:
            if isinstance(item, TimelineSpan):
                if item.id == "agent-task":
                    results.append(item.agent_result)
                walk(item)

    walk(root)
    assert results == ["earlier result", "new result"]


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
    root = _timeline_build(events, final_messages=final, continuity=True).root
    utility = [
        event.uuid
        for item in root.content
        if isinstance(item, TimelineSpan) and item.utility
        for event in _model_events(item)
    ]
    assert utility == ["m3"]


def _wide_fork(forks: int) -> list[Any]:
    """A turn, `forks` calls that all continue it with outputs of their own, then a call that carries on the first of them, with no origins."""
    from inspect_ai.event import ModelEvent, SpanBeginEvent, SpanEndEvent
    from inspect_ai.model import (
        ChatCompletionChoice,
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageUser,
        GenerateConfig,
        ModelOutput,
    )

    def model(uuid: str, input: list[Any], output: Any) -> ModelEvent:
        return ModelEvent(
            uuid=uuid,
            span_id="main",
            model="mockllm/model",
            input=input,
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(
                model="mockllm/model",
                choices=[ChatCompletionChoice(message=output, stop_reason="stop")],
            ),
        )

    opening = [
        ChatMessageSystem(content="You are the main agent."),
        ChatMessageUser(content="Pick a number."),
    ]
    first = ChatMessageAssistant(content="Thinking.")
    asked = [*opening, first, ChatMessageUser(content="Go on.")]
    tries = [ChatMessageAssistant(content=f"Try {n}.") for n in range(forks)]
    return [
        SpanBeginEvent(id="main", name="main", type="agent"),
        model("m0", opening, first),
        *[model(f"f{n}", asked, tries[n]) for n in range(forks)],
        model("last", [*asked, tries[0], ChatMessageUser(content="And?")], first),
        SpanEndEvent(id="main"),
    ]


@pytest.mark.parametrize("forks", [5, 50])
def test_a_fork_carried_on_is_the_turn_however_many_alternatives_it_has(
    forks: int,
) -> None:
    [main] = [
        item
        for item in _timeline_build(_wide_fork(forks), continuity=True).root.content
        if isinstance(item, TimelineSpan)
    ]
    utility = [
        event.uuid
        for item in main.content
        if isinstance(item, TimelineSpan) and item.utility
        for event in _model_events(item)
    ]
    assert utility == [f"f{n}" for n in range(1, forks)]


def test_a_wide_fork_s_lookups_are_linear(monkeypatch: pytest.MonkeyPatch) -> None:
    from inspect_ai.event import _timeline as timeline

    fingerprint = timeline._Inputs.fingerprint

    def looked_up(forks: int) -> int:
        count = 0

        def counting(self: Any, message: Any) -> Any:
            nonlocal count
            count += 1
            return fingerprint(self, message)

        with monkeypatch.context() as patch:
            patch.setattr(timeline._Inputs, "fingerprint", counting)
            timeline._timeline_build(_wide_fork(forks), continuity=True)
        return count

    small, large = looked_up(100), looked_up(200)
    assert large <= 2.2 * small + 10, (small, large)


def _plain_model(uuid: str, input: list[Any], output: Any) -> Any:
    from inspect_ai.event import ModelEvent
    from inspect_ai.model import ChatCompletionChoice, GenerateConfig, ModelOutput

    return ModelEvent(
        uuid=uuid,
        span_id="main",
        model="mockllm/model",
        input=input,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(
            model="mockllm/model",
            choices=[ChatCompletionChoice(message=output, stop_reason="stop")],
        ),
    )


def _moves_past_side_calls(segments: int) -> list[Any]:
    """`segments` times: the agent rebuilds its input, makes four side calls with inputs of four other lengths, then carries on the rebuilt call; no origins."""
    from inspect_ai.event import SpanBeginEvent, SpanEndEvent
    from inspect_ai.model import (
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageUser,
    )

    system = ChatMessageSystem(content="You are the main agent.")
    events: list[Any] = [SpanBeginEvent(id="main", name="main", type="agent")]
    for k in range(segments):
        rebuilt = [system, ChatMessageUser(content=f"Earlier, part {k}.")]
        answer = ChatMessageAssistant(content=f"Part {k}.")
        events.append(_plain_model(f"r{k}", rebuilt, answer))
        for n in range(4):
            notes = [ChatMessageUser(content=f"Note {k}.{i}.") for i in range(n + 2)]
            side = ChatMessageAssistant(content="noted")
            events.append(_plain_model(f"s{k}.{n}", [system, *notes], side))
        go_on = ChatMessageUser(content="Go on.")
        carried = ChatMessageAssistant(content=f"Done {k}.")
        events.append(_plain_model(f"m{k}", [*rebuilt, answer, go_on], carried))
    events.append(SpanEndEvent(id="main"))
    return events


def _looked_up(events: list[Any], monkeypatch: pytest.MonkeyPatch) -> tuple[int, Any]:
    from inspect_ai.event import _timeline as timeline

    fingerprint = timeline._Inputs.fingerprint
    count = 0

    def counting(self: Any, message: Any) -> Any:
        nonlocal count
        count += 1
        return fingerprint(self, message)

    with monkeypatch.context() as patch:
        patch.setattr(timeline._Inputs, "fingerprint", counting)
        built = timeline._timeline_build(events, continuity=True)
    return count, built


def test_moving_past_side_calls_of_many_lengths_is_linear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small, _ = _looked_up(_moves_past_side_calls(50), monkeypatch)
    large, built = _looked_up(_moves_past_side_calls(100), monkeypatch)
    assert large <= 2.2 * small + 10, (small, large)
    [main] = [item for item in built.root.content if isinstance(item, TimelineSpan)]
    utility = {
        event.uuid
        for item in main.content
        if isinstance(item, TimelineSpan) and item.utility
        for event in _model_events(item)
    }
    assert utility == {f"s{k}.{n}" for k in range(100) for n in range(4)}


def test_calls_that_continue_nothing_cost_at_most_their_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the costly case of looking up every open input length: a long run of
    # calls none of which continues another, each with an input of a new
    # length, is looked up at every shorter open length, which reads at most
    # the positions the inputs hold
    from inspect_ai.event import SpanBeginEvent, SpanEndEvent
    from inspect_ai.model import ChatMessageAssistant, ChatMessageUser

    notes = [ChatMessageUser(content=f"Note {i}.") for i in range(200)]
    calls = [
        _plain_model(f"c{n}", notes[: n + 1], ChatMessageAssistant(content=f"{n}"))
        for n in range(200)
    ]
    events = [
        SpanBeginEvent(id="main", name="main", type="agent"),
        *calls,
        SpanEndEvent(id="main"),
    ]
    looked_up, _ = _looked_up(events, monkeypatch)
    entries = sum(len(call.input) for call in calls)
    assert looked_up <= entries + 2 * len(calls)


def _pooled_lengths(calls: int) -> tuple[list[Any], list[Any]]:
    """`calls` model calls with inputs of lengths 1 to `calls`, each one range of a shared pool, none continuing another; no origins."""
    from inspect_ai.event import ModelEvent, SpanBeginEvent, SpanEndEvent
    from inspect_ai.model import (
        ChatCompletionChoice,
        ChatMessageAssistant,
        ChatMessageUser,
        GenerateConfig,
        ModelOutput,
    )

    pool = [ChatMessageUser(content=f"Note {n}.") for n in range(calls)]
    events: list[Any] = [SpanBeginEvent(id="main", name="main", type="agent")]
    for n in range(1, calls + 1):
        events.append(
            ModelEvent(
                span_id="main",
                model="mockllm/model",
                input=[],
                input_refs=[(0, n)],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput(
                    model="mockllm/model",
                    choices=[
                        ChatCompletionChoice(
                            message=ChatMessageAssistant(content=f"Answer {n}."),
                            stop_reason="stop",
                        )
                    ],
                ),
            )
        )
    events.append(SpanEndEvent(id="main"))
    return events, pool


def test_calls_of_many_lengths_in_a_pooled_log_are_looked_up_in_linear_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the log driver's timeline reads inputs as pool ranges, so its lookups
    # are counted against the log as stored (pool rows and ranges), not the
    # expanded inputs, which are quadratic here
    from bisect import bisect_left

    from inspect_ai.event import _timeline as timeline

    fingerprint = timeline._Inputs.fingerprint

    def work(calls: int) -> int:
        count = 0

        def counting_fingerprint(self: Any, message: Any) -> Any:
            nonlocal count
            count += 1
            return fingerprint(self, message)

        def counting_bisect(*args: Any) -> int:
            nonlocal count
            count += 1
            return bisect_left(*args)

        events, pool = _pooled_lengths(calls)
        with monkeypatch.context() as patch:
            patch.setattr(timeline._Inputs, "fingerprint", counting_fingerprint)
            patch.setattr("inspect_ai.event._timeline.bisect_left", counting_bisect)
            timeline._timeline_build(events, message_pool=pool, continuity=True)
        stored = len(pool) + 2 * calls  # pool rows, one range and one output each
        assert count <= 4 * stored, (count, stored)
        return count

    small, large = work(200), work(400)
    assert large <= 2.2 * small + 10, (small, large)


def _summarized_turns(turns: int) -> tuple[list[Any], list[Any]]:
    """A tool loop with no origins, its summary call and summary compaction every four turns, the next input holding the summary wrapped as Inspect wraps it: events whose inputs are ranges of the returned pool."""
    from inspect_ai.event import (
        CompactionEvent,
        ModelEvent,
        SpanBeginEvent,
        SpanEndEvent,
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
        ChatMessageUser(content="Add up the numbers."),
    ]
    events: list[Any] = [SpanBeginEvent(id="main", name="main", type="agent")]

    def add(message: Any) -> int:
        pool.append(message)
        return len(pool) - 1

    def model(uuid: str, rows: list[int], output: Any) -> None:
        events.append(
            ModelEvent(
                uuid=uuid,
                span_id="main",
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
        if turn and turn % 4 == 0:
            text = (
                f"<analysis>Turns to {turn}.</analysis>\n<summary>Sum {turn}.</summary>"
            )
            model(
                f"sm{turn}",
                [*history, add(ChatMessageUser(content="Summarize."))],
                ChatMessageAssistant(content=text),
            )
            events.append(CompactionEvent(span_id="main", type="summary"))
            wrapped = f"[CONTEXT COMPACTION SUMMARY]\n\n<summary>Sum {turn}.</summary>"
            history = [0, 1, add(ChatMessageUser(content=wrapped))]
        call = ToolCall(id=f"c{turn}", function="add", arguments={"n": turn})
        output = ChatMessageAssistant(content="", tool_calls=[call])
        model(f"m{turn}", history, output)
        history = [
            *history,
            add(output),
            add(ChatMessageTool(content="ok", tool_call_id=call.id)),
        ]
    model("last", history, ChatMessageAssistant(content="done"))
    events.append(SpanEndEvent(id="main"))
    return events, pool


def test_summary_compactions_are_settled_in_linear_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.event import _timeline as timeline

    fingerprint = timeline._Inputs.fingerprint

    def work(turns: int) -> int:
        count = 0

        def counting(self: Any, message: Any) -> Any:
            nonlocal count
            count += 1
            return fingerprint(self, message)

        events, pool = _summarized_turns(turns)
        counted = _CountingList(pool)
        _CountingList.reads = 0
        with monkeypatch.context() as patch:
            patch.setattr(timeline._Inputs, "fingerprint", counting)
            built = timeline._timeline_build(
                events, message_pool=counted, continuity=True
            )
        [main] = [item for item in built.root.content if isinstance(item, TimelineSpan)]
        utility = {
            event.uuid
            for item in main.content
            if isinstance(item, TimelineSpan) and item.utility
            for event in _model_events(item)
        }
        assert utility == {f"sm{turn}" for turn in range(4, turns, 4)}
        return count + _CountingList.reads

    small, large = work(100), work(200)
    assert large <= 2.2 * small + 10, (small, large)


def _open_at_summary(calls: int) -> tuple[list[Any], list[Any]]:
    """With no origins: `calls` side calls none continuing another, a summary call, a summary compaction, and a call whose input holds `calls` facts and the summary: events whose inputs are ranges of the returned pool."""
    from inspect_ai.event import (
        CompactionEvent,
        ModelEvent,
        SpanBeginEvent,
        SpanEndEvent,
    )
    from inspect_ai.model import (
        ChatCompletionChoice,
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageUser,
        GenerateConfig,
        ModelOutput,
    )

    pool: list[Any] = [
        ChatMessageSystem(content="You are the main agent."),
        ChatMessageUser(content="Summarize."),
        ChatMessageUser(content="[COMPACTED] Facts so far."),
        *[ChatMessageUser(content=f"Note {n}.") for n in range(calls)],
        *[ChatMessageUser(content=f"Fact {n}.") for n in range(calls)],
    ]
    events: list[Any] = [SpanBeginEvent(id="main", name="main", type="agent")]

    def model(uuid: str, refs: list[tuple[int, int]], text: str) -> None:
        events.append(
            ModelEvent(
                uuid=uuid,
                span_id="main",
                model="mockllm/model",
                input=[],
                input_refs=refs,
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput(
                    model="mockllm/model",
                    choices=[
                        ChatCompletionChoice(
                            message=ChatMessageAssistant(content=text),
                            stop_reason="stop",
                        )
                    ],
                ),
            )
        )

    for n in range(calls):
        model(f"s{n}", [(0, 1), (3 + n, 4 + n)], f"Side {n}.")
    model("sm", [(0, 2)], "Facts so far.")
    events.append(CompactionEvent(span_id="main", type="summary"))
    model("m", [(0, 1), (3 + calls, 3 + 2 * calls), (2, 3)], "Done.")
    events.append(SpanEndEvent(id="main"))
    return events, pool


def test_a_summary_compaction_reads_the_next_input_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # delta review d1: every call open at the compaction was looked for in
    # the next input, calls times its messages
    from inspect_ai.event import _timeline as timeline

    fingerprint = timeline._Inputs.fingerprint

    def work(calls: int) -> int:
        count = 0

        def counting(self: Any, message: Any) -> Any:
            nonlocal count
            count += 1
            return fingerprint(self, message)

        events, pool = _open_at_summary(calls)
        counted = _CountingList(pool)
        _CountingList.reads = 0
        with monkeypatch.context() as patch:
            patch.setattr(timeline._Inputs, "fingerprint", counting)
            built = timeline._timeline_build(
                events, message_pool=counted, continuity=True
            )
        [main] = [item for item in built.root.content if isinstance(item, TimelineSpan)]
        utility = {
            event.uuid
            for item in main.content
            if isinstance(item, TimelineSpan) and item.utility
            for event in _model_events(item)
        }
        assert utility == {"sm"}
        return count + _CountingList.reads

    small, large = work(200), work(400)
    assert large <= 2.2 * small + 10, (small, large)


def test_a_row_set_counts_and_lists_rows_by_interval() -> None:
    import random

    from inspect_ai.event._timeline import _RowSet

    chooser = random.Random(7)
    for _ in range(300):
        size = chooser.randint(1, 60)
        rows = chooser.sample(range(size), chooser.randint(0, size))
        found = _RowSet(size)
        for row in rows:
            found.add(row)
        begin, end = sorted(chooser.sample(range(size + 1), 2))
        expected = sorted(row for row in rows if begin <= row < end)
        assert found.count(begin, end) == len(expected)
        assert list(found.between(begin, end)) == expected


def _shared_outputs(calls: int, interleaved: bool) -> tuple[list[Any], list[Any]]:
    """`calls` model calls with no origins, none continuing another, all answering "ok", with a pool holding `calls` rows of "ok" told apart by metadata: apart from the inputs, or with `interleaved` between the inputs' notes, never where an open call's output would be."""
    from inspect_ai.event import ModelEvent, SpanBeginEvent, SpanEndEvent
    from inspect_ai.model import (
        ChatCompletionChoice,
        ChatMessageAssistant,
        ChatMessageUser,
        GenerateConfig,
        ModelOutput,
    )

    notes = [ChatMessageUser(content=f"Note {n}.") for n in range(calls)]
    oks = [ChatMessageAssistant(content="ok", metadata={"n": n}) for n in range(calls)]
    pool: list[Any] = (
        [m for pair in zip(notes, oks) for m in pair] if interleaved else notes + oks
    )
    events: list[Any] = [SpanBeginEvent(id="main", name="main", type="agent")]
    for n in range(1, calls + 1):
        events.append(
            ModelEvent(
                span_id="main",
                model="mockllm/model",
                input=[],
                # interleaved: notes at even rows, and an input of even length
                # 2n puts each open call's output position on a note
                input_refs=[(0, 2 * n if interleaved else n)],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput(
                    model="mockllm/model",
                    choices=[
                        ChatCompletionChoice(
                            message=ChatMessageAssistant(content="ok"),
                            stop_reason="stop",
                        )
                    ],
                ),
            )
        )
    events.append(SpanEndEvent(id="main"))
    return events, pool


def _pooled_work(
    events: list[Any], pool: list[Any], monkeypatch: pytest.MonkeyPatch
) -> int:
    """Fingerprints, bisections, sorted inserts and row-set steps while building."""
    from bisect import bisect_left, insort

    from inspect_ai.event import _timeline as timeline

    count = 0

    def counted(function: Any) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            nonlocal count
            count += 1
            return function(*args, **kwargs)

        return call

    with monkeypatch.context() as patch:
        patch.setattr(
            timeline._Inputs, "fingerprint", counted(timeline._Inputs.fingerprint)
        )
        patch.setattr("inspect_ai.event._timeline.bisect_left", counted(bisect_left))
        patch.setattr("inspect_ai.event._timeline.insort", counted(insort))
        row_set = getattr(timeline, "_RowSet", None)
        for name in ("add", "_below", "_kth") if row_set is not None else ():
            patch.setattr(row_set, name, counted(getattr(row_set, name)))
        timeline._timeline_build(events, message_pool=pool, continuity=True)
    return count


def test_an_output_many_pool_rows_hold_is_indexed_in_linear_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # review pass 4: every open call was indexed against every pool row
    # holding its output, calls times rows
    def work(calls: int) -> int:
        events, pool = _shared_outputs(calls, interleaved=False)
        found = _pooled_work(events, pool, monkeypatch)
        stored = len(pool) + 2 * calls  # pool rows, one range and one output each
        assert found <= 20 * stored, (found, stored)
        return found

    small, large = work(200), work(400)
    assert large <= 2.2 * small + 10, (small, large)


def test_a_pooled_log_s_lookups_walk_the_smaller_of_lengths_and_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the known superlinear case: each input covers many open lengths and many
    # rows holding open outputs, never lined up, so each range walks the
    # smaller set; within the positions the inputs hold
    events, pool = _shared_outputs(200, interleaved=True)
    entries = sum(2 * n for n in range(1, 201))
    assert _pooled_work(events, pool, monkeypatch) <= entries + 20 * len(pool)


def _failures(calls: int, retried: bool) -> tuple[list[Any], list[Any]]:
    """With no origins: a turn, then `calls` failed calls and, with `retried`, one call sending their input again, carried on; else `calls` failed calls each with an input of its own and `calls` side calls ending like them. Events whose inputs are ranges of the returned pool."""
    from inspect_ai.event import ModelEvent, SpanBeginEvent, SpanEndEvent
    from inspect_ai.model import (
        ChatCompletionChoice,
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageUser,
        GenerateConfig,
        ModelOutput,
    )

    system = ChatMessageSystem(content="You are the main agent.")
    ask = ChatMessageUser(content="Answer in one word.")
    pool: list[Any] = [system, ask]
    events: list[Any] = [SpanBeginEvent(id="main", name="main", type="agent")]

    def model(uuid: str, refs: list[tuple[int, int]], text: str | None) -> None:
        output = ModelOutput(
            model="mockllm/model",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content=text), stop_reason="stop"
                )
            ]
            if text is not None
            else [],
        )
        events.append(
            ModelEvent(
                uuid=uuid,
                span_id="main",
                model="mockllm/model",
                input=[],
                input_refs=refs,
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=output,
                error=None if text is not None else "overloaded",
            )
        )

    def add(message: Any) -> int:
        pool.append(message)
        return len(pool) - 1

    model("m0", [(0, 2)], "Thinking.")
    if retried:
        nudge = add(ChatMessageUser(content="Go on."))
        for n in range(calls):
            model(f"f{n}", [(0, 3), (nudge, nudge + 1)], None)
        model("r", [(0, 3), (nudge, nudge + 1)], "One.")
        answer = add(ChatMessageAssistant(content="One."))
        model("m1", [(0, 3), (nudge, nudge + 1), (answer, answer + 1)], "Two.")
    else:
        for n in range(calls):
            plan = add(ChatMessageUser(content=f"Plan {n}."))
            model(f"f{n}", [(plan, plan + 1), (1, 2)], None)
        for n in range(calls):
            other = add(ChatMessageUser(content=f"Other {n}."))
            model(f"s{n}", [(other, other + 1), (1, 2)], "yes")
    events.append(SpanEndEvent(id="main"))
    return events, pool


@pytest.mark.parametrize("retried", [True, False])
def test_failed_calls_are_matched_to_retries_in_linear_work(
    retried: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    # review pass 4: a run of failures matched by one retry was removed one by
    # one, and side calls sharing their length and last message were compared
    # with every failure waiting
    from inspect_ai.event import _timeline as timeline

    fingerprint = timeline._Inputs.fingerprint

    def work(calls: int) -> int:
        count = 0

        def counting(self: Any, message: Any) -> Any:
            nonlocal count
            count += 1
            return fingerprint(self, message)

        events, pool = _failures(calls, retried)
        with monkeypatch.context() as patch:
            patch.setattr(timeline._Inputs, "fingerprint", counting)
            built = timeline._timeline_build(events, message_pool=pool, continuity=True)
        [main] = [item for item in built.root.content if isinstance(item, TimelineSpan)]
        utility = {
            event.uuid
            for item in main.content
            if isinstance(item, TimelineSpan) and item.utility
            for event in _model_events(item)
        }
        # the retried failures are what their retry is, a turn; failures never
        # retried are turns
        assert not utility & {f"f{n}" for n in range(calls)}
        return count

    small, large = work(200), work(400)
    assert large <= 2.2 * small + 10, (small, large)


def test_an_input_s_identity_is_the_same_pooled_or_expanded() -> None:
    # delta review d1: a retry's input stored at other pool rows, as rows
    # holding equal messages with other metadata, matched no failed call
    import random

    from inspect_ai._sentinel._steps import PoolView
    from inspect_ai.event._pool import _compress_refs
    from inspect_ai.event._timeline import _Inputs
    from inspect_ai.model import ChatMessageUser

    chooser = random.Random(11)
    for _ in range(200):
        pool = [
            ChatMessageUser(content=f"{chooser.randint(0, 3)}", metadata={"row": row})
            for row in range(chooser.randint(1, 30))
        ]
        inputs = _Inputs([], pool)
        rows = [chooser.randrange(len(pool)) for _ in range(chooser.randint(0, 20))]
        other = [
            chooser.choice([r for r, m in enumerate(pool) if m.text == pool[row].text])
            for row in rows
        ]
        pooled = PoolView(pool, _compress_refs(rows))
        assert inputs.identity(pooled) == inputs.identity(list(pooled))
        assert inputs.identity(pooled) == inputs.identity(
            PoolView(pool, _compress_refs(other))
        )
        differing = [
            r for r, m in enumerate(pool) if rows and m.text != pool[rows[0]].text
        ]
        if differing:
            changed = [differing[0], *rows[1:]]
            assert inputs.identity(pooled) != inputs.identity(
                PoolView(pool, _compress_refs(changed))
            )
