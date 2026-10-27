from inspect_ai.log._samples import sample_active
from inspect_ai.util._span import AgentSpans, current_agent_span_id


def current_conversation() -> str:
    """The conversation a model call made here belongs to: the innermost agent span, else the sample's uuid."""
    agent_span_id = current_agent_span_id()
    if agent_span_id is not None:
        return agent_span_id
    active = sample_active()
    return active.sample_uuid if active is not None else ""


class SpanConversations(AgentSpans):
    """The conversation of each event in a log, from its span tree.

    An event's conversation is its agent span (see `inspect_ai.util._span.AgentSpans`), else the sample's uuid: what `current_conversation()` returned when the event was made.
    """

    def __init__(self, sample_uuid: str) -> None:
        super().__init__()
        self._sample_uuid = sample_uuid

    def conversation(self, span_id: str | None) -> str:
        """The conversation of an event in the span `span_id`.

        Raises:
            ValueError: The span tree has a `parent_id` cycle.
        """
        agent_span = self.agent_span(span_id)
        return agent_span if agent_span is not None else self._sample_uuid
