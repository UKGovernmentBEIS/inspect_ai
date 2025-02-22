import contextlib
import time
from contextvars import ContextVar
from logging import getLogger
from typing import Iterator

from inspect_ai._util.trace import trace_action

logger = getLogger(__name__)


@contextlib.contextmanager
def execution(trace: str | None = None) -> Iterator[None]:
    """Context manager to denote a sample execution action.

    `execution_time` is reported for each sample (and samples can
    be subject to an `execution_limit`). By default, model generation
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
        execution_time(time.monotonic() - start_time)


def execution_time(time: float) -> None:
    """Report sample execution time.

    `execution_time` is reported for each sample (and samples can
    be subject to an `execution_limit`). By default, model generation
    and subprocess exeuction count as execution time. This function
    allows for reporting of additional execution time.

    Args:
      time: Seconds of exeuction time.
    """
    # ignore if there is no limit
    execution_limit = _sample_execution_limit.get()
    if execution_limit is None:
        return

    # update execution time
    executing = _sample_execution_time.get() + time
    _sample_execution_time.set(executing)

    # are we over the limit?
    if executing >= execution_limit:
        from inspect_ai.solver._limit import SampleLimitExceededError

        raise SampleLimitExceededError(
            type="execution",
            value=int(executing),
            limit=int(execution_limit),
            message=f"Exceeded execution time limit ({execution_limit:,} seconds)",
        )


def init_sample_execution_limit(execution_limit: float | None) -> None:
    _sample_execution_limit.set(execution_limit)


def sample_execution_time() -> float:
    return _sample_execution_time.get()


_sample_execution_limit: ContextVar[float | None] = ContextVar(
    "sample_execution_limit", default=None
)
_sample_execution_time: ContextVar[float] = ContextVar(
    "sample_execution_time", default=0
)
