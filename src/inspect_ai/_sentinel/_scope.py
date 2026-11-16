from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal, NamedTuple

import anyio

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
    "utility",
]
"""Where a model call was made (`ModelEvent.origin`); only `"agent"` is an agent turn.

`"utility"` is a bridged request's call that its agent classified as utility (`set_agent_bridge_context()`): not an agent turn, but checked by sentinels as one (`is_checked_turn()`).
"""


class _Scope(NamedTuple):
    origin: ModelOrigin
    final: bool


# the phase fence: model calls are agent turns only while the solvers run
_solving: ContextVar[bool] = ContextVar("sentinel_solving", default=False)
_scope: ContextVar[_Scope] = ContextVar(
    "sentinel_scope", default=_Scope("agent", False)
)


@dataclass
class _UtilityRequest:
    """One bridged request's utility classification, shared with the tasks it spawns.

    Shared rather than copied, so a task spawned during the request sees the
    classification change on a later attempt and lapse when the request ends.
    """

    outer: "_UtilityRequest | None"
    task: object
    utility: bool = False
    active: bool = True

    def live(self) -> bool:
        """Whether calls made under this request are utility's: it or a request it is nested in is classified so, while in flight."""
        return self.active and (
            self.utility or (self.outer is not None and self.outer.live())
        )


# the innermost bridged request in flight
_utility_request: ContextVar[_UtilityRequest | None] = ContextVar(
    "sentinel_utility_request", default=None
)

UTILITY_REQUEST_ORIGIN: ModelOrigin = "utility"
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
    request = _utility_request.get()
    if not scope.final and request is not None and request.live():
        return UTILITY_REQUEST_ORIGIN
    return "agent"


def is_agent_turn(origin: str | None) -> bool:
    """Whether a model call with this origin is one of its conversation's agent turns.

    The one rule, live and from a log: a kind added later reads as not a turn.
    """
    return origin == "agent"


def is_checked_turn(origin: str | None) -> bool:
    """Whether a sentinel checks a model call with this origin at its generate stages, live and in replay.

    An agent turn, or a call its bridged agent classified as utility: the classification comes from the agent's own requests, so it shapes the timeline but does not exempt the call from monitoring.
    """
    return origin in ("agent", "utility")


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

    A request nested in a utility request stays utility whatever its own kind. When the request ends, its classification no longer applies anywhere, including in tasks it spawned.
    """
    request = _UtilityRequest(_utility_request.get(), _current_task())
    token = _utility_request.set(request)
    try:
        yield
    finally:
        request.active = False
        _utility_request.reset(token)


def set_utility_request(utility: bool) -> None:
    """Classify the bridged request in flight as utility, or not.

    Read when a call's origin is resolved (`current_origin()`), so a region entered or left after this call (a span, `model_origin()`, a tool) neither loses it nor is overridden by it. Only the task handling the request classifies it, as only there does `set_agent_bridge_context()` reach the request; elsewhere, and outside a request, this is a no-op.
    """
    request = _utility_request.get()
    if request is not None and request.active and request.task == _current_task():
        request.utility = utility


def _current_task() -> object:
    try:
        return anyio.get_current_task().id
    except RuntimeError:
        # no event loop (synchronous code): one task at most
        return None
