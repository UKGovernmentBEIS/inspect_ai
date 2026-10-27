from contextvars import ContextVar
from typing import Any, NamedTuple

from ._config import SentinelRoot
from ._scope import AgentScope, current_scope, in_final_scope, solving


class SentinelFailure(Exception):
    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


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
    return (
        active_sentinel() is not None and solving() and current_scope() is AgentScope.ON
    )


def checks_tool_calls() -> bool:
    # tool calls inside a final scope (a sentinel run, an approver, a reviewer,
    # ...) are not checked, or a monitor that runs a tool would be checked by
    # its own sentinel
    return active_sentinel() is not None and not in_final_scope()
