import contextlib
import inspect
from collections.abc import Awaitable, Callable, Iterator
from contextvars import ContextVar
from logging import getLogger
from typing import AsyncIterator

from shortuuid import uuid as shortuuid

logger = getLogger(__name__)


AGENT_SPAN_TYPE = "agent"
"""Span ``type`` value marking an agent-invocation boundary.

Every code path that invokes an ``Agent`` opens a span with this type
(``agent.run``, ``as_tool``, ``as_solver``, ``handoff``, and deepagent
task dispatch). The ACP event router counts concurrently-open spans
with this type to determine sub-agent nesting depth when filtering
transcript events for ``session/update`` notifications — events at
depth > 1 originated from a nested agent and are dropped.
"""


SCORERS_SPAN_NAME = "scorers"
"""Span ``name`` (and default ``type``, since ``span()`` defaults the
``type`` to ``name`` when omitted) wrapping the post-agent scoring phase.

Opened once by the task runner around the scorer loop. The ACP TUI
reads this in its raw-event consumer to (a) clear the plan strip once
scoring begins and (b) latch a "no more plan updates" flag so a
stale ``AgentPlanUpdate`` from late-attach replay can't resurrect the
plan after scoring already started.
"""


SCORER_SPAN_TYPE = "scorer"
"""Span ``type`` value wrapping a single scorer's execution.

Opened by the scorer loop per individual scorer (the inner span inside
the outer :data:`SCORERS_SPAN_NAME` block). The ACP TUI uses these to
mount + clear the per-scorer ``scoring · X…`` indicator chip — begin
mounts; matching end (or the scorer's ``ScoreEvent``) clears.
"""


SpanIdProvider = Callable[[str, str | None, str | None], Awaitable[str]]
"""Signature for a span-ID provider: ``await provider(name, parent_id, requested_id)`` → span id.

Set via `set_span_id_provider` to make `span()` use orchestrator-supplied IDs
(e.g. for replay-deterministic span identity across branched trajectories).
"""


@contextlib.asynccontextmanager
async def span(
    name: str, *, type: str | None = None, id: str | None = None
) -> AsyncIterator[None]:
    """Context manager for establishing a transcript span.

    Args:
        name (str): Step name.
        type (str | None): Optional span type.
        id (str | None): Optional span ID. Generated if not provided. If a
            span-ID provider is active (`set_span_id_provider`), it is
            consulted with ``(name, parent_id, requested_id)`` instead of
            generating a UUID.
    """
    from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
    from inspect_ai.log._transcript import (
        track_store_changes,
        transcript,
    )

    # capture parent id
    parent_id = _current_span_id.get()

    # span id
    provider = _span_id_provider.get()
    if provider is not None:
        id = await provider(name, parent_id, id)
    elif id is None:
        id = shortuuid()

    # set new current span (reset at the end)
    token = _current_span_id.set(id)

    # run the span
    try:
        # span begin event
        transcript()._event(
            SpanBeginEvent(
                id=id,
                parent_id=parent_id,
                type=type or name,
                name=name,
            )
        )

        # run span w/ store change events
        with track_store_changes():
            yield

    finally:
        # send end event
        transcript()._event(SpanEndEvent(id=id))

        try:
            _current_span_id.reset(token)
        except ValueError:
            frame = inspect.stack()[1]
            caller = f"{frame.function}() [{frame.filename}:{frame.lineno}]"
            logger.warning(f"Exiting span created in another context: {caller}")


def current_span_id() -> str | None:
    """Return the current span id (if any)."""
    return _current_span_id.get()


@contextlib.contextmanager
def span_id_provider(provider: SpanIdProvider | None) -> Iterator[None]:
    """Set the span-ID provider for the duration of the context.

    When set, every `span()` call consults ``await provider(name, parent_id, requested_id)`` to determine the span id (any explicit ``id`` argument is passed through as ``requested_id``).
    """
    token = _span_id_provider.set(provider)
    try:
        yield
    finally:
        _span_id_provider.reset(token)


_current_span_id: ContextVar[str | None] = ContextVar("_current_span_id", default=None)
_span_id_provider: ContextVar[SpanIdProvider | None] = ContextVar(
    "_span_id_provider", default=None
)
