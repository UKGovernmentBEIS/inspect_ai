"""Execution observer for in-flight model/tool tracking.

The agent runtime needs a way to record what work is "in flight" so that
intervention producers (ACP today, future supervisors) can capture
provenance when they interrupt. Today's ACP layer needs this to populate
:class:`InterruptEvent` cross-reference fields and to clear ``pending=True``
on cancelled in-flight events so the transcript shows them as cancelled
rather than forever-running.

The channel itself does not own this concern: the data is producer-
specific (ACP-shaped today; other producers may track differently or not
at all). So we route it through a generic :class:`ExecutionObserver`
Protocol — model/tool layers call the observer, producers implement it.
The default :class:`NullExecutionObserver` no-ops so an eval with no
producers attached pays no overhead.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Iterator, Protocol, runtime_checkable

if TYPE_CHECKING:
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._tool import ToolEvent


@runtime_checkable
class ExecutionObserver(Protocol):
    """Observer notified of in-flight tool calls and model events.

    Implementers wrap each top-level tool execution and each model
    generation in their respective ``track_*`` context managers. The
    observer captures the call into its own state (typically used to
    populate an interrupt-event snapshot at cancel time) for the
    lifetime of the wrapping scope.
    """

    def track_tool_call(
        self, tool_call_id: str, event: "ToolEvent | None" = None
    ) -> contextlib.AbstractContextManager[None]:
        """Mark a tool call as in flight for the lifetime of the scope."""
        ...

    def track_model_event(
        self, event: "ModelEvent"
    ) -> contextlib.AbstractContextManager[None]:
        """Mark a model call as in flight for the lifetime of the scope."""
        ...


class NullExecutionObserver:
    """Default observer that records nothing.

    Used when no producer is attached. Both ``track_*`` context managers
    are no-op yields so call sites pay nothing.
    """

    @contextlib.contextmanager
    def track_tool_call(
        self, tool_call_id: str, event: "ToolEvent | None" = None
    ) -> Iterator[None]:
        yield

    @contextlib.contextmanager
    def track_model_event(self, event: "ModelEvent") -> Iterator[None]:
        yield


_NULL_OBSERVER: ExecutionObserver = NullExecutionObserver()


def null_execution_observer() -> ExecutionObserver:
    """Return the shared :class:`NullExecutionObserver` singleton."""
    return _NULL_OBSERVER
