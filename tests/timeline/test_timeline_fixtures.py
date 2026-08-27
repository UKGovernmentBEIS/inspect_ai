"""Fixture-driven tests for timeline_build().

Each JSON file in fixtures/events/ defines a flat event stream plus the
expected timeline structure. The same fixtures drive the TypeScript
implementation (ts-mono's fixtureTimeline.test.ts), keeping the Python and
TypeScript timeline builders consistent without duplicating test logic.

Fixture format: {"description": ..., "events": [...], "expected": {...}}
with expected sections "init", "agent", and "scoring" (see the assertion
helpers below for the supported expectation fields).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from inspect_ai.event import Event, Timeline, timeline_build
from inspect_ai.event._timeline import TimelineEvent, TimelineSpan

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "events"

_events_adapter = TypeAdapter(list[Event])


def _fixture_names() -> list[str]:
    return sorted(f.stem for f in FIXTURES_DIR.glob("*.json"))


def _load_fixture(name: str) -> dict[str, Any]:
    with open(FIXTURES_DIR / f"{name}.json") as f:
        data: dict[str, Any] = json.load(f)
        return data


# =============================================================================
# Assertion helpers (mirror ts-mono fixtureTimeline.test.ts)
# =============================================================================


def _direct_event_uuids(span: TimelineSpan) -> list[str]:
    return [
        item.event.uuid
        for item in span.content
        if isinstance(item, TimelineEvent) and item.event.uuid is not None
    ]


def _child_spans(span: TimelineSpan) -> list[TimelineSpan]:
    return [item for item in span.content if isinstance(item, TimelineSpan)]


def _all_event_uuids(span: TimelineSpan) -> list[str]:
    uuids: list[str] = []
    for item in span.content:
        if isinstance(item, TimelineEvent):
            if item.event.uuid is not None:
                uuids.append(item.event.uuid)
        else:
            uuids.extend(_all_event_uuids(item))
    return uuids


def _assert_span_matches(actual: TimelineSpan | None, expected: dict[str, Any]) -> None:
    assert actual is not None
    assert actual.id == expected["id"]
    assert actual.name == expected["name"]

    if "event_uuids" in expected:
        assert _direct_event_uuids(actual) == expected["event_uuids"]

    if "nested_uuids" in expected:
        assert _all_event_uuids(actual) == expected["nested_uuids"]

    if "total_tokens" in expected:
        assert actual.total_tokens() == expected["total_tokens"]

    if "utility" in expected:
        assert actual.utility == expected["utility"]

    if "agent_result" in expected:
        assert actual.agent_result == expected["agent_result"]

    if "children" in expected:
        children = _child_spans(actual)
        assert len(children) == len(expected["children"]), (
            f"Expected {len(expected['children'])} child spans of "
            f"'{actual.name}', got {[c.name for c in children]}"
        )
        for child, expected_child in zip(children, expected["children"]):
            _assert_span_matches(child, expected_child)

    if "branches" in expected:
        _assert_branches_match(actual, expected["branches"])


def _assert_branches_match(
    actual: TimelineSpan, expected_branches: list[dict[str, Any]]
) -> None:
    assert len(actual.branches) == len(expected_branches), (
        f"Expected {len(expected_branches)} branches of '{actual.name}', "
        f"got {len(actual.branches)}"
    )
    for branch, expected in zip(actual.branches, expected_branches):
        assert branch.branched_from == expected["branched_from"]
        if "event_uuids" in expected:
            assert _direct_event_uuids(branch) == expected["event_uuids"]
        if "children" in expected:
            children = _child_spans(branch)
            assert len(children) == len(expected["children"])
            for child, expected_child in zip(children, expected["children"]):
                _assert_span_matches(child, expected_child)
        if "branches" in expected:
            _assert_branches_match(branch, expected["branches"])


def _assert_section_matches(
    root: TimelineSpan, span_type: str, expected: dict[str, Any] | None
) -> None:
    sections = [
        item
        for item in root.content
        if isinstance(item, TimelineSpan) and item.span_type == span_type
    ]
    if expected is None:
        assert len(sections) == 0, f"Expected no '{span_type}' section"
        return
    assert len(sections) == 1
    if "event_uuids" in expected:
        assert _direct_event_uuids(sections[0]) == expected["event_uuids"]


def _assert_timeline_matches(timeline: Timeline, expected: dict[str, Any]) -> None:
    root = timeline.root

    _assert_section_matches(root, "init", expected["init"])
    _assert_section_matches(root, "scorers", expected["scoring"])

    expected_agent = expected["agent"]
    if expected_agent is None:
        return

    assert root.id == expected_agent["id"]
    assert root.name == expected_agent["name"]

    if "event_uuids" in expected_agent:
        assert _direct_event_uuids(root) == expected_agent["event_uuids"]

    if "utility" in expected_agent:
        assert root.utility == expected_agent["utility"]

    if "children" in expected_agent:
        children = [
            item
            for item in _child_spans(root)
            if item.span_type not in ("init", "scorers")
        ]
        assert len(children) == len(expected_agent["children"]), (
            f"Expected {len(expected_agent['children'])} child spans of root, "
            f"got {[c.name for c in children]}"
        )
        for child, expected_child in zip(children, expected_agent["children"]):
            _assert_span_matches(child, expected_child)

    if "branches" in expected_agent:
        _assert_branches_match(root, expected_agent["branches"])


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.parametrize("fixture_name", _fixture_names())
def test_timeline_fixture(fixture_name: str) -> None:
    fixture = _load_fixture(fixture_name)
    events = _events_adapter.validate_python(fixture["events"])
    timeline = timeline_build(events)
    _assert_timeline_matches(timeline, fixture["expected"])
