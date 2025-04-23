import contextlib
from contextvars import ContextVar
from typing import Iterator
from uuid import uuid4

from inspect_ai.util._anyio import safe_current_task_id


@contextlib.contextmanager
def span(name: str, *, type: str | None = None) -> Iterator[None]:
    """Context manager for establishing a transcript span.

    Args:
        name (str): Step name.
        type (str | None): Optional span type.
    """
    from inspect_ai.log._transcript import (
        SpanBeginEvent,
        SpanEndEvent,
        track_store_changes,
        transcript,
    )

    # determine span and task id
    id = uuid4().hex
    task_id = safe_current_task_id()

    # capture parent id
    parent_id = _current_span_id.get()

    # set new current span (reset at the end)
    token = _current_span_id.set(id)

    # run the span
    try:
        # span begin event
        transcript()._event(
            SpanBeginEvent(
                id=id,
                parent_id=parent_id,
                task_id=task_id,
                type=type,
                name=name,
            )
        )

        # run span w/ store change events
        with track_store_changes():
            yield

    finally:
        # send end event
        transcript()._event(SpanEndEvent(id=id))

        _current_span_id.reset(token)


def current_span_id() -> str | None:
    return _current_span_id.get()


_current_span_id: ContextVar[str | None] = ContextVar("_current_span_id", default=None)
