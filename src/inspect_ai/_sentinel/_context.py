from contextvars import ContextVar

from ._config import SentinelRoot

_active_sentinel: "ContextVar[SentinelRoot | None]" = ContextVar(
    "active_sentinel", default=None
)


def init_sentinel(root: "SentinelRoot | None") -> None:
    _active_sentinel.set(root)


def active_sentinel() -> "SentinelRoot | None":
    return _active_sentinel.get()
