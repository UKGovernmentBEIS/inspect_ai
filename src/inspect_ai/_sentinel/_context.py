from contextvars import ContextVar
from logging import getLogger
from typing import Any, NamedTuple

from inspect_ai._util.logger import warn_once

from ._config import SentinelRoot

logger = getLogger(__name__)


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


def warn_sentinel_bridged() -> None:
    if active_sentinel() is not None:
        warn_once(
            logger,
            "Sentinels do not yet run for bridged agents (agent_bridge() and "
            "sandbox_agent_bridge()), so their model calls and tool calls are not "
            "monitored. See https://github.com/UKGovernmentBEIS/inspect_ai/issues/5759.",
        )
