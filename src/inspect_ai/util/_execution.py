import contextlib
import time
from contextvars import ContextVar
from logging import getLogger
from typing import Iterator

from inspect_ai._util.trace import trace_action

logger = getLogger(__name__)


@contextlib.contextmanager
def working(trace: str | None = None) -> Iterator[None]:
    """Context manager to denote a sample execution action.

    `execution_time` is reported for each sample (and samples can
    be subject to an `working_limit`). By default, model generation
    and subprocess exeuction count as execution time. This context
    manager allows for classification of other code as execution time.

    Args:
       trace: Optional trace action (will cause the code to be
         tracked and logged by the trace manager)
    """
    start_time = time.monotonic()
    try:
        if trace is not None:
            with trace_action(logger, trace, trace):
                yield
        else:
            yield
    finally:
        working_time(time.monotonic() - start_time)


def working_time(time: float) -> None:
    """Report sample execution time.

    `execution_time` is reported for each sample (and samples can
    be subject to an `working_limit`). By default, model generation
    and subprocess exeuction count as execution time. This function
    allows for reporting of additional execution time.

    Args:
      time: Seconds of exeuction time.
    """
    # ignore if there is no limit
    working_limit = _sample_working_limit.get()
    if working_limit is None:
        return

    # update execution time
    working = _sample_working_time.get() + time
    _sample_working_time.set(working)

    # are we over the limit?
    if working >= working_limit:
        from inspect_ai.solver._limit import SampleLimitExceededError

        raise SampleLimitExceededError(
            type="execution",
            value=int(working),
            limit=int(working_limit),
            message=f"Exceeded execution time limit ({working_limit:,} seconds)",
        )


def init_sample_working_limit(working_limit: float | None) -> None:
    _sample_working_limit.set(working_limit)


def sample_working_time() -> float:
    return _sample_working_time.get()


_sample_working_limit: ContextVar[float | None] = ContextVar(
    "sample_working_limit", default=None
)
_sample_working_time: ContextVar[float] = ContextVar("sample_working_time", default=0)
