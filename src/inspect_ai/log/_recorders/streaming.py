from __future__ import annotations

from typing import TYPE_CHECKING

from inspect_ai._util.error import EvalError
from inspect_ai.event._pool import materialize_pooled_events
from inspect_ai.event._validate import validate_events
from inspect_ai.log._log import EvalRetryError, EvalSample
from inspect_ai.log._resolve import resolve_sample_events_data

if TYPE_CHECKING:
    from inspect_ai.log._recorders.buffer.history import SampleHistory


def materialize_streaming_sample(
    sample: EvalSample, history: "SampleHistory"
) -> EvalSample:
    events = validate_events(list(history.iter_events()))
    materialized = resolve_sample_events_data(
        sample.model_copy(update={"events": events, "events_data": history.events_data})
    )
    return materialized.model_copy(
        update={
            "attachments": {
                **materialized.attachments,
                **history.attachments,
            }
        }
    )


def eval_retry_error_from_history(
    error: EvalError, history: "SampleHistory"
) -> EvalRetryError:
    """Create retry error from full history since the latest ModelEvent."""
    suffix: list[object] = []
    for event in history.iter_events():
        if event.get("event") == "model":
            suffix = [event]
        elif suffix:
            suffix.append(event)

    events = materialize_pooled_events(
        suffix,
        history.events_data["messages"],
        history.events_data["calls"],
    )

    return EvalRetryError(
        message=error.message,
        traceback=error.traceback,
        traceback_ansi=error.traceback_ansi,
        events=events,
    )
