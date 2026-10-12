from collections.abc import Iterable, Sequence

from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._span import SpanBeginEvent
from inspect_ai.model._chat_message import ChatMessage, ChatMessageSystem
from inspect_ai.util._span import AGENT_SPAN_TYPE

# a model call inside one of these is not an agent's own, whichever agent is above it
_NOT_AGENT_SPANS = frozenset({"tool", "sentinel", "compaction", "scorer"})
_SOLVERS_SPAN = "solvers"


def instance_events(
    newest_first: Iterable[Event], agent_span: str | None
) -> list[Event]:
    # an instance's calls all follow its agent span's begin (or, outside any
    # agent span, the solvers span's), so reading back stops there
    found: list[Event] = []
    for event in newest_first:
        found.append(event)
        if isinstance(event, SpanBeginEvent) and (
            event.id == agent_span
            if agent_span is not None
            else event.type == _SOLVERS_SPAN
        ):
            break
    found.reverse()
    return found


def agent_history(
    events: Sequence[Event],
    agent_span: str | None,
    active_model: str,
    pending: Sequence[ChatMessage] = (),
) -> list[ChatMessage] | None:
    # the model's view of one agent instance's run: every message it sent to its
    # model or received from it, first-seen order, deduplicated by id, a changed
    # message added again as a new version; from completed ModelEvents only, so
    # a replay over the same events gives the same history
    spans: dict[str, SpanBeginEvent] = {}
    view = _View()
    for event in events:
        if isinstance(event, SpanBeginEvent):
            spans[event.id] = event
        elif (
            isinstance(event, ModelEvent)
            and not event.pending
            and _is_agent_call(event, spans, agent_span, active_model)
        ):
            view.add(event.input)
            if event.output.choices:
                view.add([event.output.choices[0].message])
    view.add(pending)
    return view.messages if view.messages else None


def _is_agent_call(
    event: ModelEvent,
    spans: dict[str, SpanBeginEvent],
    agent_span: str | None,
    active_model: str,
) -> bool:
    # mirrors is_agent_generate: the nearest agent span owns the call, unless a
    # tool body, sentinel run, compaction or scorer is in between; outside any
    # agent span, only the active model's calls during the solvers count
    span_id = event.span_id
    solving = False
    while span_id is not None:
        span = spans.get(span_id)
        if span is None or span.type in _NOT_AGENT_SPANS:
            return False
        if span.type == AGENT_SPAN_TYPE:
            return span.id == agent_span
        solving = solving or span.type == _SOLVERS_SPAN
        span_id = span.parent_id
    return (
        agent_span is None
        and solving
        and event.role is None
        and event.model == active_model
    )


class _View:
    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []
        self._latest: dict[str, ChatMessage] = {}
        self._unidentified: list[ChatMessage] = []
        self._system: list[ChatMessage] = []

    def add(self, messages: Sequence[ChatMessage]) -> None:
        for message in messages:
            if message.id is None:
                if message in self._unidentified:
                    continue
                self._unidentified.append(message)
            else:
                latest = self._latest.get(message.id)
                if latest is message or latest == message:
                    continue
                # a configured system message is minted again for every call
                if (
                    latest is None
                    and isinstance(message, ChatMessageSystem)
                    and any(m.content == message.content for m in self._system)
                ):
                    continue
                self._latest[message.id] = message
            if isinstance(message, ChatMessageSystem):
                self._system.append(message)
            self.messages.append(message)
