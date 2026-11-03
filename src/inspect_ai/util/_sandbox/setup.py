"""Where a sandbox provider's task-level setup and cleanup run.

Inspect calls a provider's ``task_init_environment``, ``task_init`` and
``task_cleanup`` for a task's sandbox config without changing the process's
working directory or environment variables, which every running task shares.
Instead, while those calls run, :func:`sandbox_setup` returns the task's
directory and the environment variables the provider's
``task_init_environment`` returned for the call, and
:func:`~inspect_ai.util.subprocess` applies them to the child processes it
starts (as their default working directory and extra environment variables).
A provider that resolves relative paths in Python during setup can read the
task directory from :func:`sandbox_setup`.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from inspect_ai.util._subprocess import CircularByteBuffer


@dataclass(frozen=True)
class SandboxSetup:
    """The task a sandbox provider's setup or cleanup call is for."""

    task_dir: str
    """The task's directory (where its task file is), absolute."""

    env: dict[str, str] = field(default_factory=dict)
    """Environment variables for the call's child processes (for ``task_init``,
    what the provider's ``task_init_environment`` returned)."""

    output: "CircularByteBuffer | None" = None
    """When set, the output of child processes that would go to the terminal
    is collected here instead (so it can be shown if the setup fails); the
    buffer keeps only its most recent bytes."""


class _Scope:
    """The setup a scope makes current, until the scope ends.

    Mutable, so that work started during the call (background tasks copy the
    context) stops seeing the setup when the call ends.
    """

    def __init__(self, setup: SandboxSetup) -> None:
        self.setup: SandboxSetup | None = setup


_sandbox_setup: ContextVar[_Scope | None] = ContextVar("sandbox_setup", default=None)


def sandbox_setup() -> SandboxSetup | None:
    """The task the current sandbox setup or cleanup call is for.

    Returns ``None`` outside a provider's ``task_init_environment``,
    ``task_init`` and ``task_cleanup`` (for example in ``sample_init``, or in
    background work such a call started, once the call has returned).
    """
    scope = _sandbox_setup.get()
    return scope.setup if scope is not None else None


@contextmanager
def sandbox_setup_scope(setup: SandboxSetup) -> Iterator[None]:
    """Make ``setup`` the current sandbox setup for the block."""
    scope = _Scope(setup)
    token = _sandbox_setup.set(scope)
    try:
        yield
    finally:
        scope.setup = None
        _sandbox_setup.reset(token)
