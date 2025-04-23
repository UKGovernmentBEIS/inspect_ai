import contextlib
from contextvars import ContextVar
from typing import Iterator
from uuid import uuid4

import anyio


@contextlib.contextmanager
def span(name: str, type: str | None = None) -> Iterator[None]:
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
    task_id = anyio.get_current_task().id

    # capture parent id
    parent_id = _current_span.get()

    # set new current span (reset at the end)
    token = _current_span.set(id)

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

        # spend end event
        transcript()._event(SpanEndEvent(id=id))
    finally:
        _current_span.reset(token)


_current_span: ContextVar[str | None] = ContextVar("_current_span", default=None)
