from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from enum import Enum
from typing import NamedTuple


class AgentScope(Enum):
    ON = "on"  # a model call here is an agent turn
    OFF = "off"  # a model call here is not an agent turn


class _Scope(NamedTuple):
    scope: AgentScope
    final: bool


# the phase fence: model calls are agent turns only while the solvers run
_solving: ContextVar[bool] = ContextVar("sentinel_solving", default=False)
_scope: ContextVar[_Scope] = ContextVar(
    "sentinel_scope", default=_Scope(AgentScope.ON, False)
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
def sentinel_scope(scope: AgentScope, *, final: bool = False) -> Iterator[None]:
    token = enter_scope(scope, final=final)
    try:
        yield
    finally:
        exit_scope(token)


def current_scope() -> AgentScope:
    return _scope.get().scope


def in_final_scope() -> bool:
    return _scope.get().final


def enter_scope(scope: AgentScope, *, final: bool = False) -> Token[_Scope]:
    # innermost wins, except that nothing inside a final scope changes it
    current = _scope.get()
    return _scope.set(current if current.final else _Scope(scope, final))


def exit_scope(token: Token[_Scope]) -> None:
    _scope.reset(token)
