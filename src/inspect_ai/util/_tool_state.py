from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


@contextmanager
def tool_state_scope(name: str) -> Iterator[None]:
    """Give tool state at the default instance its own scope.

    Built-in tools that keep state in the sample store (`memory()`,
    `bash_session()`, `web_browser()` and `skill()`) use the scope name as
    their instance when their `instance` is left at `None`. Agents that run
    concurrently in one sample can each run inside their own scope to get
    their own memory, shell, browser and skills. A tool given an explicit
    `instance` is not affected, so agents that pass the same instance still
    share that state.

    Nested scopes join their names with "/" (`"outer/inner"`). The scope is
    held in a context variable, so tasks started inside the block inherit it
    and tasks started outside it do not see it.

    Args:
       name: Scope name. Must be non-empty and must not contain "/".

    Raises:
       ValueError: If `name` is empty or contains "/".
    """
    if not name or "/" in name:
        raise ValueError(
            f"Tool state scope name must be non-empty and must not contain '/' (got {name!r})."
        )
    outer = _tool_state_scope.get()
    token = _tool_state_scope.set(f"{outer}/{name}" if outer is not None else name)
    try:
        yield
    finally:
        _tool_state_scope.reset(token)


def tool_state_instance(instance: str | None) -> str | None:
    """Resolve a tool's `instance` argument against the current tool state scope.

    Stateful tools call this on each call and pass the result to `store_as()`
    (and use it for any other per-instance key). See `tool_state_scope()`.

    Args:
       instance: Instance chosen by the tool's user, or `None` for the default.

    Returns:
       `instance` if it is not `None`. Otherwise the current scope's name,
       or `None` outside any scope.
    """
    if instance is not None:
        return instance
    return _tool_state_scope.get()


def private_tool_instance(name: str) -> str:
    """Instance for tool state that a library names itself.

    Use this when library code gives a tool an explicit instance of its own
    (for example, one per subagent type) and that state must stay private to
    the current tool state scope. See `tool_state_scope()`.

    Args:
       name: Instance name chosen by the library.

    Returns:
       `"<scope>/<name>"` inside a scope, or `name` outside one.
    """
    scope = _tool_state_scope.get()
    return f"{scope}/{name}" if scope is not None else name


_tool_state_scope: ContextVar[str | None] = ContextVar("tool_state_scope", default=None)
