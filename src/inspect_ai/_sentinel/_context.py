from contextvars import ContextVar
from typing import Any, NamedTuple

from ._config import SentinelRoot


class _ActiveSentinel(NamedTuple):
    root: "SentinelRoot"
    task_metadata: dict[str, Any]


_active_sentinel: "ContextVar[_ActiveSentinel | None]" = ContextVar(
    "active_sentinel", default=None
)


def init_sentinel(
    root: "SentinelRoot | None", task_metadata: dict[str, Any] | None = None
) -> None:
    _active_sentinel.set(
        _ActiveSentinel(root, task_metadata or {}) if root is not None else None
    )


def active_sentinel() -> "SentinelRoot | None":
    active = _active_sentinel.get()
    return active.root if active is not None else None


def active_task_metadata() -> dict[str, Any]:
    active = _active_sentinel.get()
    return active.task_metadata if active is not None else {}
