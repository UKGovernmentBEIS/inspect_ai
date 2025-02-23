import time
from contextvars import ContextVar


def init_sample_working_limit(start_time: float, working_limit: float | None) -> None:
    _sample_working_limit.set(working_limit)
    _sample_start_time.set(start_time)
    _sample_waiting_time.set(0)


def sample_waiting_time() -> float:
    return _sample_waiting_time.get()


def report_sample_waiting_time(waiting_time: float) -> None:
    _sample_waiting_time.set(_sample_waiting_time.get() + waiting_time)
    check_sample_working_limit()


def check_sample_working_limit() -> None:
    # no check if we don't have a limit
    working_limit = _sample_working_limit.get()
    if working_limit is None:
        return

    # are we over the limit?
    running_time = time.monotonic() - _sample_start_time.get()
    working_time = running_time - sample_waiting_time()
    if working_time > working_limit:
        from inspect_ai.solver._limit import SampleLimitExceededError

        raise SampleLimitExceededError(
            type="working",
            value=int(working_time),
            limit=int(working_limit),
            message=f"Exceeded working time limit ({working_limit:,} seconds)",
        )


_sample_working_limit: ContextVar[float | None] = ContextVar(
    "sample_working_limit", default=None
)

_sample_start_time: ContextVar[float] = ContextVar("sample_start_time", default=0)

_sample_waiting_time: ContextVar[float] = ContextVar("sample_waiting_time", default=0)
