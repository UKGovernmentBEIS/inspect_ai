"""Per-sample streaming writer for filestore recovery."""

from __future__ import annotations

import json as json_module
import re
import tempfile
from logging import getLogger
from typing import IO

from pydantic import JsonValue

from inspect_ai._util.error import EvalError
from inspect_ai._util.json import to_json_safe
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._sample_limit import SampleLimitEvent
from inspect_ai.log._condense import (
    WalkContext,
    condense_event,
    messages_attachment_fn,
    walk_chat_messages,
    walk_input,
)
from inspect_ai.log._log import (
    EvalSampleLimit,
    EvalSampleSummary,
    EvalSpec,
    EventsData,
)
from inspect_ai.log._pool import (
    condense_model_event_calls,
    condense_model_event_inputs,
)
from inspect_ai.log._recorders.buffer.filestore import Manifest, SampleBufferFilestore
from inspect_ai.log._recorders.eval import ZipLogFile, _sample_filename
from inspect_ai.model._chat_message import ChatMessage

from ._attachments import StreamingAttachmentStore, write_attachments_field
from ._reconstruct import MessageAccumulator, _deserialize_events

logger = getLogger(__name__)


def _write_json_field(
    stream: IO[bytes], name: str, value: object, comma: bool = False
) -> None:
    """Write a single JSON field (``"name": value``) to a binary stream.

    Args:
        stream: Writable binary stream.
        name: JSON key.
        value: Value to serialize via ``to_json_safe``.
        comma: If True, prepend a comma separator.
    """
    if comma:
        stream.write(b",")
    stream.write(json_module.dumps(name).encode("utf-8"))
    stream.write(b":")
    stream.write(to_json_safe(value, indent=None))


