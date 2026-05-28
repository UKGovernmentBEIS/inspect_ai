from __future__ import annotations

from typing import TYPE_CHECKING

from inspect_ai.event._validate import validate_events
from inspect_ai.log._log import EvalSample
from inspect_ai.log._resolve import rebind_sample_timelines, resolve_sample_events_data

if TYPE_CHECKING:
    from inspect_ai.log._recorders.buffer.history import SampleHistory


def materialize_streaming_sample(
    sample: EvalSample, history: "SampleHistory"
) -> EvalSample:
    events = validate_events(list(history.iter_events()))
    materialized = resolve_sample_events_data(
        sample.model_copy(update={"events": events, "events_data": history.events_data})
    )
    materialized = materialized.model_copy(
        update={
            "attachments": {
                **materialized.attachments,
                **history.attachments,
            }
        }
    )
    return rebind_sample_timelines(materialized)
