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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Protocol

if TYPE_CHECKING:
    # Type-checking only: importing `ChatMessage` eagerly here pulls in
    # `inspect_ai.model._chat_message` → `inspect_ai.tool`, which is
    # mid-load when this module is first reached during
    # `inspect_ai.util.__init__` (the tool package triggers util via
    # `_json`). `from __future__ import annotations` above means the
    # name is only needed by the type-checker, not at runtime.
    from inspect_ai.model._chat_message import ChatMessage


@dataclass(frozen=True)
class ResumeInfo:
    """Returned by :meth:`Checkpointer.resume` on a retry/resumption.

    ``state`` is the dict the agent persisted via its
    :meth:`Checkpointer.on_checkpoint` callback in the prior run, or
    ``{}`` when the prior run did not register a callback (no
    ``agent_state.json`` on disk).
    """

    state: dict[str, Any] = field(default_factory=dict)


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

    def on_checkpoint(self, callback: Callable[[], dict[str, Any]]) -> None:
        """Register a callback invoked at each checkpoint fire.

        The returned dict is the agent's property bag, serialized as
        ``agent_state.json`` in the host snapshot. Subsequent calls
        replace any prior callback. The file is written only when a
        callback is registered — its presence on disk signals that the
        agent opted in.
        """
        ...

    def resume(self) -> ResumeInfo | None:
        """Return resume info for this sample, or ``None`` on a fresh run.

        Call this immediately after entering the checkpointer context to
        detect retry/resumption and (if applicable) recover prior state.

        - ``None`` — this sample is not a retry/resumption (fresh run).
        - :class:`ResumeInfo` — this is a retry/resumption. Its
          ``state`` field is the dict the agent persisted via
          :meth:`on_checkpoint` in the prior run, or ``{}`` if no
          callback was registered (no ``agent_state.json`` on disk).

        Truthiness is reliable: ``if resumed:`` distinguishes resume
        from fresh runs regardless of whether ``state`` is empty.
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
