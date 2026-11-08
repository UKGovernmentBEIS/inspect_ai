from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Literal, NamedTuple

ModelOrigin = Literal[
    "agent",
    "environment",
    "helper",
    "tool",
    "compaction",
    "approval",
    "review",
    "sampling",
    "sentinel",
    "scorer",
    "setup",
]
"""Where a model call was made (`ModelEvent.origin`); only `"agent"` is an agent turn."""


class _Scope(NamedTuple):
    origin: ModelOrigin
    final: bool


# the phase fence: model calls are agent turns only while the solvers run
_solving: ContextVar[bool] = ContextVar("sentinel_solving", default=False)
_scope: ContextVar[_Scope] = ContextVar(
    "sentinel_scope", default=_Scope("agent", False)
)


@contextmanager
def sentinel_solving() -> Iterator[None]:
    token = _solving.set(True)
    try:
        yield
    finally:
        _solving.reset(token)


def solving() -> bool:
    return _solving.get()


@contextmanager
def sentinel_scope(origin: ModelOrigin, *, final: bool = False) -> Iterator[None]:
    token = enter_scope(origin, final=final)
    try:
        yield
    finally:
        exit_scope(token)


def current_origin() -> ModelOrigin:
    """The origin of a model call made here: the innermost region's kind, `"setup"` for an agent call outside the solve."""
    origin = _scope.get().origin
    return "setup" if origin == "agent" and not solving() else origin


def is_agent_turn(origin: str | None) -> bool:
    """Whether a model call with this origin is one of its conversation's agent turns.

    The one rule, live and from a log: a kind added later reads as not a turn.
    """
    return origin == "agent"


def in_final_scope() -> bool:
    return _scope.get().final


def enter_scope(origin: ModelOrigin, *, final: bool = False) -> Token[_Scope]:
    # innermost wins, except that nothing inside a final scope changes it
    current = _scope.get()
    return _scope.set(current if current.final else _Scope(origin, final))


def exit_scope(token: Token[_Scope]) -> None:
    _scope.reset(token)
