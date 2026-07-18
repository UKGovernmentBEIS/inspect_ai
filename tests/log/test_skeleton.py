"""Tests for the structural skeleton producer.

The JSON fixture suite in ``test_skeleton/`` is language-neutral: each
fixture holds plain-JSON input events, optional policy knobs and the
expected skeleton, so a future TypeScript twin can run the same suite.
"""

import json
from pathlib import Path
from typing import Any, Sequence

import pytest
from pydantic import TypeAdapter

from inspect_ai._util.constants import DESERIALIZING
from inspect_ai.event._event import DiscriminatedEvent, Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._span import SpanBeginEvent
from inspect_ai.event._step import StepEvent
from inspect_ai.log._skeleton import (
    SampleSkeleton,
    SkeletonPolicy,
    sample_skeleton,
)

FIXTURES_DIR = Path(__file__).parent / "test_skeleton"

_events_adapter: TypeAdapter[list[Event]] = TypeAdapter(list[DiscriminatedEvent])


def _parse_events(data: list[dict[str, Any]]) -> list[Event]:
    return _events_adapter.validate_python(data, context={DESERIALIZING: True})


def _parse_policy(data: dict[str, Any]) -> SkeletonPolicy:
    defaults = SkeletonPolicy()
    return SkeletonPolicy(
        notable_cap=data.get("notable_cap", defaults.notable_cap),
        escape_hatch_events=data.get(
            "escape_hatch_events", defaults.escape_hatch_events
        ),
        notable_types=frozenset(data.get("notable_types", defaults.notable_types)),
    )


def _load_fixture(path: Path) -> tuple[list[Event], SkeletonPolicy, dict[str, Any]]:
    data = json.loads(path.read_text())
    return (
        _parse_events(data["events"]),
        _parse_policy(data.get("policy", {})),
        data["expected"],
    )


def assert_skeleton_invariants(
    skeleton: SampleSkeleton, events: Sequence[Event], policy: SkeletonPolicy
) -> None:
    """Structural invariants that must hold for any skeleton."""
    # sample totals match the event sequence
    assert skeleton.counts.events == len(events)
    assert skeleton.counts.models == sum(
        1 for ev in events if isinstance(ev, ModelEvent)
    )

    # span-proportional: one entry per structural span (+ capped notables),
    # never one per event
    span_begins = sum(1 for ev in events if isinstance(ev, SpanBeginEvent))
    step_begins = sum(
        1 for ev in events if isinstance(ev, StepEvent) and ev.action == "begin"
    )
    assert len(skeleton.spans) <= span_begins + step_begins
    assert len(skeleton.notables) <= policy.notable_cap * len(policy.notable_types)

    persisted_by_span: dict[int | None, int] = {}
    for notable in skeleton.notables:
        persisted_by_span[notable.span] = persisted_by_span.get(notable.span, 0) + 1
        if notable.span is not None:
            span = skeleton.spans[notable.span]
            assert span.extent[0] <= notable.i <= span.extent[1]

    for index, span in enumerate(skeleton.spans):
        child_spans = [s for s in skeleton.spans if s.parent == index]

        # gap_models layout: len == items + 1
        items = len(child_spans) + persisted_by_span.get(index, 0)
        assert len(span.gap_models) == items + 1

        # per-span model accounting
        assert sum(span.gap_models) + sum(s.models for s in child_spans) == span.models

        # extents and nesting
        assert span.extent[0] <= span.begin <= span.extent[1]
        assert 1 <= span.events <= len(events)
        if span.parent is not None:
            assert span.parent < index
            parent = skeleton.spans[span.parent]
            assert parent.extent[0] <= span.extent[0]
            assert span.extent[1] <= parent.extent[1]

    # root-level model accounting: every model event is in exactly one place
    root_models = sum(s.models for s in skeleton.spans if s.parent is None)
    assert root_models <= skeleton.counts.models


@pytest.mark.parametrize(
    "fixture_path",
    sorted(FIXTURES_DIR.glob("*.json")),
    ids=lambda path: path.stem,
)
def test_skeleton_fixture(fixture_path: Path) -> None:
    events, policy, expected = _load_fixture(fixture_path)
    skeleton = sample_skeleton(events, policy)
    assert skeleton.model_dump(mode="json", exclude_none=True) == expected
    assert_skeleton_invariants(skeleton, events, policy)


