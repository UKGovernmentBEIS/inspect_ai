"""Checkpoint session protocol and ``checkpointer()`` factory.

Kept deliberately light so that this module can be imported eagerly
from ``inspect_ai.util._checkpoint/__init__.py`` and ``inspect_ai.util``
without triggering the heavy ``log``/``solver``/``model`` chain that
the active-session implementation in :mod:`.checkpointer` pulls in
(that chain loops back to ``inspect_ai.dataset.Sample`` and breaks
during initial package load otherwise).

The factory looks up the checkpointer instance built eagerly by
:func:`inspect_ai.log._samples.active_sample`, so no heavy import is
needed here at call time.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar

T = TypeVar("T")


@dataclass
class ResumeCheckpoint:
    """Per-sample resume info: where the on-disk checkpoint lives.

    Produced by ``eval_log_sample_source`` when an incomplete sample
    has a ``ckpt-*.json`` sidecar on disk. The consumer hydrates the
    checkpointer's resume state from this; same-machine retry reads
    the agent-state snapshot from the original run's working dir
    (derived from ``log_location``).
    """

    sample_checkpoints_dir: str
    log_location: str
    """Original eval log location — used to derive the original
    working dir for same-machine resume."""


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


class _NoopCheckpointer:
    """No-op session used when no sample is active or no config is set."""

    async def tick(self) -> None:
        return None

    async def checkpoint(self) -> None:
        return None

    def track(
        self,
        key: str,
        callback: Callable[[], T],
        initial_value: T,
    ) -> T:
        return initial_value


@contextlib.asynccontextmanager
async def checkpointer() -> AsyncIterator[Checkpointer]:
    """Enter the checkpointer bound to the active sample.

    Returns the per-sample :class:`Checkpointer` instance built eagerly
    by :func:`inspect_ai.log._samples.active_sample` (a
    :class:`_NoopCheckpointer` if the active sample has no checkpoint
    config). Falls back to a no-op when called outside any active
    sample.

    The resolved :class:`CheckpointConfig` lives on
    :class:`inspect_ai.log._samples.ActiveSample` — installed by the
    harness at sample-run setup time per eval / task / sample
    precedence. Agents do not pass a config here.
    """
    # Function-scoped import to avoid a load-time cycle between this
    # module and `inspect_ai.log._samples`.
    from inspect_ai.log._samples import sample_active

    active = sample_active()
    yield active.checkpointer if active is not None else _NoopCheckpointer()
