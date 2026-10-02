from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, NamedTuple

from inspect_ai.util._span import current_agent_span_id

from ._config import SentinelRoot


class SentinelFailure(Exception):
    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


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


_solving: ContextVar[bool] = ContextVar("sentinel_solving", default=False)
_not_agent: ContextVar[bool] = ContextVar("sentinel_not_agent", default=False)
_NO_TOOL = object()
# the agent span a tool's body runs in: a generate in that span is the tool's own
_tool_agent_span: ContextVar[object] = ContextVar(
    "sentinel_tool_agent_span", default=_NO_TOOL
)


@contextmanager
def sentinel_solving() -> Iterator[None]:
    token = _solving.set(True)
    try:
        yield
    finally:
        _solving.reset(token)


@contextmanager
def not_agent_generates() -> Iterator[None]:
    token = _not_agent.set(True)
    try:
        yield
    finally:
        _not_agent.reset(token)


@contextmanager
def sentinel_tool_body() -> Iterator[None]:
    token = _tool_agent_span.set(current_agent_span_id())
    try:
        yield
    finally:
        _tool_agent_span.reset(token)


def is_agent_generate(is_active_model: bool) -> bool:
    if not is_active_model or active_sentinel() is None:
        return False
    if not _solving.get() or _not_agent.get():
        return False
    tool_span = _tool_agent_span.get()
    return tool_span is _NO_TOOL or tool_span != current_agent_span_id()
