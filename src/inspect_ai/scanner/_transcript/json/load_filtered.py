import re
from dataclasses import dataclass
from typing import IO, Any, Callable, Literal, TypeAlias

import ijson  # type: ignore

from inspect_ai.scanner._transcript.json.reducer import (
    ListProcessingConfig,
    ParseState,
    reduce_parse_event,
)
from inspect_ai.scanner._transcript.types import (
    EventType,
    MessageType,
    Transcript,
    TranscriptInfo,
)

MessageFilter: TypeAlias = Literal["all"] | list[MessageType] | None
EventFilter: TypeAlias = Literal["all"] | list[EventType] | None

# Pre-compiled regex patterns for performance
ATTACHMENT_PATTERN = re.compile(r"attachment://([a-f0-9]{32})")
ATTACHMENT_PREFIX = "attachment://"


@dataclass(slots=True)
class RawTranscript:
    """Temporary structure for transcript data before validation."""

    id: str
    source: str
    metadata: dict[str, Any]
    messages: list[dict[str, Any]]
    events: list[dict[str, Any]]


async def load_filtered_transcript(
    sample_json: IO[bytes],
    t: TranscriptInfo,
    messages: MessageFilter,
    events: EventFilter,
) -> Transcript:
    """
    Transform and filter JSON sample data into a Transcript.

    Uses a two-phase approach:
    1. Stream parse and filter messages/events while collecting attachment references
    2. Resolve attachment references with actual values

    Args:
        sample_json: Byte stream of JSON sample data
        t: TranscriptInfo representing the transcript to load
        messages: Filter for message roles (None=exclude all, "all"=include all,
            list=include matching)
        events: Filter for event types (None=exclude all, "all"=include all,
            list=include matching)

    Returns:
        Transcript object with filtered messages and events, resolved attachments
    """
    # Phase 1: Parse, filter, and collect attachment references
    transcript, attachment_refs = _parse_and_filter(sample_json, t, messages, events)

    # Phase 2: Resolve attachment references
    final_transcript = _resolve_attachments(transcript, attachment_refs)

    return final_transcript


def _parse_and_filter(
    sample_json: IO[bytes],
    t: TranscriptInfo,
    messages_filter: MessageFilter,
    events_filter: EventFilter,
) -> tuple[RawTranscript, dict[str, str]]:
    """
    Phase 1: Single-pass stream parse, filter, and collect attachment references.

    Returns:
        Tuple of (partial transcript, attachment references dict)
    """
    # Create processing configurations
    messages_config = (
        ListProcessingConfig(
            array_item_prefix="messages.item",
            filter_field="role",
            filter_list=messages_filter,  # type:ignore
        )
        if messages_filter is not None
        else None
    )

    events_config = (
        ListProcessingConfig(
            array_item_prefix="events.item",
            filter_field="event",
            filter_list=events_filter,  # type:ignore
        )
        if events_filter is not None
        else None
    )

    state = ParseState()

    for prefix, event, value in ijson.parse(sample_json, use_float=True):
        # Use mutable reducer for all events
        reduce_parse_event(state, prefix, event, value, messages_config, events_config)

    return (
        RawTranscript(
            id=t.id,
            source=t.source,
            metadata=t.metadata,
            messages=state.messages,
            events=state.events,
        ),
        state.attachments,
    )


def _resolve_attachments(
    transcript: RawTranscript, attachments: dict[str, str]
) -> Transcript:
    """
    Phase 2: Replace attachment references with actual values.

    Args:
        transcript: Transcript with attachment references
        attachments: Dict mapping attachment IDs to their values

    Returns:
        Transcript with resolved attachment references
    """

    def resolve_string(text: str) -> str:
        """Replace attachment references in a string."""
        # Fast path: skip regex if no attachment prefix found
        if ATTACHMENT_PREFIX not in text:
            return text

        def replace_ref(match: re.Match[str]) -> str:
            attachment_id = match.group(1)
            return attachments.get(
                attachment_id, match.group(0)
            )  # Return original if not found

        return ATTACHMENT_PATTERN.sub(replace_ref, text)

    # Resolve references in messages (already raw dicts, no need to model_dump)
    resolved_messages = []
    for message_dict in transcript.messages:
        resolved_dict = _resolve_dict_attachments(message_dict, resolve_string)
        resolved_messages.append(resolved_dict)

    # Resolve references in events (already raw dicts, no need to model_dump)
    resolved_events = []
    for event_dict in transcript.events:
        resolved_dict = _resolve_dict_attachments(event_dict, resolve_string)
        resolved_events.append(resolved_dict)

    # Create new transcript with resolved data using single validation
    return Transcript.model_validate(
        {
            "id": transcript.id,
            "source": transcript.source,
            "metadata": transcript.metadata,
            "messages": resolved_messages,
            "events": resolved_events,
        }
    )


def _resolve_dict_attachments(obj: Any, resolve_func: Callable[[str], str]) -> Any:
    if isinstance(obj, str):
        return resolve_func(obj)
    if isinstance(obj, dict):
        return {k: _resolve_dict_attachments(v, resolve_func) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_dict_attachments(item, resolve_func) for item in obj]

    return obj
