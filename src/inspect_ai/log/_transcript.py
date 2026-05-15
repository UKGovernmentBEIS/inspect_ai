import contextlib
from contextvars import ContextVar
from logging import getLogger
from typing import (
    Callable,
    Iterator,
    Literal,
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
from inspect_ai.event._interrupt import InterruptEvent
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
    def __init__(self, *, log_model_api: bool | None = None) -> None: ...

    @overload
    def __init__(
        self, events: list[Event], log_model_api: bool | None = None
    ) -> None: ...

    def __init__(
        self, events: list[Event] | None = None, log_model_api: bool | None = None
    ) -> None:
        self._event_logger = None
        self._log_model_api = log_model_api
        self._context = WalkContext(message_cache={}, only_core=False)
        self._events: list[Event] = events if events is not None else []
        self._attachments: dict[str, str] = {}
        self._timelines: list[Timeline] = []
        self._model_call_counts: dict[str, int] = {}
        self._kept_event_ids: set[int] = set()
        self._additional_subscribers: list[Callable[[Event], None]] = []
        # Re-entry guard for the subscriber loop. A subscriber that
        # raises causes :data:`logger.exception` to run, which (when
        # ``inspect_ai``'s ``LogHandler`` is installed by eval) feeds
        # a fresh ``LoggerEvent`` back through ``_event`` → straight
        # into this method again. Without the guard, a consistently
        # broken subscriber would recurse infinitely. We still want
        # the recursive event to land in ``_events`` and reach the
        # single-slot ``_event_logger`` (log writer), but skip the
        # subscriber loop to break the cycle.
        self._notifying_subscribers: bool = False

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
        self._process_event(event)
        self._events.append(event)

    def _event_updated(self, event: Event) -> None:
        self._process_event(event)

    def _process_event(self, event: Event) -> None:
        if isinstance(event, ModelEvent) and event.call is not None:
            is_error = bool(event.call.error)
            if not is_error:
                if self._log_model_api is True:
                    pass
                elif self._log_model_api is False:
                    event.call = None
                else:
                    event_id = id(event)
                    if event_id not in self._kept_event_ids:
                        from inspect_ai._util.constants import (
                            DEFAULT_LOG_MODEL_API_CALLS,
                        )

                        count = self._model_call_counts.get(event.model, 0)
                        if count < DEFAULT_LOG_MODEL_API_CALLS:
                            self._model_call_counts[event.model] = count + 1
                            self._kept_event_ids.add(event_id)
                        else:
                            event.call = None

        if self._event_logger:
            self._event_logger(event)

        # Re-entrant call (a subscriber's logger.exception fed a
        # LoggerEvent back through here). Skip the subscriber loop
        # to avoid infinite recursion with a consistently broken
        # subscriber — the outer call's loop is the one that
        # delivers events anyway.
        if not self._notifying_subscribers:
            self._notifying_subscribers = True
            try:
                for sub in self._additional_subscribers:
                    try:
                        sub(event)
                    except Exception:
                        logger.exception("Transcript subscriber raised; continuing")
            finally:
                self._notifying_subscribers = False

        # condense model event calls immediately to prevent O(N) memory usage
        if isinstance(event, ModelEvent) and event.call is not None:
            event_fn = events_attachment_fn(self.attachments)
            event.call = walk_model_call(event.call, event_fn, self._context)

    def _subscribe(self, event_logger: Callable[[Event], None]) -> None:
        self._event_logger = event_logger

    def _add_subscriber(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        """Register an additive event subscriber.

        Unlike :meth:`_subscribe` (single-slot, used by the eval runner's
        log writer), multiple subscribers coexist and all fire on every
        event. Each subscriber runs in a try/except so one failing
        subscriber does not block others or interrupt the agent loop.

        Returns an idempotent unsubscribe callable.
        """
        self._additional_subscribers.append(callback)

        def unsubscribe() -> None:
            try:
                self._additional_subscribers.remove(callback)
            except ValueError:
                pass

        return unsubscribe


def transcript() -> Transcript:
    """Get the current `Transcript`."""
    return _transcript.get()


def record_interrupt_event(
    *,
    source: Literal["user_cancel", "limit", "system"],
    interrupted: Literal["generate", "tool_call", "between_turns"],
    interrupted_tool_call_id: str | None = None,
    interrupted_model_event_id: str | None = None,
) -> None:
    """Append an `InterruptEvent` to the current transcript.

    Internal helper used by Inspect's cancellation machinery — the ACP
    `cancel_current_turn` path, sample-level limit handlers, and system
    shutdown. Not a public API for agent authors.

    Args:
        source: What caused the interrupt — an ACP client cancel,
            a sample limit, or system shutdown.
        interrupted: What was running at the moment of the interrupt.
        interrupted_tool_call_id: ``ToolEvent.id`` of the in-flight
            tool call, if any.
        interrupted_model_event_id: ``ModelEvent.uuid`` of the
            in-flight model call, if any.
    """
    transcript()._event(
        InterruptEvent(
            source=source,
            interrupted=interrupted,
            interrupted_tool_call_id=interrupted_tool_call_id,
            interrupted_model_event_id=interrupted_model_event_id,
        )
    )


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