def _write_sample_streaming(
    zip_log: "ZipLogFile",
    buffer: SampleBufferFilestore,
    summary: EvalSampleSummary,
    manifest: Manifest,
    *,
    eval_spec: EvalSpec,
    is_in_progress: bool = False,
    include_events: bool = True,
) -> EvalSampleSummary:
    """Stream-process a single sample's segments and write to a ZIP entry.

    Processes segments one at a time: deserialize events, run attachment
    walking, run pool dedup, write condensed events, feed to
    MessageAccumulator. After all segments, write messages/output/attachments.

    Returns the summary for stats accumulation. Samples with no flushed
    event data are still written with empty events/messages so summaries
    and sample files stay consistent.

    All fields declared on ``EvalSample`` are emitted unconditionally
    (``null`` or pydantic default when we have no source). Note: the key
    order here does **not** match ``EvalSample``'s pydantic declaration
    order -- the streaming invariant (events must flush before walked
    messages/output) makes strict ordering impractical, and pydantic
    parses order-insensitively.

    ``sample_init`` / ``sample_limit_event`` are detected on the raw
    (pre-condense) event stream: ``condense_event`` would rewrite the
    ``Sample`` payload on ``SampleInitEvent``, so we must look at raw
    events before condensing.
    """
    filename = _sample_filename(summary.id, summary.epoch)

    # State accumulated across segments
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(summary.id))[:40]
    attachments_dir = tempfile.mkdtemp(prefix=f"recov-att-{safe_id}-{summary.epoch}-")
    attachments = StreamingAttachmentStore(attachments_dir)
    message_pool: list[ChatMessage] = []
    call_pool: list[JsonValue] = []
    msg_index: dict[str, int] = {}
    call_index: dict[str, int] = {}
    walk_context = WalkContext(message_cache={}, only_core=False)
    accumulator = MessageAccumulator()

    # Per-sample reconstruction state captured from raw events
    sample_init: SampleInitEvent | None = None
    sample_limit_event: SampleLimitEvent | None = None

    # Build the error field
    error: EvalError | None = None
    if is_in_progress:
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

    total_segments = 0
    for sm in manifest.samples:
        if sm.summary.id == summary.id and sm.summary.epoch == summary.epoch:
            total_segments = len(sm.segments)
            break

    try:
        with zip_log._zip_open_write(filename) as stream:
            stream.write(b"{")

            # Write scalar fields from summary (input written later after walking)
            _write_json_field(stream, "id", summary.id)
            _write_json_field(stream, "epoch", summary.epoch, comma=True)
            _write_json_field(stream, "choices", summary.choices, comma=True)
            _write_json_field(stream, "target", summary.target, comma=True)

            # Stream events: process segments one at a time
            stream.write(b',"events":[')
            first_event = True
            read_count = 0

            for seg_id, seg_data in buffer.iter_sample_segments(
                summary.id, summary.epoch, manifest
            ):
                read_count += 1
                if total_segments > 100 and read_count % 500 == 0:
                    logger.info(
                        f"Streaming segments for sample {summary.id} epoch "
                        f"{summary.epoch}: {read_count}/{total_segments}"
                    )

                # Merge per-segment attachment pool into the streaming store.
                # Live buffer writer stores events with `attachment://<hash>` refs
                # and content in `seg_data.attachments` -- recovery must merge
                # them back in.
                for att in seg_data.attachments:
                    attachments[att.hash] = att.content

                # Deserialize events from this segment
                raw_events = _deserialize_events([ed.event for ed in seg_data.events])
                if not raw_events:
                    continue

                # Detect SampleInitEvent / SampleLimitEvent on the raw stream
                # (before condense_event, which would rewrite Sample payloads).
                if sample_init is None:
                    for ev in raw_events:
                        if isinstance(ev, SampleInitEvent):
                            sample_init = ev
                            break
                for ev in raw_events:
                    if isinstance(ev, SampleLimitEvent):
                        sample_limit_event = ev  # keep the last

                # Feed to message accumulator (before condensing)
                accumulator.process_events(raw_events)

                if include_events:
                    # Attachment walking per event
                    condensed = [
                        condense_event(ev, attachments, context=walk_context)
                        for ev in raw_events
                    ]

                    # Pool dedup (carrying state across segments)
                    condensed, message_pool, msg_index, _ = condense_model_event_inputs(
                        condensed, message_pool, msg_index
                    )

                    condensed, call_pool, call_index, _ = condense_model_event_calls(
                        condensed, call_pool, call_index
                    )

                    # Write condensed events to the stream
                    for ev in condensed:
                        if not first_event:
                            stream.write(b",")
                        stream.write(to_json_safe(ev, indent=None))
                        first_event = False

            if total_segments > 100:
                logger.info(
                    f"Streamed all segments for sample {summary.id} epoch "
                    f"{summary.epoch}: {read_count}/{total_segments}"
                )

            stream.write(b"]")  # close events array

            if total_segments > 100:
                logger.info(
                    f"Finished streaming events for sample {summary.id} epoch "
                    f"{summary.epoch}; writing walked messages/output/attachments"
                )

            # Derive structural fields from captured init/limit events
            sandbox_value = (
                sample_init.sample.sandbox
                if sample_init is not None and sample_init.sample.sandbox is not None
                else eval_spec.sandbox
            )
            files_value: list[str] | None = None
            if sample_init is not None and sample_init.sample.files:
                files_value = list(sample_init.sample.files.keys())
            setup_value = sample_init.sample.setup if sample_init is not None else None
            limit_value: EvalSampleLimit | None = None
            if sample_limit_event is not None and sample_limit_event.limit is not None:
                limit_value = EvalSampleLimit(
                    type=sample_limit_event.type,
                    limit=sample_limit_event.limit,
                )

            # Get messages and output from accumulator
            messages, output = accumulator.result()

            # Walk messages for attachment refs
            messages_fn = messages_attachment_fn(attachments)
            walked_input = walk_input(summary.input, messages_fn, walk_context)
            walked_messages = walk_chat_messages(messages, messages_fn, walk_context)

            # Sample init-derived fields
            _write_json_field(stream, "sandbox", sandbox_value, comma=True)
            _write_json_field(stream, "files", files_value, comma=True)
            _write_json_field(stream, "setup", setup_value, comma=True)

            # Summary-derived scalars
            _write_json_field(stream, "metadata", summary.metadata, comma=True)
            _write_json_field(stream, "scores", summary.scores, comma=True)

            # Store: parity with DB recovery path (defaults to {}).
            _write_json_field(stream, "store", {}, comma=True)

            _write_json_field(stream, "model_usage", summary.model_usage, comma=True)
            _write_json_field(stream, "role_usage", summary.role_usage, comma=True)
            _write_json_field(stream, "started_at", summary.started_at, comma=True)
            _write_json_field(stream, "completed_at", summary.completed_at, comma=True)
            _write_json_field(stream, "total_time", summary.total_time, comma=True)
            _write_json_field(stream, "working_time", summary.working_time, comma=True)
            _write_json_field(stream, "uuid", summary.uuid, comma=True)

            # Not reconstructable from buffer -- emit nulls.
            _write_json_field(stream, "timelines", None, comma=True)
            _write_json_field(stream, "invalidation", None, comma=True)

            _write_json_field(stream, "error", error, comma=True)
            _write_json_field(stream, "error_retries", None, comma=True)
            _write_json_field(stream, "limit", limit_value, comma=True)

            _write_json_field(stream, "input", walked_input, comma=True)
            _write_json_field(stream, "messages", walked_messages, comma=True)
            _write_json_field(stream, "output", output, comma=True)
            write_attachments_field(stream, attachments, comma=True)

            # Always emit events_data (null when pools empty / no events).
            events_data: EventsData | None = None
            if include_events and (message_pool or call_pool):
                events_data = EventsData(messages=message_pool, calls=call_pool)
            _write_json_field(stream, "events_data", events_data, comma=True)

            stream.write(b"}")
    finally:
        attachments.close()

    summary.completed = True

    return summary
