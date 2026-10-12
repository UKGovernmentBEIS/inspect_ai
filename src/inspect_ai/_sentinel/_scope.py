from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from enum import Enum
from typing import NamedTuple


class AgentScope(Enum):
    OFF = "off"  # not an agent turn
    ACTIVE_MODEL = "active_model"  # an agent turn if on the sample's active model
    ANY_MODEL = "any_model"  # an agent turn on any model


class _Scope(NamedTuple):
    scope: AgentScope
    final: bool


# None outside every scope, which reads as OFF
_scope: ContextVar[_Scope | None] = ContextVar("sentinel_scope", default=None)


@contextmanager
def sentinel_scope(scope: AgentScope, *, final: bool = False) -> Iterator[None]:
    token = _enter(scope, final)
    try:
        yield
    finally:
        _scope.reset(token)


def current_scope() -> AgentScope:
    current = _scope.get()
    return current.scope if current is not None else AgentScope.OFF


def enter_agent_span() -> Token[_Scope | None] | None:
    # an agent span outside every scope (sample init, scoring) stays OFF
    if _scope.get() is None:
        return None
    return _enter(AgentScope.ANY_MODEL, False)


def exit_agent_span(token: Token[_Scope | None]) -> None:
    _scope.reset(token)


def _enter(scope: AgentScope, final: bool) -> Token[_Scope | None]:
    # innermost wins, except that nothing inside a final scope changes it
    current = _scope.get()
    if current is not None and current.final:
        return _scope.set(current)
    return _scope.set(_Scope(scope, final))
