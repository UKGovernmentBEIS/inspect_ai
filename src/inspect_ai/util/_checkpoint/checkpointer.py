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
from collections.abc import AsyncIterator, Sequence
from contextvars import ContextVar
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    # Type-checking only: importing `ChatMessage` eagerly here pulls in
    # `inspect_ai.model._chat_message` → `inspect_ai.tool`, which is
    # mid-load when this module is first reached during
    # `inspect_ai.util.__init__` (the tool package triggers util via
    # `_json`). `from __future__ import annotations` above means the
    # name is only needed by the type-checker, not at runtime.
    from inspect_ai.model._chat_message import ChatMessage


class Checkpointer(Protocol):
    """The session yielded by ``async with checkpointer() as cp:``."""

    async def tick(self, messages: Sequence[ChatMessage]) -> None:
        """Invoke at each turn boundary; may fire a checkpoint.

        ``messages`` is the agent's current conversation — the source of
        the messages written into ``context.json`` if this tick fires.
        """
        ...

    async def checkpoint(self, messages: Sequence[ChatMessage]) -> None:
        """Force a fire regardless of policy (used by manual triggers).

        ``messages`` is the agent's current conversation — same role as
        in :meth:`tick`.
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
