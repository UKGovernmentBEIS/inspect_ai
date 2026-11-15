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


# set while a bridged request an agent classified as utility is in flight,
# and the value the innermost bridged request started from
_utility_request: ContextVar[bool] = ContextVar(
    "sentinel_utility_request", default=False
)
_utility_request_outer: ContextVar[bool | None] = ContextVar(
    "sentinel_utility_request_outer", default=None
)

UTILITY_REQUEST_ORIGIN: ModelOrigin = "helper"
"""The origin of an agent-turn call made in a bridged request classified as utility."""


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
    """The origin of a model call made here: the innermost region's kind, `"setup"` for an agent call outside the solve.

    An agent call (not in a final region) in a bridged request classified as utility is `UTILITY_REQUEST_ORIGIN`'s.
    """
    scope = _scope.get()
    if scope.origin != "agent":
        return scope.origin
    if not solving():
        return "setup"
    if not scope.final and _utility_request.get():
        return UTILITY_REQUEST_ORIGIN
    return "agent"


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


@contextmanager
def utility_request_scope() -> Iterator[None]:
    """Bound `set_utility_request()` to one bridged request.

    A request nested in a utility request stays utility whatever its own kind.
    """
    outer = _utility_request.get()
    token = _utility_request.set(outer)
    outer_token = _utility_request_outer.set(outer)
    try:
        yield
    finally:
        _utility_request_outer.reset(outer_token)
        _utility_request.reset(token)


def set_utility_request(utility: bool) -> None:
    """Classify the bridged request in flight as utility, or not; no-op outside one.

    Read when a call's origin is resolved (`current_origin()`), so a region entered or left after this call (a span, `model_origin()`, a tool) neither loses it nor is overridden by it.
    """
    outer = _utility_request_outer.get()
    if outer is not None:
        _utility_request.set(outer or utility)
