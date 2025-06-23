import contextlib
import inspect
from contextvars import ContextVar
from logging import getLogger
from typing import AsyncIterator
from uuid import uuid4

logger = getLogger(__name__)


@contextlib.asynccontextmanager
async def span(name: str, *, type: str | None = None) -> AsyncIterator[None]:
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

    # span id
    id = uuid4().hex

    # span caller context
    frame = inspect.stack()[1]
    caller = f"{frame.function}() [{frame.filename}:{frame.lineno}]"

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
            logger.warning(f"Exiting span created in another context: {caller}")


def current_span_id() -> str | None:
    return _current_span_id.get()


_current_span_id: ContextVar[str | None] = ContextVar("_current_span_id", default=None)