def test_skeleton_deterministic() -> None:
    events, policy, _ = _load_fixture(FIXTURES_DIR / "gap_models.json")
    first = sample_skeleton(events, policy).model_dump(mode="json", exclude_none=True)
    second = sample_skeleton(events, policy).model_dump(mode="json", exclude_none=True)
    assert first == second


def test_gap_models_additive() -> None:
    """Suppressing an item row == summing its adjacent gaps.

    Lowering the notable cap drops items from the gap layout; the dropped
    items' adjacent gaps must merge additively.
    """
    events, _, _ = _load_fixture(FIXTURES_DIR / "notable_caps.json")
    full = sample_skeleton(events, SkeletonPolicy(notable_cap=4)).spans[0]
    capped = sample_skeleton(events, SkeletonPolicy(notable_cap=2)).spans[0]
    assert full.gap_models == [1, 1, 1, 1, 1]
    # dropping the last two items merges their adjacent gaps into one
    assert capped.gap_models == [
        full.gap_models[0],
        full.gap_models[1],
        sum(full.gap_models[2:]),
    ]
    assert sum(capped.gap_models) == sum(full.gap_models)


def test_skeleton_span_proportional() -> None:
    """Skeleton size scales with structural spans, not events.

    Thousands of events inside excluded leaf tool spans produce no
    additional entries.
    """
    events_json: list[dict[str, Any]] = [
        {
            "event": "span_begin",
            "id": "S1",
            "name": "agent1",
            "type": "agent",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "working_start": 0.0,
        }
    ]
    for i in range(500):
        events_json.extend(
            [
                {
                    "event": "span_begin",
                    "id": f"T{i}",
                    "parent_id": "S1",
                    "span_id": "S1",
                    "name": "bash",
                    "type": "tool",
                    "timestamp": "2026-01-01T00:00:01+00:00",
                    "working_start": 1.0,
                },
                {
                    "event": "tool",
                    "span_id": f"T{i}",
                    "id": f"c{i}",
                    "function": "bash",
                    "arguments": {},
                    "timestamp": "2026-01-01T00:00:01+00:00",
                    "working_start": 1.0,
                },
                {
                    "event": "info",
                    "span_id": f"T{i}",
                    "data": "output",
                    "timestamp": "2026-01-01T00:00:01+00:00",
                    "working_start": 1.0,
                },
                {
                    "event": "span_end",
                    "id": f"T{i}",
                    "span_id": "S1",
                    "timestamp": "2026-01-01T00:00:01+00:00",
                    "working_start": 1.0,
                },
            ]
        )
    events_json.append(
        {
            "event": "span_end",
            "id": "S1",
            "timestamp": "2026-01-01T00:00:02+00:00",
            "working_start": 2.0,
        }
    )
    events = _parse_events(events_json)
    policy = SkeletonPolicy()
    skeleton = sample_skeleton(events, policy)
    assert_skeleton_invariants(skeleton, events, policy)
    assert skeleton.counts.events == 2002
    assert len(skeleton.spans) == 1  # all 500 leaf tool spans excluded
    assert skeleton.spans[0].children == {"tool": 500, "info": 500}
    assert len(json.dumps(skeleton.model_dump(mode="json", exclude_none=True))) < 2048


def test_skeleton_real_logs() -> None:
    """Producer runs over real .eval logs.

    Invariants hold and output is span-proportional (KBs, not
    event-proportional).
    """
    from inspect_ai.log import read_eval_log

    policy = SkeletonPolicy()
    tests_dir = Path(__file__).parent.parent
    checked_samples = 0
    for log_path in sorted(tests_dir.rglob("*.eval")):
        try:
            log = read_eval_log(str(log_path), resolve_attachments=False)
        except Exception:
            continue  # fixture logs for other tests may be intentionally odd
        for sample in log.samples or []:
            if not sample.events:
                continue
            skeleton = sample_skeleton(sample.events, policy)
            assert_skeleton_invariants(skeleton, sample.events, policy)
            serialized = json.dumps(skeleton.model_dump(mode="json", exclude_none=True))
            # span-proportional: far smaller than the events themselves
            assert len(serialized) < 512 * 1024
            checked_samples += 1

    assert checked_samples >= 3
