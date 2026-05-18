from __future__ import annotations

from inspect_ai._util.error import EvalError
from inspect_ai.log._event_store.history import SampleHistory
from inspect_ai.log._log import EvalRetryError
from inspect_ai.log._pool import resolve_model_event_calls, resolve_model_event_inputs
from inspect_ai.log._recorders.recorder import materialize_streaming_events


def eval_retry_error_from_history(
    error: EvalError, history: SampleHistory
) -> EvalRetryError:
    """Create retry error from full history since the latest ModelEvent."""
    suffix: list[object] = []
    for event in history.iter_events():
        if event.get("event") == "model":
            suffix = [event]
        elif suffix:
            suffix.append(event)

    events = materialize_streaming_events(suffix)
    events = resolve_model_event_inputs(events, history.events_data["messages"])
    events = resolve_model_event_calls(events, history.events_data["calls"])

    return EvalRetryError(
        message=error.message,
        traceback=error.traceback,
        traceback_ansi=error.traceback_ansi,
        events=events,
    )
