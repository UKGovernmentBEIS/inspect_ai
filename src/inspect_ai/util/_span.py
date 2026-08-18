import contextlib
import inspect
from collections.abc import Awaitable, Callable, Iterator
from contextvars import ContextVar, Token
from logging import getLogger
from typing import Any, AsyncIterator

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
    parent_id = current_span_id()

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
    current = _current_span_id.get()
    return current.id if isinstance(current, _SpanCell) else current


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


class _SpanCell:
    """Mutable holder for a span id, shared by reference across context copies.

    Task spawn copies a context's *values*; a later ``ContextVar.set`` in one
    task is invisible to already-running siblings. The copy is shallow,
    though — a cell placed on ``_current_span_id`` is shared by reference, so
    mutating ``cell.id`` is immediately visible to every task whose context
    chain bottoms out at the cell. ``id`` is ``None`` between spans (the
    enclosing parent may itself be ``None``).
    """

    __slots__ = ("id",)

    def __init__(self, id: str | None) -> None:
        self.id = id


class SpanRotationScope:
    """A sequence of sibling spans whose "current" id survives task spawns.

    Built for the checkpointer's ``checkpoint N`` spans: the span current
    when the agent does its work must rotate at each checkpoint fire, and the
    rotation must be visible to tasks spawned *before* the fire (e.g. the
    sandbox agent bridge's RPC service tasks, which emit model events on the
    agent's behalf). ``span()`` cannot express this — its ContextVar value is
    frozen into each task's context snapshot at spawn — so this scope places
    a shared ``_SpanCell`` on the chain instead and rotates by mutating it.

    ``open()`` and ``close()`` own the ContextVar set/reset pair and must run
    in the same task. ``end_span()`` and ``begin_span()`` may run in any task:
    they emit span/store events and mutate the shared cell, never touching
    the ContextVar.
    """

    def __init__(self, *, type: str) -> None:
        self._type = type
        self._cell: _SpanCell | None = None
        self._token: Token[str | _SpanCell | None] | None = None
        self._parent_id: str | None = None
        self._span_open = False
        self._store_before: dict[str, Any] = {}

    @property
    def is_open(self) -> bool:
        """Whether the scope is entered (between ``open()`` and ``close()``)."""
        return self._cell is not None

    async def open(self, name: str) -> None:
        """Enter the scope and begin its first span (entry task only)."""
        assert self._cell is None, "SpanRotationScope already open"
        self._parent_id = current_span_id()
        id = await self._span_id(name)
        self._cell = _SpanCell(id)
        self._token = _current_span_id.set(self._cell)
        self._span_open = True
        self._emit_begin(name, id)
        self._snapshot_store()

    async def begin_span(self, name: str) -> None:
        """Begin the next sibling span (any task)."""
        assert self._cell is not None, "SpanRotationScope not open"
        assert not self._span_open, "span already open"
        id = await self._span_id(name)
        self._cell.id = id
        self._span_open = True
        self._emit_begin(name, id)
        self._snapshot_store()

    async def end_span(self) -> None:
        """End the current span if one is open (any task)."""
        if not self._span_open:
            return
        from inspect_ai.event._span import SpanEndEvent
        from inspect_ai.log._transcript import transcript

        assert self._cell is not None and self._cell.id is not None
        # StoreEvent first, then SpanEndEvent — both constructed while the
        # cell still holds the ending span, so they stamp inside it (same
        # ordering and stamping as `span()`'s track_store_changes + finally).
        self._emit_store_changes()
        transcript()._event(SpanEndEvent(id=self._cell.id))
        self._span_open = False
        self._cell.id = self._parent_id

    async def close(self) -> None:
        """End any open span and exit the scope (entry task only). Idempotent."""
        if self._cell is None:
            return
        await self.end_span()
        assert self._token is not None
        _current_span_id.reset(self._token)
        self._token = None
        self._cell = None

    async def _span_id(self, name: str) -> str:
        provider = _span_id_provider.get()
        if provider is not None:
            return await provider(name, self._parent_id, None)
        return shortuuid()

    def _emit_begin(self, name: str, id: str) -> None:
        from inspect_ai.event._span import SpanBeginEvent
        from inspect_ai.log._transcript import transcript

        transcript()._event(
            SpanBeginEvent(
                id=id,
                parent_id=self._parent_id,
                type=self._type,
                name=name,
            )
        )

    def _snapshot_store(self) -> None:
        from inspect_ai.util._store import store, store_jsonable

        self._store_before = store_jsonable(store())

    def _emit_store_changes(self) -> None:
        from inspect_ai.event._store import StoreEvent
        from inspect_ai.log._transcript import transcript
        from inspect_ai.util._store import store, store_changes, store_jsonable

        changes = store_changes(self._store_before, store_jsonable(store()))
        if changes:
            transcript()._event(StoreEvent(changes=changes))


_current_span_id: ContextVar[str | _SpanCell | None] = ContextVar(
    "_current_span_id", default=None
)
_span_id_provider: ContextVar[SpanIdProvider | None] = ContextVar(
    "_span_id_provider", default=None
)
