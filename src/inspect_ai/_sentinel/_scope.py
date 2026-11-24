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

# the name of an agent bridge's tool-stage check span (type `sentinel`), which
# replay never assigns to a native call
BRIDGE_CHECK_SPAN = "sentinel_bridge"


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


class SentinelRun:
    """A sentinel's monitor or protocol run, active until the run returns or raises.

    Tasks started and contexts copied inside the run share it, so it ends for
    them too when the run does, however long they keep running.
    """

    def __init__(self) -> None:
        self.active = True


_run: ContextVar[SentinelRun | None] = ContextVar("sentinel_run", default=None)


@contextmanager
def sentinel_run() -> Iterator[None]:
    """Run a sentinel's monitor or protocol: model calls in it have the sentinel origin, and it is `in_sentinel_run()` until it exits."""
    run = SentinelRun()
    token = _run.set(run)
    try:
        with sentinel_scope("sentinel", final=True):
            yield
    finally:
        run.active = False
        _run.reset(token)


def current_sentinel_run() -> SentinelRun | None:
    """The sentinel run this context was started in, active or ended, if any."""
    return _run.get()


def in_sentinel_run() -> bool:
    """Whether this is a sentinel's own monitor or protocol run, while it runs.

    Only the dispatcher enters one (`sentinel_run()`). A task the run started,
    or a context copied in it, is in it only until the run ends.
    """
    run = _run.get()
    return run is not None and run.active


def enter_scope(origin: ModelOrigin, *, final: bool = False) -> Token[_Scope]:
    # innermost wins, except that nothing inside a final scope changes it
    current = _scope.get()
    return _scope.set(current if current.final else _Scope(origin, final))


def exit_scope(token: Token[_Scope]) -> None:
    _scope.reset(token)
