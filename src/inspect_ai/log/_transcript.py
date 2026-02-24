import contextlib
from contextvars import ContextVar
from logging import getLogger
from typing import (
    Callable,
    Iterator,
    Sequence,
    TypeVar,
    overload,
)

from pydantic import (
    JsonValue,
)

from inspect_ai._util.logger import warn_once
from inspect_ai.event._base import BaseEvent
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._store import StoreEvent
from inspect_ai.event._timeline import Timeline
from inspect_ai.log._condense import (
    WalkContext,
    events_attachment_fn,
    walk_model_call,
)
from inspect_ai.util._store import store, store_changes, store_jsonable

logger = getLogger(__name__)


ET = TypeVar("ET", bound=BaseEvent)


class Transcript:
    """Transcript of events."""

    _event_logger: Callable[[Event], None] | None
    _context: WalkContext

    @overload
    def __init__(self) -> None: ...

    @overload
    def __init__(self, events: list[Event]) -> None: ...

    def __init__(self, events: list[Event] | None = None) -> None:
        self._event_logger = None
        self._context = WalkContext(message_cache={}, only_core=False)
        self._events: list[Event] = events if events is not None else []
        self._attachments: dict[str, str] = {}
        self._timelines: list[Timeline] = []

    def info(self, data: JsonValue, *, source: str | None = None) -> None:
        """Add an `InfoEvent` to the transcript.

        Args:
           data: Data associated with the event.
           source: Optional event source.
        """
        self._event(InfoEvent(source=source, data=data))

    @contextlib.contextmanager
    def step(self, name: str, type: str | None = None) -> Iterator[None]:
        """Context manager for recording StepEvent.

        The `step()` context manager is deprecated and will be removed in a future version.
        Please use the `span()` context manager instead.

        Args:
            name (str): Step name.
            type (str | None): Optional step type.
        """
        warn_once(
            logger,
            "The `transcript().step()` context manager is deprecated and will "
            + "be removed in a future version. Please replace the call to step() "
            + "with a call to span().",
        )
        yield

    @property
    def events(self) -> Sequence[Event]:
        return self._events

    @property
    def attachments(self) -> dict[str, str]:
        return self._attachments

    @property
    def timelines(self) -> Sequence[Timeline]:
        return self._timelines

    def add_timeline(self, timeline: Timeline) -> None:
        """Add a named timeline to the transcript.

        Args:
            timeline: Timeline to add.

        Raises:
            ValueError: If a timeline with the same name already exists.
        """
        for existing in self._timelines:
            if existing.name == timeline.name:
                raise ValueError(
                    f"A timeline with the name '{timeline.name}' already exists."
                )
        self._timelines.append(timeline)

    def _event(self, event: Event) -> None:
        if self._event_logger:
            self._event_logger(event)

        # condense model event calls immediately to prevent O(N) memory usage
        if isinstance(event, ModelEvent):
            event_fn = events_attachment_fn(self.attachments)
            event.call = walk_model_call(event.call, event_fn, self._context)

        self._events.append(event)

    def _event_updated(self, event: Event) -> None:
        if self._event_logger:
            self._event_logger(event)

        # condense model event call immediately to prevent O(N) memory usage (call is the only changed fields
        if isinstance(event, ModelEvent):
            event_fn = events_attachment_fn(self.attachments)
            event.call = walk_model_call(event.call, event_fn, self._context)

    def _subscribe(self, event_logger: Callable[[Event], None]) -> None:
        self._event_logger = event_logger


def transcript() -> Transcript:
    """Get the current `Transcript`."""
    return _transcript.get()


@contextlib.contextmanager
def track_store_changes() -> Iterator[None]:
    before = store_jsonable(store())
    yield
    after = store_jsonable(store())

    changes = store_changes(before, after)
    if changes:
        transcript()._event(StoreEvent(changes=changes))


def init_transcript(transcript: Transcript) -> None:
    _transcript.set(transcript)


_transcript: ContextVar[Transcript] = ContextVar(
    "subtask_transcript", default=Transcript()
)
