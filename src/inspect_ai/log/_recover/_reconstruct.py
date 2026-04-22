"""Reconstruct EvalSample from buffer DB data."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.error import EvalError
from inspect_ai.event._compaction import CompactionEvent
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.log._recorders.buffer.types import SampleData
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model_output import ModelOutput


def reconstruct_eval_sample(
    summary: EvalSampleSummary,
    sample_data: SampleData,
    *,
    cancelled: bool = False,
    include_events: bool = True,
) -> EvalSample:
    """Reconstruct an EvalSample from buffer DB data.

    Args:
        summary: Sample summary from the buffer DB samples table.
        sample_data: Events and attachments from buffer.get_sample_data().
        cancelled: If True, synthesize a cancellation EvalError
            (for in-progress samples interrupted by a crash).
        include_events: If False, return an empty events list and no
            timelines. Events are still deserialized internally to
            extract messages and output.

    Returns:
        A fully resolved EvalSample (not condensed — condensing happens
        at write time in Step 4).
    """
    # Deserialize events from JSON dicts
    events = _deserialize_events(
        [event_data.event for event_data in sample_data.events]
    )

    # Extract messages and output from events
    messages, output = _extract_messages_from_events(events)

    # Build attachments dict from buffer DB attachment data
    attachments = {
        attachment.hash: attachment.content for attachment in sample_data.attachments
    }

    # Set error: synthesize cancellation for in-progress samples,
    # or preserve existing error from completed-but-errored samples
    error: EvalError | None = None
    if cancelled:
        error = EvalError(
            message="CancelledError()",
            traceback="CancelledError: recovered from crashed eval\n",
            traceback_ansi="CancelledError: recovered from crashed eval\n",
        )
    elif summary.error is not None:
        error = EvalError(
            message=summary.error,
            traceback=f"{summary.error}\n",
            traceback_ansi=f"{summary.error}\n",
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
        events=events if include_events else [],
        timelines=None,
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


class MessageAccumulator:
    """Incrementally accumulates messages from events across segment batches.

    Extracted from _extract_messages_from_events so that segments can be
    processed one at a time with bounded memory.
    """

    def __init__(self) -> None:
        self._merged: list[ChatMessage] = []
        self._last_model_event: ModelEvent | None = None
        self._pending_trim_pre_input: list[ChatMessage] | None = None
        self._output: ModelOutput = ModelOutput()

    def process_events(self, events: list[Event]) -> None:
        """Feed a batch of deserialized events (typically one segment)."""
        for event in events:
            if isinstance(event, ModelEvent):
                if self._pending_trim_pre_input is not None:
                    prefix = _trim_prefix(
                        self._pending_trim_pre_input, list(event.input)
                    )
                    self._merged.extend(prefix)
                    self._pending_trim_pre_input = None

                self._last_model_event = event
                self._output = event.output

            elif isinstance(event, CompactionEvent):
                if event.type == "summary":
                    if self._last_model_event is not None:
                        self._merged.extend(_segment_messages(self._last_model_event))
                    self._last_model_event = None

                elif event.type == "trim":
                    if self._last_model_event is not None:
                        self._pending_trim_pre_input = list(
                            self._last_model_event.input
                        )
                    self._last_model_event = None

    def result(self) -> tuple[list[ChatMessage], ModelOutput]:
        """Return accumulated (messages, output)."""
        merged = list(self._merged)
        if self._last_model_event is not None:
            merged.extend(_segment_messages(self._last_model_event))
        return merged, self._output


def _extract_messages_from_events(
    events: list[Event],
) -> tuple[list[ChatMessage], ModelOutput]:
    """Extract messages from an event list, handling compaction boundaries."""
    acc = MessageAccumulator()
    acc.process_events(events)
    return acc.result()


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
