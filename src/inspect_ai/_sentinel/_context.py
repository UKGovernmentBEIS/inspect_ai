from contextvars import ContextVar
from typing import Any, NamedTuple

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.util._limit import LimitExceededError

from ._config import SentinelRoot
from ._scope import current_origin, in_final_scope, is_agent_turn


class SentinelFailure(Exception):
    """A sentinel monitor or protocol failed, which fails the sample.

    It leaves the sentinel's dispatch through `fail_sample()`, which ends the
    sample attempt even if code that catches this exception carries on.
    """

    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


def fail_sample(failure: SentinelFailure) -> None:
    """End the running sample attempt with `failure`, by cancelling it.

    A failure whose deciding error is a limit or a termination keeps that
    meaning and is not handled here. Outside a sample this does nothing.
    """
    # imported here: at module level they make an import cycle
    from inspect_ai.log._samples import sample_active
    from inspect_ai.model._call_tools import decisive_sentinel_exception

    decisive = decisive_sentinel_exception(failure.error)
    if isinstance(decisive, (LimitExceededError, TerminateSampleError)):
        return
    active = sample_active()
    if active is not None:
        active.sentinel_failed(failure)


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
