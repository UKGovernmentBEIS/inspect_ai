from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import SampleLimitEvent


def check_limit_event(log: EvalLog, type: str) -> None:
    event = find_limit_event(log)
    assert event is not None, f"Limit event '{type}' not found in log"
    assert type == event.type


def find_limit_event(log: EvalLog) -> SampleLimitEvent | None:
    if log.samples:
        return next(
            (
                event
                for event in log.samples[0].events
                if isinstance(event, SampleLimitEvent)
            ),
            None,
        )
    else:
        return None
