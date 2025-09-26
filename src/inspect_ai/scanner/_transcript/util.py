from functools import reduce
from typing import Iterable, TypeVar

from inspect_ai.log._transcript import Event
from inspect_ai.model._chat_message import ChatMessage

from .types import (
    EventFilter,
    MessageFilter,
    Transcript,
    TranscriptContent,
)


def union_transcript_contents(
    contents: Iterable[TranscriptContent],
) -> TranscriptContent:
    """Create the narrowest TranscriptContent that satisfies all passed TranscriptContent's.

    Each scanner has its own TranscriptContent filter describing what data it needs
    from the transcript. This function combines these individual scanner requirements
    into a single filter that represents the union of all needs. The goal is to
    create the narrowest possible filter that still satisfies every scanner's
    requirements, minimizing the amount of data loaded from large transcripts.

    Args:
        contents: Iterable of TranscriptContent objects, each representing a
            scanner's data requirements.

    Returns:
        A new TranscriptContent containing the union of all scanner filters.
    """
    return reduce(
        _union_contents,
        contents,
        TranscriptContent(None, None),
    )


def filter_transcript(transcript: Transcript, content: TranscriptContent) -> Transcript:
    """Filter a transcript based on specified content filters.

    Args:
        transcript: The original transcript to filter.
        content: Content filters specifying which messages and events to include.

    Returns:
        A new Transcript with filtered messages and events based on the content specification.
    """
    return Transcript(
        id=transcript.id,
        source_id=transcript.source_id,
        source_uri=transcript.source_uri,
        metadata=transcript.metadata,
        messages=_apply_filter_to_list(transcript.messages, content.messages),
        events=_apply_filter_to_list(transcript.events, content.events),
    )


def _union_contents(a: TranscriptContent, b: TranscriptContent) -> TranscriptContent:
    return TranscriptContent(
        _union_filters(a.messages, b.messages), _union_filters(a.events, b.events)
    )


T = TypeVar("T", MessageFilter, EventFilter)


def _union_filters(a: T, b: T) -> T:
    if a == "all" or b == "all":
        return "all"
    if a is None:
        return b
    if b is None:
        return a
    # At this point, both a and b are non-None and non-"all".
    return list(set(a) | set(b))


TMessageOrEvent = TypeVar("TMessageOrEvent", ChatMessage, Event)


def _apply_filter_to_list(
    items: list[TMessageOrEvent],
    filter_value: MessageFilter | EventFilter,
) -> list[TMessageOrEvent]:
    return (
        []
        if filter_value is None
        else (
            items
            if filter_value == "all"
            else [item for item in items if _matches_filter(item, filter_value)]
        )
    )


def _matches_filter(
    obj: ChatMessage | Event, filter: MessageFilter | EventFilter
) -> bool:
    if filter is None:
        return False
    if filter == "all":
        return True

    attr = (
        getattr(obj, "role", None)
        if hasattr(obj, "role")
        else getattr(obj, "event", None)
    )
    assert isinstance(attr, str)
    return attr in filter
