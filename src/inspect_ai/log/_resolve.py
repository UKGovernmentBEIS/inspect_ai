from inspect_ai.event._pool import (
    resolve_model_event_calls,
    resolve_model_event_inputs,
)
from inspect_ai.event._validate import validate_chat_messages

from ._log import EvalSample


def resolve_sample_events_data(sample: EvalSample) -> EvalSample:
    """Resolve events_data pool references in model events.

    Always called on read to ensure ModelEvent.input is populated,
    regardless of the resolve_attachments setting.
    """
    if sample.events_data is None:
        return sample
    msg_pool = validate_chat_messages(
        sample.events_data["messages"], context={"deserializing": True}
    )
    call_pool = sample.events_data["calls"]
    resolved_events = resolve_model_event_inputs(sample.events, msg_pool)
    resolved_events = resolve_model_event_calls(resolved_events, call_pool)
    return sample.model_copy(
        update={
            "events": resolved_events,
            "events_data": None,
        }
    )


def rebind_sample_timelines(sample: EvalSample) -> EvalSample:
    """Rebind timelines to the sample's current event objects."""
    if not sample.timelines:
        return sample

    from inspect_ai.event._timeline import timeline_dump, timeline_load

    return sample.model_copy(
        update={
            "timelines": [
                timeline_load(timeline_dump(timeline), sample.events)
                for timeline in sample.timelines
            ],
        }
    )
