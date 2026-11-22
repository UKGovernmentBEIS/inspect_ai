"""Mark sandbox operations as Inspect's own, so they keep the default user.

A leaf module (it imports only the standard library), so every helper that
issues sandbox operations can import it without an import cycle.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


@contextmanager
def framework_sandbox_operation() -> Iterator[None]:
    """Mark sandbox operations in the block as Inspect's own.

    Inside the block, `exec()`, `read_file()` and `write_file()` calls that name
    no user run as the sandbox's default user even inside a `sandbox_identity()`
    scope. Only the boundary default is affected: the scope, injection
    targeting, the sandbox-tools request user and the model-facing tools' strict
    resolution are unchanged.

    Wrap only calls whose `user=None` means the sandbox's default user, and
    never code that runs model-chosen work. The one deliberate exception is
    in-loop scoring: `score()` wraps the task's scorer, which may execute
    submitted code as the default user.

    The mark is held in a context variable, so tasks started inside the block
    inherit it. Opening a `sandbox_identity()` scope inside the block raises
    `SandboxIdentityError`, so a scorer cannot open one during in-loop scoring.
    """
    token = _framework_operation.set(True)
    try:
        yield
    finally:
        _framework_operation.reset(token)


def in_framework_sandbox_operation() -> bool:
    """Whether the current context is inside `framework_sandbox_operation()`."""
    return _framework_operation.get()


_framework_operation: ContextVar[bool] = ContextVar(
    "sandbox_framework_operation", default=False
)
