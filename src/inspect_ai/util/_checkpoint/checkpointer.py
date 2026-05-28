"""Checkpoint session protocol and ``checkpointer()`` factory.

Kept deliberately light so that this module can be imported eagerly
from ``inspect_ai.util._checkpoint/__init__.py`` and ``inspect_ai.util``
without triggering the heavy ``log``/``solver``/``model`` chain that
the active-session implementation in :mod:`.checkpointer_impl` pulls
in (that chain loops back to ``inspect_ai.dataset.Sample`` and breaks
during initial package load otherwise).

Two-phase shape:

* The harness stashes a setup object (an
  ``AbstractAsyncContextManager[Checkpointer]``) on the active sample.
  It holds the inputs but does no I/O.
* The agent's ``async with checkpointer() as cp:`` enters that setup,
  which performs the on-disk + sandbox setup and yields a fully-formed
  :class:`Checkpointer` — the agent-facing API with no lifecycle
  concerns.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar

T = TypeVar("T")


@dataclass
class ResumeCheckpoint:
    """Per-sample resume info: where the on-disk checkpoint lives."""

    sample_checkpoints_dir: str


class Checkpointer(Protocol):
    """The session yielded by ``async with checkpointer() as cp:``.

    Agent-facing — no lifecycle methods. The async-ctx-mgr concerns
    live on the setup object that the harness keeps on the active
    sample.
    """

    @property
    def is_resuming(self) -> bool:
        """True iff this sample is being resumed from a prior checkpoint.

        Agents can branch on this to skip one-time setup that was
        already performed on the original run, or to log/handle resume
        specially. Stable across the lifetime of the session.
        """
        ...

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

    def span_session(self) -> contextlib.AbstractAsyncContextManager[None]:
        """Bracket the agent's checkpointed scope with per-checkpoint transcript spans.

        Spans are peers — siblings under whatever span was active when the
        agent opened ``async with checkpointer()``. Each span's name
        matches the checkpoint id it will fire under (1-indexed, same
        numbering as ``ckpt-NNNNN.json``): ``checkpoint 1`` is the work
        that the first fire commits, ``checkpoint 2`` is the work that
        the second fire commits, and so on.

        On fire, the current span closes *before* ``write_host_context``
        (so the ``SpanEndEvent`` lands in this checkpoint's
        ``events.json``), then the next span opens after the checkpoint
        file is committed.

        A sample that finishes without ever firing leaves an unclosed
        ``checkpoint 1`` span — expected and informative: it records the
        work that would have been the first checkpoint had any fire
        happened. Same shape on resume: an attempt with ``M`` prior
        commits that finishes without firing leaves an unclosed
        ``checkpoint M+1``.

        For the no-op session this returns an empty ctx mgr.
        """
        ...

    def track(
        self,
        key: str,
        callback: Callable[[], T],
        initial_value: T,
        *,
        value_type: type[T] | None = None,
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

        ``value_type`` is required for any ``T`` whose JSON form differs
        from its in-memory form — collections of Pydantic models,
        discriminated unions, models nested in generic containers, etc.
        Two cases are auto-handled and do **not** need a ``value_type``:

        * A single Pydantic model instance — the instance's runtime
          class is unambiguous.
        * A JSON-primitive value (``int``, ``float``, ``str``, ``bool``,
          ``None``) — round-trips identically through ``json``.

        Any other ``initial_value`` without a ``value_type`` raises
        ``TypeError`` at register time. The check fires deterministically
        on every run (fresh or resume) so the missing-``value_type`` bug
        surfaces during development rather than mid-agent-loop after a
        real failure-and-retry.

        A key may be tracked only once per session; a duplicate call
        raises ``ValueError``.
        """
        ...


@contextlib.asynccontextmanager
async def checkpointer() -> AsyncIterator[Checkpointer]:
    """Enter the checkpointer bound to the active sample.

    Delegates to the per-sample setup object stashed on the active
    sample by the harness. The setup builds and caches a real
    :class:`Checkpointer` on first entry; subsequent opens within the
    same sample reuse the cached instance.

    Must be called inside an active sample — :func:`sample_active`
    returning ``None`` raises ``RuntimeError``.
    """
    # Function-scoped import to avoid a load-time cycle with
    # `inspect_ai.log._samples`.
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    if active is None:
        raise RuntimeError("checkpointer() must be called inside an active sample")
    async with active.checkpointer as cp:
        async with cp.span_session():
            yield cp
