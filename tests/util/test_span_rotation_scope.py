"""Tests for `SpanRotationScope` — checkpoint-style spans across task spawns.

The scope exists because `ContextVar` values are frozen into each task's
context snapshot at spawn: a `span()` rotation performed in one task is
invisible to already-running siblings (the sandbox agent bridge's RPC
handler tasks). The scope shares a mutable cell by reference instead, so
these tests center on cross-task visibility.
"""

import logging
from collections.abc import Iterator

import anyio
import pytest

from inspect_ai.event._info import InfoEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.event._store import StoreEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.util._span import (
    SpanRotationScope,
    current_span_id,
    span,
    span_id_provider,
)
from inspect_ai.util._store import Store, init_subtask_store, store


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    init_transcript(Transcript())
    init_subtask_store(Store())
    yield
    init_transcript(Transcript())
    init_subtask_store(Store())


async def test_rotation_visible_to_previously_spawned_task() -> None:
    """A task spawned before a rotation stamps events with the new span.

    This is the sandbox-bridge regression: the bridge's RPC service tasks
    are spawned once (before any checkpoint fires) and emit events for the
    rest of the sample; rotations must reach them.
    """
    scope = SpanRotationScope(type="checkpoint")
    await scope.open("checkpoint 1")
    first_id = current_span_id()

    rotated = anyio.Event()
    observed: dict[str, str | None] = {}

    async def early_spawned() -> None:
        # context snapshot taken here, before the rotation below
        await rotated.wait()
        observed["span_id"] = InfoEvent(data="post-rotation").span_id

    async def rotator() -> None:
        await scope.end_span()
        await scope.begin_span("checkpoint 2")
        rotated.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(early_spawned)
        tg.start_soon(rotator)

    second_id = current_span_id()
    assert second_id is not None and second_id != first_id
    # the pre-rotation task saw the post-rotation span
    assert observed["span_id"] == second_id
    await scope.close()


async def test_rotation_in_child_task_visible_to_parent() -> None:
    scope = SpanRotationScope(type="checkpoint")
    await scope.open("checkpoint 1")
    first_id = current_span_id()

    async def rotate() -> None:
        await scope.end_span()
        await scope.begin_span("checkpoint 2")

    async with anyio.create_task_group() as tg:
        tg.start_soon(rotate)

    assert current_span_id() not in (None, first_id)
    await scope.close()


async def test_spans_are_siblings_under_session_parent() -> None:
    events: list[object] = []
    transcript()._subscribe(events.append)

    async with span("agent", type="agent"):
        agent_id = current_span_id()
        scope = SpanRotationScope(type="checkpoint")
        await scope.open("checkpoint 1")
        await scope.end_span()
        await scope.begin_span("checkpoint 2")
        await scope.close()

    begins = [
        e for e in events if isinstance(e, SpanBeginEvent) and e.type == "checkpoint"
    ]
    assert [b.name for b in begins] == ["checkpoint 1", "checkpoint 2"]
    assert all(b.parent_id == agent_id for b in begins)
    # begin/end events self-stamp (same as `span()`)
    ends = [e for e in events if isinstance(e, SpanEndEvent)]
    assert {b.id for b in begins} <= {e.id for e in ends}


async def test_current_span_is_parent_between_spans() -> None:
    async with span("agent", type="agent"):
        agent_id = current_span_id()
        scope = SpanRotationScope(type="checkpoint")
        await scope.open("checkpoint 1")
        assert current_span_id() != agent_id
        await scope.end_span()
        assert current_span_id() == agent_id
        await scope.begin_span("checkpoint 2")
        assert current_span_id() not in (None, agent_id)
        await scope.close()
        assert current_span_id() == agent_id


async def test_no_cross_context_warning_on_cross_task_rotation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # inspect_ai loggers don't propagate; attach caplog's handler directly
    span_logger = logging.getLogger("inspect_ai.util._span")
    span_logger.addHandler(caplog.handler)
    try:
        scope = SpanRotationScope(type="checkpoint")
        await scope.open("checkpoint 1")

        async def rotate() -> None:
            await scope.end_span()
            await scope.begin_span("checkpoint 2")

        async with anyio.create_task_group() as tg:
            tg.start_soon(rotate)
        await scope.close()
    finally:
        span_logger.removeHandler(caplog.handler)

    assert not [r for r in caplog.records if "another context" in r.getMessage()]


async def test_store_changes_emitted_inside_closing_span() -> None:
    events: list[object] = []
    transcript()._subscribe(events.append)

    scope = SpanRotationScope(type="checkpoint")
    await scope.open("checkpoint 1")
    first_id = current_span_id()
    store().set("key", "value")
    await scope.end_span()
    await scope.close()

    store_events = [e for e in events if isinstance(e, StoreEvent)]
    assert len(store_events) == 1
    assert store_events[0].span_id == first_id
    # StoreEvent precedes the SpanEndEvent (same ordering as `span()`)
    end_index = next(i for i, e in enumerate(events) if isinstance(e, SpanEndEvent))
    assert events.index(store_events[0]) < end_index


async def test_span_id_provider_consulted() -> None:
    async def provider(name: str, parent_id: str | None, id: str | None) -> str:
        return f"provided-{name}"

    with span_id_provider(provider):
        scope = SpanRotationScope(type="checkpoint")
        await scope.open("checkpoint 1")
        assert current_span_id() == "provided-checkpoint 1"
        await scope.end_span()
        await scope.begin_span("checkpoint 2")
        assert current_span_id() == "provided-checkpoint 2"
        await scope.close()


async def test_normal_span_shadows_cell() -> None:
    scope = SpanRotationScope(type="checkpoint")
    await scope.open("checkpoint 1")
    checkpoint_id = current_span_id()

    async with span("tool", type="tool"):
        tool_id = current_span_id()
        assert tool_id != checkpoint_id
        assert InfoEvent(data="in-tool").span_id == tool_id

    assert current_span_id() == checkpoint_id
    await scope.close()


async def test_close_is_idempotent() -> None:
    scope = SpanRotationScope(type="checkpoint")
    await scope.open("checkpoint 1")
    await scope.close()
    await scope.close()
    assert current_span_id() is None
    # reusable after close (second `span_session()` in the same sample)
    await scope.open("checkpoint 2")
    assert current_span_id() is not None
    await scope.close()
