from inspect_ai.event._span import SpanBeginEvent
from inspect_ai.log._samples import sample_active
from inspect_ai.util._span import AGENT_SPAN_TYPE, current_agent_span_id


def live_conversation() -> str:
    """The conversation a model call made here belongs to: the innermost agent span, else the sample's uuid."""
    agent_span_id = current_agent_span_id()
    if agent_span_id is not None:
        return agent_span_id
    active = sample_active()
    return active.sample_uuid if active is not None else ""


class SpanConversations:
    """The conversation of each event in a log, from its span tree.

    An event's conversation is the innermost span of type `agent` reached from its `span_id` through `parent_id`, else the sample's uuid: what `live_conversation()` returned when the event was made. Spans are added in log order, as their `SpanBeginEvent`s are read, and each span's answer is kept, so a pass over a sample's events walks each span once. A walk that reaches a span not yet added is not kept, so a span whose begin is read later still counts.
    """

    def __init__(self, sample_uuid: str) -> None:
        self._sample_uuid = sample_uuid
        self._spans: dict[str, SpanBeginEvent] = {}
        self._conversations: dict[str, str] = {}

    def add(self, begin: SpanBeginEvent) -> None:
        self._spans[begin.id] = begin

    def conversation(self, span_id: str | None) -> str:
        """The conversation of an event in the span `span_id`.

        Raises:
            ValueError: The span tree has a `parent_id` cycle.
        """
        walked: set[str] = set()
        conversation = self._sample_uuid
        while span_id is not None:
            if span_id in self._conversations:
                conversation = self._conversations[span_id]
                break
            if span_id in walked:
                raise ValueError(f"The span tree has a parent_id cycle at {span_id}.")
            begin = self._spans.get(span_id)
            if begin is None:
                return conversation
            walked.add(span_id)
            if begin.type == AGENT_SPAN_TYPE:
                conversation = span_id
                break
            span_id = begin.parent_id
        for walked_id in walked:
            self._conversations[walked_id] = conversation
        return conversation
