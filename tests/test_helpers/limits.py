from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import SampleLimitEvent


def check_limit_event(log: EvalLog, content: str) -> None:
    event = find_limit_event(log)
    assert event
    assert content == event.type


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
