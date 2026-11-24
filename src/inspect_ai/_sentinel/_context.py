from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, NamedTuple

from ._config import SentinelRoot
from ._scope import current_origin, in_final_scope, is_agent_turn


class SentinelFailure(Exception):
    """A sentinel's monitor or protocol failed, so a step went unchecked.

    It fails the sample, unless `error` is a limit or a termination, which keep
    their meaning. It is an ordinary `Exception`, so a scaffold or tool that
    catches `Exception` around an agent catches it too, but that doesn't let
    the agent carry on: the first one raised in a sample's solve is kept
    (`sentinel_failed()`), every later sentinel check, model generate and
    checked tool call in the solve raises it again, and the solve ends with it
    even if the solvers return. A limit or a termination is not kept.

    Args:
        error: What the monitor or protocol raised.
    """

    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


class _Latch:
    """The sentinel failure kept for one solve, once there is one."""

    def __init__(self) -> None:
        self.failure: SentinelFailure | None = None

    def again(self) -> SentinelFailure:
        """A new `SentinelFailure` for the kept failure's error.

        Raising a new one leaves the error's traceback where it was first
        raised, which is the traceback the sample records.
        """
        assert self.failure is not None
        failure = SentinelFailure(self.failure.error)
        failure.__cause__ = self.failure.error
        return failure


_latch: "ContextVar[_Latch | None]" = ContextVar("sentinel_failure", default=None)


@contextmanager
def sentinel_failure_latch() -> Iterator[None]:
    """Keep the first sentinel failure of a sample's solve, and end the solve with it.

    The sample runner enters it around the solvers of each attempt, so a retry
    or another epoch starts with none kept. Tasks the solvers start (a
    background agent, an agent bridge's service) share it. A solve that
    returns, or ends with another error, once a failure is kept raises the
    kept failure instead. A cancellation passes through unchanged.
    """
    latch = _Latch()
    token = _latch.set(latch)
    try:
        yield
    except Exception as ex:
        if latch.failure is None or (
            isinstance(ex, SentinelFailure) and ex.error is latch.failure.error
        ):
            raise
        raise latch.again() from ex
    finally:
        _latch.reset(token)
    if latch.failure is not None:
        raise latch.again()


def fails_the_sample(failure: SentinelFailure) -> bool:
    """Whether `failure` fails the sample: its deciding error is not a limit or a termination."""
    from inspect_ai._util.exception import TerminateSampleError
    from inspect_ai.model._call_tools import decisive_sentinel_exception
    from inspect_ai.util._limit import LimitExceededError

    decisive = decisive_sentinel_exception(failure.error)
    return not isinstance(decisive, (LimitExceededError, TerminateSampleError))


def sentinel_failed(failure: SentinelFailure) -> None:
    """Keep `failure` for the solve, if it fails the sample and none is kept yet."""
    latch = _latch.get()
    if latch is not None and latch.failure is None and fails_the_sample(failure):
        latch.failure = failure


def raise_if_sentinel_failed() -> None:
    """Raise the solve's kept sentinel failure again, if there is one.

    Nothing is raised inside a final scope (a sentinel's own run, an approver,
    a reviewer, a scorer, a `model_origin()` region, ...), where no sentinel
    checks the steps taken.

    Raises:
        SentinelFailure: The kept failure.
    """
    latch = _latch.get()
    if latch is not None and latch.failure is not None and not in_final_scope():
        raise latch.again()


class _ActiveSentinel(NamedTuple):
    root: "SentinelRoot"
    task_metadata: dict[str, Any]
    task_description: str | None


_active_sentinel: "ContextVar[_ActiveSentinel | None]" = ContextVar(
    "active_sentinel", default=None
)


def init_sentinel(
    root: "SentinelRoot | None",
    task_metadata: dict[str, Any] | None = None,
    task_description: str | None = None,
) -> None:
    _active_sentinel.set(
        _ActiveSentinel(root, task_metadata or {}, task_description)
        if root is not None
        else None
    )


def active_sentinel() -> "SentinelRoot | None":
    active = _active_sentinel.get()
    return active.root if active is not None else None


def active_task_metadata() -> dict[str, Any]:
    active = _active_sentinel.get()
    return active.task_metadata if active is not None else {}


def active_task_description() -> str | None:
    active = _active_sentinel.get()
    return active.task_description if active is not None else None


def is_agent_generate() -> bool:
    return active_sentinel() is not None and is_agent_turn(current_origin())


def checks_tool_calls() -> bool:
    # tool calls inside a final scope (a sentinel run, an approver, a reviewer,
    # ...) are not checked, or a monitor that runs a tool would be checked by
    # its own sentinel
    return active_sentinel() is not None and not in_final_scope()
