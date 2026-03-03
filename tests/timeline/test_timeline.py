"""Pytest tests for timeline scenarios.

Each test runs a scenario from generate.py and validates the resulting timeline.
"""

from typing import Any, Callable

from inspect_ai import eval
from inspect_ai.event import Timeline, timeline_build

from .generate import (
    scenario_auto_branching,
    scenario_deep_nesting,
    scenario_deep_utility,
    scenario_handoff_and_as_tool,
    scenario_multi_turn_agent,
    scenario_multiple_rerolls,
    scenario_nested_sub_agent,
    scenario_parallel_collect,
    scenario_parallel_heterogeneous,
    scenario_parallel_with_nesting,
    scenario_sequential_and_parallel,
    scenario_sequential_run,
    scenario_simple_agent,
    scenario_utility_agent,
    validate_auto_branching,
    validate_deep_nesting,
    validate_deep_utility,
    validate_handoff_and_as_tool,
    validate_multi_turn_agent,
    validate_multiple_rerolls,
    validate_nested_sub_agent,
    validate_parallel_collect,
    validate_parallel_heterogeneous,
    validate_parallel_with_nesting,
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


def test_timeline_multi_turn_agent() -> None:
    _run_and_validate(scenario_multi_turn_agent, validate_multi_turn_agent)


def test_timeline_nested_sub_agent() -> None:
    _run_and_validate(scenario_nested_sub_agent, validate_nested_sub_agent)


def test_timeline_auto_branching() -> None:
    _run_and_validate(scenario_auto_branching, validate_auto_branching)


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


def test_timeline_multiple_rerolls() -> None:
    _run_and_validate(scenario_multiple_rerolls, validate_multiple_rerolls)


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
