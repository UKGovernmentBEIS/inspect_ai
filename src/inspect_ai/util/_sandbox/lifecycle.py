"""Mutable state a sandbox provider shares across one eval batch.

The run-level sandbox owner (``SandboxManager`` in ``_eval/run.py``) opens a
scope before any task or sample of its batch starts and closes it after its
final ``task_cleanup`` pass. A provider keeps the registries its cleanup needs
(running containers, generated config files) on the state the scope owns, so a
``task_init`` that runs late — in a ``SampleSource`` feeder task, a sibling of
the samples — mutates the object every task of the batch inherited, rather
than binding a ``ContextVar`` that only its own task can see.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, TypeVar

T = TypeVar("T")


class SandboxLifecycleState:
    """Per-provider state for one sandbox lifecycle scope, keyed by state class."""

    def __init__(self) -> None:
        self._state: dict[type[object], object] = {}

    def get(self, cls: type[T]) -> T:
        """The scope's instance of ``cls``, constructed without arguments on first use."""
        state = self._state.get(cls)
        if not isinstance(state, cls):
            state = cls()
            self._state[cls] = state
        return state


_lifecycle_state: ContextVar[SandboxLifecycleState | None] = ContextVar(
    "sandbox_lifecycle_state", default=None
)


@contextmanager
def sandbox_lifecycle_scope() -> Iterator[SandboxLifecycleState]:
    """Own fresh provider state for the block; tasks spawned inside inherit it.

    Enter and exit in the same task: the exit resets the binding via its token,
    so the enclosing context is left exactly as it was (a sequential batch that
    follows starts from no scope, and opens its own).
    """
    state = SandboxLifecycleState()
    token = _lifecycle_state.set(state)
    try:
        yield state
    finally:
        _lifecycle_state.reset(token)


def sandbox_lifecycle_state() -> SandboxLifecycleState | None:
    """The enclosing scope's state, or ``None`` outside any scope."""
    return _lifecycle_state.get()
