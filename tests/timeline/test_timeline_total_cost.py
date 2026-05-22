"""Tests for TimelineSpan.total_cost() and the compute_model_cost re-export."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from inspect_ai import eval
from inspect_ai.event import Timeline, timeline_build
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._timeline import TimelineEvent, TimelineSpan
from inspect_ai.event._tool import ToolEvent
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    ModelCost,
    ModelInfo,
    ModelOutput,
    ModelUsage,
    compute_model_cost,
    set_model_cost,
    set_model_info,
)
from inspect_ai.model._model_output import ChatCompletionChoice

from .generate import (
    scenario_handoff_and_as_tool,
    scenario_nested_sub_agent,
    scenario_parallel_collect,
    scenario_simple_agent,
    scenario_utility_agent,
)

MOCK_MODEL = "mockllm/model"
MOCK_COST = ModelCost(
    input=1.0, output=2.0, input_cache_write=0.0, input_cache_read=0.0
)


# =============================================================================
# Synthetic event helpers (mirrors test_timeline_branches.py)
# =============================================================================


def _ts(seconds: float) -> datetime:
    return datetime(2025, 1, 1, 0, 0, int(seconds), tzinfo=timezone.utc)


def _model_event(
    *,
    uuid: str = "m1",
    span_id: str = "s1",
    ts: float = 0.0,
    model: str = "test-model",
    usage: ModelUsage | None = None,
) -> ModelEvent:
    if usage is None:
        usage = ModelUsage(input_tokens=10, output_tokens=20, total_tokens=30)
    return ModelEvent(
        uuid=uuid,
        span_id=span_id,
        timestamp=_ts(ts),
        working_start=ts,
        model=model,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        input=[ChatMessageUser(content="hi", id="u1")],
        output=ModelOutput(
            model=model,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content="ok", id="a1"),
                    stop_reason="stop",
                )
            ],
            usage=usage,
        ),
    )


def _make_span(
    *,
    id: str = "root",
    name: str = "main",
    content: list[Any] | None = None,
    branches: list[Any] | None = None,
) -> TimelineSpan:
    return TimelineSpan(
        id=id,
        name=name,
        span_type="agent",
        content=content or [],
        branches=branches or [],
    )


# =============================================================================
# Layer A — Synthetic unit tests
# =============================================================================


def test_total_cost_eval_time_passthrough() -> None:
    """ModelUsage.total_cost is returned verbatim when present."""
    usage = ModelUsage(
        input_tokens=10, output_tokens=20, total_tokens=30, total_cost=0.05
    )
    span = _make_span(content=[TimelineEvent(event=_model_event(usage=usage))])
    assert span.total_cost() == 0.05


def test_total_cost_subtree_sum_all_eval_time() -> None:
    """Nested spans: sum across all descendants."""
    inner = _make_span(
        id="inner",
        name="child",
        content=[
            TimelineEvent(
                event=_model_event(
                    uuid="m1",
                    usage=ModelUsage(
                        input_tokens=1, output_tokens=1, total_tokens=2, total_cost=0.01
                    ),
                )
            ),
            TimelineEvent(
                event=_model_event(
                    uuid="m2",
                    usage=ModelUsage(
                        input_tokens=1, output_tokens=1, total_tokens=2, total_cost=0.02
                    ),
                )
            ),
        ],
    )
    outer = _make_span(
        content=[
            TimelineEvent(
                event=_model_event(
                    uuid="m3",
                    usage=ModelUsage(
                        input_tokens=1, output_tokens=1, total_tokens=2, total_cost=0.04
                    ),
                )
            ),
            inner,
        ]
    )
    assert math.isclose(outer.total_cost(), 0.07)


def test_total_cost_retrospective_via_model_costs_dict() -> None:
    """When total_cost is None, fall back to compute_model_cost via dict lookup."""
    usage = ModelUsage(input_tokens=1000, output_tokens=500, total_tokens=1500)
    # input: 1000 * 1.0 / 1M = 0.001; output: 500 * 2.0 / 1M = 0.001 → 0.002
    span = _make_span(
        content=[TimelineEvent(event=_model_event(model="test-model", usage=usage))]
    )
    result = span.total_cost(model_costs={"test-model": MOCK_COST})
    assert math.isclose(result, 0.002)


def test_total_cost_retrospective_via_get_model_info() -> None:
    """No model_costs dict — fall back to registered ModelInfo cost."""
    model = "test-org/synthetic-retro-model"
    set_model_info(model, ModelInfo(name=model, api="mockllm", context_length=1000))
    set_model_cost(model, MOCK_COST)
    usage = ModelUsage(input_tokens=1000, output_tokens=500, total_tokens=1500)
    span = _make_span(
        content=[TimelineEvent(event=_model_event(model=model, usage=usage))]
    )
    # Same arithmetic as the dict case
    assert math.isclose(span.total_cost(), 0.002)


def test_total_cost_mixed_eval_time_and_retrospective() -> None:
    """One call with total_cost set, another None with dict fallback."""
    eval_time = ModelUsage(
        input_tokens=1, output_tokens=1, total_tokens=2, total_cost=0.07
    )
    retro = ModelUsage(input_tokens=1000, output_tokens=500, total_tokens=1500)
    span = _make_span(
        content=[
            TimelineEvent(event=_model_event(uuid="m1", usage=eval_time)),
            TimelineEvent(
                event=_model_event(uuid="m2", model="test-model", usage=retro)
            ),
        ]
    )
    # 0.07 + 0.002 = 0.072
    result = span.total_cost(model_costs={"test-model": MOCK_COST})
    assert math.isclose(result, 0.072)


def test_total_cost_missing_data_contributes_zero() -> None:
    """No total_cost, no dict, no get_model_info match → 0.0 (no raise)."""
    usage = ModelUsage(input_tokens=1000, output_tokens=500, total_tokens=1500)
    span = _make_span(
        content=[
            TimelineEvent(
                event=_model_event(model="unknown/never-registered", usage=usage)
            )
        ]
    )
    assert span.total_cost() == 0.0


def test_total_cost_non_model_event_contributes_zero() -> None:
    """ToolEvents and other non-ModelEvents contribute 0."""
    tool_event = ToolEvent(
        uuid="t1",
        span_id="s1",
        timestamp=_ts(0),
        working_start=0,
        id="call-1",
        function="addition",
        arguments={"x": 1, "y": 1},
    )
    span = _make_span(content=[TimelineEvent(event=tool_event)])
    assert span.total_cost() == 0.0


def test_total_cost_model_event_with_none_usage_contributes_zero() -> None:
    """ModelEvent with usage=None contributes 0 (defensive)."""
    event = _model_event()
    event.output.usage = None
    span = _make_span(content=[TimelineEvent(event=event)])
    assert span.total_cost() == 0.0


def test_total_cost_include_branches_flag() -> None:
    """include_branches=False excludes branch costs."""
    main = TimelineEvent(
        event=_model_event(
            uuid="m1",
            usage=ModelUsage(
                input_tokens=1, output_tokens=1, total_tokens=2, total_cost=0.10
            ),
        )
    )
    branch_event = TimelineEvent(
        event=_model_event(
            uuid="m2",
            usage=ModelUsage(
                input_tokens=1, output_tokens=1, total_tokens=2, total_cost=0.25
            ),
        )
    )
    branch = TimelineSpan(
        id="b1", name="branch", span_type="branch", content=[branch_event]
    )
    span = _make_span(content=[main], branches=[branch])
    assert math.isclose(span.total_cost(include_branches=True), 0.35)
    assert math.isclose(span.total_cost(include_branches=False), 0.10)


def test_compute_model_cost_public_import_smoke() -> None:
    """compute_model_cost is importable from inspect_ai.model and identical."""
    from inspect_ai.model import compute_model_cost as public
    from inspect_ai.model._model import compute_model_cost as private

    assert public is private


# =============================================================================
# Layer B — Integration tests via mockllm + eval()
# =============================================================================


def _flat_events(log_events: Iterable[Any]) -> list[Any]:
    return list(log_events)


def _flat_model_cost_sum(flat_events: list[Any], cost: ModelCost) -> float:
    """Sum compute_model_cost over every ModelEvent in the flat event list."""
    total = 0.0
    for e in flat_events:
        if isinstance(e, ModelEvent) and e.output.usage is not None:
            total += compute_model_cost(cost, e.output.usage)
    return total


def _flat_eval_time_sum(flat_events: list[Any]) -> float:
    """Sum ModelUsage.total_cost over every ModelEvent in the flat event list."""
    total = 0.0
    for e in flat_events:
        if isinstance(e, ModelEvent) and e.output.usage is not None:
            if e.output.usage.total_cost is not None:
                total += e.output.usage.total_cost
    return total


def _run_scenario(
    scenario_fn: Callable[[], tuple[str, Any, Any]],
) -> tuple[Timeline, list[Any]]:
    _, task, model = scenario_fn()
    log = eval(task, model=model, display="none")[0]
    assert log.status == "success"
    assert log.samples and log.samples[0].events
    events = log.samples[0].events
    return timeline_build(events), events


def _assert_cross_check_retrospective(
    timeline: Timeline, flat_events: list[Any]
) -> None:
    """Tree total_cost (retrospective) == sum over flat ModelEvents."""
    flat_sum = _flat_model_cost_sum(flat_events, MOCK_COST)
    tree_sum = timeline.root.total_cost(model_costs={MOCK_MODEL: MOCK_COST})
    assert math.isclose(tree_sum, flat_sum), (
        f"tree={tree_sum} flat={flat_sum} delta={tree_sum - flat_sum}"
    )
    assert flat_sum > 0  # sanity: scenarios actually generate usage


def test_integration_cross_check_simple_agent() -> None:
    timeline, events = _run_scenario(scenario_simple_agent)
    _assert_cross_check_retrospective(timeline, events)


def test_integration_cross_check_nested_sub_agent() -> None:
    timeline, events = _run_scenario(scenario_nested_sub_agent)
    _assert_cross_check_retrospective(timeline, events)


def test_integration_cross_check_utility_agent() -> None:
    timeline, events = _run_scenario(scenario_utility_agent)
    _assert_cross_check_retrospective(timeline, events)


def test_integration_cross_check_parallel_collect() -> None:
    timeline, events = _run_scenario(scenario_parallel_collect)
    _assert_cross_check_retrospective(timeline, events)


def test_integration_cross_check_handoff_and_as_tool() -> None:
    timeline, events = _run_scenario(scenario_handoff_and_as_tool)
    _assert_cross_check_retrospective(timeline, events)


def test_integration_eval_time_passthrough_end_to_end() -> None:
    """Register mockllm cost so total_cost is populated at eval time.

    Verifies that the eval-time-populated path through the recursion
    matches the same flat-event sum, on a real timeline produced by the
    full timeline_build() pipeline.
    """
    from inspect_ai.model._model_info import (
        _custom_models,
        clear_model_info_cache,
    )

    set_model_info(
        MOCK_MODEL,
        ModelInfo(name=MOCK_MODEL, api="mockllm", context_length=10_000),
    )
    set_model_cost(MOCK_MODEL, MOCK_COST)
    try:
        timeline, events = _run_scenario(scenario_nested_sub_agent)

        # At least some ModelEvents should have total_cost populated.
        usages_with_cost = [
            e.output.usage
            for e in events
            if isinstance(e, ModelEvent)
            and e.output.usage is not None
            and e.output.usage.total_cost is not None
        ]
        assert usages_with_cost, "expected eval-time total_cost to be populated"

        flat_eval_sum = _flat_eval_time_sum(events)
        tree_sum = timeline.root.total_cost()  # no model_costs arg
        assert math.isclose(tree_sum, flat_eval_sum)
        # Cross-consistency: eval-time sum matches manually recomputed sum
        flat_manual = _flat_model_cost_sum(events, MOCK_COST)
        assert math.isclose(flat_eval_sum, flat_manual)
    finally:
        _custom_models.pop(MOCK_MODEL, None)
        clear_model_info_cache()
