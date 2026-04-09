"""Reconstruct EvalSample from buffer DB data."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.error import EvalError
from inspect_ai.event._compaction import CompactionEvent
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._timeline import Timeline, TimelineEvent, timeline_build
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.log._recorders.buffer.types import SampleData
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model_output import ModelOutput


def reconstruct_eval_sample(
    summary: EvalSampleSummary,
    sample_data: SampleData,
    *,
    cancelled: bool = False,
) -> EvalSample:
    """Reconstruct an EvalSample from buffer DB data.

    Args:
        summary: Sample summary from the buffer DB samples table.
        sample_data: Events and attachments from buffer.get_sample_data().
        cancelled: If True, synthesize a cancellation EvalError
            (for in-progress samples interrupted by a crash).

    Returns:
        A fully resolved EvalSample (not condensed — condensing happens
        at write time in Step 4).
    """
    # Deserialize events from JSON dicts
    events = _deserialize_events(
        [event_data.event for event_data in sample_data.events]
    )

    # Build timeline and extract messages
    messages, output = _extract_messages_and_output(events)

    # Build attachments dict from buffer DB attachment data
    attachments = {
        attachment.hash: attachment.content for attachment in sample_data.attachments
    }

    # Build timeline
    timelines: list[Timeline] | None = None
    if events:
        try:
            timeline = timeline_build(events)
            timelines = [timeline]
        except Exception:
            # timeline_build can fail on partial/malformed event streams
            pass

    # Synthesize cancellation error for in-progress samples
    error: EvalError | None = None
    if cancelled:
        error = EvalError(
            message="CancelledError()",
            traceback="CancelledError: recovered from crashed eval\n",
            traceback_ansi="CancelledError: recovered from crashed eval\n",
        )

    return EvalSample(
        id=summary.id,
        epoch=summary.epoch,
        input=summary.input,
        choices=summary.choices,
        target=summary.target,
        metadata=summary.metadata,
        messages=messages,
        output=output,
        scores=summary.scores,
        events=events,
        timelines=timelines,
        attachments=attachments,
        model_usage=summary.model_usage,
        role_usage=summary.role_usage,
        started_at=summary.started_at,
        completed_at=summary.completed_at,
        total_time=summary.total_time,
        working_time=summary.working_time,
        uuid=summary.uuid,
        error=error,
    )


def _deserialize_events(event_dicts: list[dict[str, Any]]) -> list[Event]:
    """Deserialize event JSON dicts into typed Event objects."""
    if not event_dicts:
        return []
    adapter: TypeAdapter[list[Event]] = TypeAdapter(list[Event])
    return adapter.validate_python(event_dicts, context=get_deserializing_context())


def _extract_messages_and_output(
    events: list[Event],
) -> tuple[list[ChatMessage], ModelOutput]:
    """Extract messages and output from events using timeline_build.

    Uses the span_messages pattern: build a timeline to discover the main
    trajectory, then walk ModelEvents to extract messages, handling
    compaction boundaries.

    Returns:
        Tuple of (messages, output). Messages is the full conversation
        history. Output is the last ModelEvent's output, or a default
        ModelOutput if no ModelEvents exist.
    """
    if not events:
        return [], ModelOutput()

    # Build timeline to discover main trajectory
    try:
        timeline = timeline_build(events)
    except Exception:
        # Fall back to flat event walk if timeline_build fails
        return _extract_messages_flat(events)

    # Extract events from the timeline's root span
    span_events = [
        item.event for item in timeline.root.content if isinstance(item, TimelineEvent)
    ]

    return _extract_messages_from_events(span_events)


def _extract_messages_flat(
    events: list[Event],
) -> tuple[list[ChatMessage], ModelOutput]:
    """Fallback: extract messages from a flat event list."""
    return _extract_messages_from_events(events)


def _extract_messages_from_events(
    events: list[Event],
) -> tuple[list[ChatMessage], ModelOutput]:
    """Extract messages from an event list, handling compaction boundaries.

    Follows the span_messages pattern from inspect_scout with
    compaction="all" — merges across all compaction boundaries for
    full message history reconstruction.
    """
    # Collect ModelEvents
    model_events: list[ModelEvent] = [e for e in events if isinstance(e, ModelEvent)]

    if not model_events:
        return [], ModelOutput()

    # The last ModelEvent's output is the sample output
    output = model_events[-1].output

    # Merge messages across compaction boundaries
    merged: list[ChatMessage] = []
    current_model_events: list[ModelEvent] = []
    pending_trim_pre_input: list[ChatMessage] | None = None

    for event in events:
        if isinstance(event, ModelEvent):
            if pending_trim_pre_input is not None:
                prefix = _trim_prefix(pending_trim_pre_input, list(event.input))
                merged.extend(prefix)
                pending_trim_pre_input = None

            current_model_events.append(event)

        elif isinstance(event, CompactionEvent):
            if event.type == "summary":
                if current_model_events:
                    merged.extend(_segment_messages(current_model_events[-1]))
                current_model_events = []

            elif event.type == "trim":
                if current_model_events:
                    pending_trim_pre_input = list(current_model_events[-1].input)
                current_model_events = []

            # Edit: transparent, continue accumulating

    # Append final segment
    if current_model_events:
        merged.extend(_segment_messages(current_model_events[-1]))

    return merged, output


def _segment_messages(model_event: ModelEvent) -> list[ChatMessage]:
    """Extract messages from a ModelEvent (input + output message)."""
    messages = list(model_event.input)
    if (
        model_event.output is not None
        and model_event.output.choices
        and model_event.output.choices[0].message is not None
    ):
        messages.append(model_event.output.choices[0].message)
    return messages


def _trim_prefix(
    pre_input: list[ChatMessage],
    post_input: list[ChatMessage],
) -> list[ChatMessage]:
    """Compute messages trimmed by a trim compaction.

    Finds the overlap between pre and post compaction inputs,
    returning the prefix that was dropped.
    """
    if not post_input or not pre_input:
        return []

    # Try matching by message id
    first_post_id = post_input[0].id
    if first_post_id is not None:
        for i, msg in enumerate(pre_input):
            if msg.id == first_post_id:
                return pre_input[:i]

    # Fall back to content equality
    first_post_text = post_input[0].text
    for i, msg in enumerate(pre_input):
        if msg.text == first_post_text and msg.role == post_input[0].role:
            return pre_input[:i]

    return []
