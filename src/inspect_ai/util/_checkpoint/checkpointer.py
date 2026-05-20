"""Checkpoint session protocol and ``checkpointer()`` factory.

Kept deliberately light so that this module can be imported eagerly
from ``inspect_ai.util._checkpoint/__init__.py`` and ``inspect_ai.util``
without triggering the heavy ``log``/``solver``/``model`` chain that
the active-session implementation in :mod:`.checkpointer` pulls in
(that chain loops back to ``inspect_ai.dataset.Sample`` and breaks
during initial package load otherwise).

The factory defers the import of the heavy build function to call
time, so the cycle never arises in practice.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import Callable, Protocol, TypeVar

T = TypeVar("T")


class Checkpointer(Protocol):
    """The session yielded by ``async with checkpointer() as cp:``."""

    async def tick(self) -> None:
        """Invoke at each turn boundary; may fire a checkpoint.

        Triggered by the agent at points where a checkpoint is
        permissible. State persisted at the fire is whatever the agent
        has registered via :meth:`track`.
        """
        ...

    async def checkpoint(self) -> None:
        """Force a fire regardless of policy (used by manual triggers)."""
        ...

    def track(
        self,
        key: str,
        callback: Callable[[], T],
        initial_value: T,
    ) -> T:
        """Track ``key`` as part of the agent's checkpointed state.

        ``callback`` is invoked at every checkpoint fire to capture
        the value of the tracked state. On a retry of this sample, the
        captured value is returned; on a fresh run, ``initial_value``
        is returned.

        Generic over ``T``. The runtime contract on the captured value
        is "any value that ``pydantic_core.to_jsonable_python`` can
        serialize" — JSON primitives, lists, dicts, Pydantic models,
        dataclasses, and arbitrary nesting of these.

        A key may be tracked only once per session; a duplicate call
        raises ``ValueError``.
        """
        ...


# Set by `checkpointer()` for either impl, so free functions (e.g. the
# manual `checkpoint()` trigger) get back whichever session is active
# — including the no-op one. Outside any `checkpointer()` context,
# lookups return None.
_active_checkpointer: ContextVar[Checkpointer | None] = ContextVar(
    "inspect_ai_active_checkpointer", default=None
)


@contextlib.asynccontextmanager
async def checkpointer() -> AsyncIterator[Checkpointer]:
    """Enter a checkpointer for the current sample.

    Picks one of two concrete impls on entry: a no-op session when the
    active sample has no checkpoint config (or no sample is active at
    all), or an active session bound to the current sample. Either
    way, the yielded object satisfies :class:`CheckpointSession` and
    is registered as the active session for the current async context.

    The resolved :class:`CheckpointConfig` lives on
    :class:`inspect_ai.log._samples.ActiveSample` — installed by the
    harness at sample-run setup time per eval / task / sample
    precedence. Agents do not pass a config here.
    """
    # Function-scoped import of the heavy build function: keeps this
    # module light enough to be imported during initial inspect_ai load
    # without triggering the dataset/Sample cycle.
    from .checkpointer_impl import build_impl

    impl = await build_impl()
    token = _active_checkpointer.set(impl)
    try:
        yield impl
    finally:
        _active_checkpointer.reset(token)
