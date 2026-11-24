from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, NamedTuple

from ._config import SentinelRoot
from ._scope import (
    current_origin,
    current_sentinel_run,
    in_final_scope,
    in_sentinel_run,
    is_agent_turn,
)


class SentinelFailure(Exception):
    """A sentinel's monitor or protocol failed, so a step went unchecked.

    It fails the sample, unless `error` is a limit or a termination, which keep
    their meaning. It is an ordinary `Exception`, so a scaffold or tool that
    catches `Exception` around an agent catches it too, but that doesn't let
    the agent carry on: the first one raised in a sample attempt is kept
    (`SentinelFailures`). Every later model generate, provider dispatch, tool
    call and sentinel check in the attempt raises it again, except the
    sentinel's own, and the attempt ends with it even if the solvers return
    or its background tasks catch it. A limit or a termination is not kept.

    Args:
        error: What the monitor or protocol raised.
    """

    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


class SentinelFailures:
    """The sentinel failure kept for one attempt of a sample, once there is one."""

    def __init__(self) -> None:
        self.failure: SentinelFailure | None = None

    def keep(self, failure: SentinelFailure) -> None:
        """Keep `failure`, if it fails the sample and none is kept yet."""
        if self.failure is None and fails_the_sample(failure):
            self.failure = failure

    def again(self) -> SentinelFailure:
        """A new `SentinelFailure` for the kept failure's error.

        Raising a new one leaves the error's traceback where it was first
        raised, which is the traceback the sample records.
        """
        assert self.failure is not None
        failure = SentinelFailure(self.failure.error)
        failure.__cause__ = self.failure.error
        return failure

    def raise_if_failed(self) -> None:
        """Raise the kept failure again, if there is one.

        Raises:
            SentinelFailure: The kept failure.
        """
        if self.failure is not None:
            raise self.again()

    def raise_instead_of(self, ex: BaseException) -> None:
        """Raise the kept failure from `ex`, if there is one and `ex` isn't it.

        Raises:
            SentinelFailure: The kept failure.
        """
        if self.failure is not None and not (
            isinstance(ex, SentinelFailure) and ex.error is self.failure.error
        ):
            raise self.again() from ex


_failures: "ContextVar[SentinelFailures | None]" = ContextVar(
    "sentinel_failures", default=None
)


@contextmanager
def sentinel_failures() -> Iterator[SentinelFailures]:
    """Keep the first sentinel failure of one sample attempt.

    The sample runner enters it around the attempt's task group, which runs the
    solvers and every task they start (`background()`, a deepagent's
    background subagents, an agent bridge's service), so they share it, and
    checks it when the group has finished. Scoring and teardown run after it
    exits, and a retry or another epoch gets a new one.
    """
    failures = SentinelFailures()
    token = _failures.set(failures)
    try:
        yield failures
    finally:
        _failures.reset(token)


@contextmanager
def sentinel_failure_latch() -> Iterator[None]:
    """End the solvers with the attempt's kept sentinel failure (`sentinel_failures()`).

    Solvers that return, or end with another error, once a failure is kept
    raise the kept failure instead. A cancellation passes through unchanged.
    """
    failures = _failures.get()
    if failures is None:
        yield
        return
    try:
        yield
    except Exception as ex:
        failures.raise_instead_of(ex)
        raise
    failures.raise_if_failed()


def fails_the_sample(failure: SentinelFailure) -> bool:
    """Whether `failure` fails the sample: its deciding error is not a limit or a termination."""
    from inspect_ai._util.exception import TerminateSampleError
    from inspect_ai.model._call_tools import decisive_sentinel_exception
    from inspect_ai.util._limit import LimitExceededError

    decisive = decisive_sentinel_exception(failure.error)
    return not isinstance(decisive, (LimitExceededError, TerminateSampleError))


def sentinel_failed(failure: SentinelFailure) -> None:
    """Keep `failure` for the sample attempt (`SentinelFailures.keep`)."""
    failures = _failures.get()
    if failures is not None:
        failures.keep(failure)


def raise_if_sentinel_failed() -> None:
    """Raise the attempt's kept sentinel failure again, if there is one.

    Called before every model generate, provider dispatch, tool call and
    sentinel check, and again after each wait before the dispatch or the
    call. Whether a sentinel checks a step (a final scope such as
    `model_origin()`, an approver or a scorer is not checked) doesn't matter:
    once the sample has failed, no step runs. The sentinel's own monitors and
    protocols are the exception while they run (`in_sentinel_run()`), so a
    check already running finishes, but work they started that outlives them
    is refused.

    Raises:
        SentinelFailure: The kept failure.
    """
    failures = _failures.get()
    if failures is not None and failures.failure is not None and not in_sentinel_run():
        raise failures.again()


def sentinel_refusal() -> Callable[[], SentinelFailure | None]:
    """This context's kept failure check, to make later from another context.

    For a request this context queues and another task sends, such as a
    provider batch: called immediately before the request is sent, it returns
    the failure `raise_if_sentinel_failed()` would raise here then, or `None`.
    """
    failures = _failures.get()
    if failures is None:
        return _no_refusal
    run = current_sentinel_run()

    def refusal() -> SentinelFailure | None:
        if failures.failure is None or (run is not None and run.active):
            return None
        return failures.again()

    return refusal


def _no_refusal() -> SentinelFailure | None:
    return None


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
