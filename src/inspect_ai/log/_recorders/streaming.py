from __future__ import annotations

from collections.abc import Sequence

from pydantic import TypeAdapter

from inspect_ai._util.error import EvalError
from inspect_ai.log._event_store.history import SampleHistory
from inspect_ai.log._log import EvalRetryError
from inspect_ai.log._pool import resolve_model_event_calls, resolve_model_event_inputs
from inspect_ai.log._recorders.recorder import materialize_streaming_events
from inspect_ai.model import ChatMessage

_chat_messages_adapter: TypeAdapter[list[ChatMessage]] | None = None


def eval_retry_error_from_history(
    error: EvalError, history: SampleHistory
) -> EvalRetryError:
    """Create retry error from full history since the latest ModelEvent."""
    suffix: list[object] = []
    for event in history.event_dicts():
        if event.get("event") == "model":
            suffix = [event]
        elif suffix:
            suffix.append(event)

    events = materialize_streaming_events(suffix)
    events = resolve_model_event_inputs(
        events, _chat_messages(history.events_data["messages"])
    )
    events = resolve_model_event_calls(events, history.events_data["calls"])

    return EvalRetryError(
        message=error.message,
        traceback=error.traceback,
        traceback_ansi=error.traceback_ansi,
        events=events,
    )


def _chat_messages(messages: Sequence[object]) -> list[ChatMessage]:
    global _chat_messages_adapter
    if _chat_messages_adapter is None:
        _chat_messages_adapter = TypeAdapter(list[ChatMessage])
    return _chat_messages_adapter.validate_python(
        messages, context={"deserializing": True}
    )
