"""The ``SandboxSnapshotStrategy`` Protocol and its supporting types.

See ``design/checkpoint-snapshot-strategy.md`` §3–§4 for the full
contract. The short form: a strategy captures and restores one
sandbox's bulk state for checkpointing, honoring these guarantees:

- **Durable before commit (§4.1)**: when ``snapshot()`` returns,
  everything needed to restore that snapshot exists under the
  strategy's storage area at the sample root (the core ships the
  storage area to a remote destination, together with the checkpoint
  file shipped last, at the end of each fire).
- **Interruption tolerance (§4.2)**: partial state from an interrupted
  ``snapshot()`` must not break the next ``snapshot()`` on the same
  live sample, and must be invisible after resume once
  ``discard_orphans`` runs.
- **Restore into a fresh sandbox (§4.3)**: ``restore()`` receives a
  fresh sandbox and must leave the captured paths byte-identical to
  capture time at their original absolute paths.
- **Security (§4.6)**: tooling placed in the sandbox must be root-only
  and invisible to the agent; bytes read out of the sandbox are
  untrusted; secrets reach the sandbox only via per-exec environment
  variables.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Protocol

from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .._layout.schemas import SnapshotDetails
from ..sandbox_paths import SandboxBackupPaths

DEFAULT_STRATEGY_NAME = "restic-incremental"
"""Strategy recorded implicitly by pre-strategy checkpoint dirs.

A ``SnapshotDetails`` without a ``strategy`` field (and a sample dir
without a strategy pin) predates pluggable strategies, when restic was
the only implementation."""


@dataclass(frozen=True)
class SnapshotContext:
    """Per-(sandbox, attempt) context the core provides to every strategy call.

    Frozen per attempt; constructed by the core during hydration.
    """

    sandbox_name: str
    """Name of the sandbox this strategy instance captures."""

    storage_dir: str
    """The strategy's storage area — a host-local directory under the
    sample root owned entirely by the strategy; the core never reads
    inside it, and ships it verbatim to remote destinations."""

    storage_subpath: str
    """``storage_dir`` relative to the sample root (the same relative
    path locates the storage area at the destination and in prior
    attempts' sample dirs)."""

    secret: str
    """Per-sample capture secret (today's restic password). Must reach
    the sandbox only via per-exec environment variables."""

    resuming: bool
    """Whether this attempt resumes a prior attempt's checkpoints."""


@dataclass(frozen=True)
class PriorAttempt:
    """Where a prior attempt's strategy state lives, for ``adopt``."""

    sample_checkpoints_dir: str
    """The prior attempt's sample checkpoints dir (possibly remote)."""

    storage_subpath: str
    """The strategy's storage area subpath under that dir (same layout
    as this attempt's ``SnapshotContext.storage_subpath``)."""

    @property
    def storage_prefix(self) -> str:
        """Full URI prefix of the prior attempt's storage area."""
        return f"{self.sample_checkpoints_dir}/{self.storage_subpath}"


class SandboxSnapshotStrategy(Protocol):
    """Captures and restores one sandbox's bulk state for checkpointing.

    One instance per (sandbox, attempt), constructed by the core at
    hydration. See the module docstring for the contract each method
    must honor and the design doc for the full guarantees.

    Implementations should derive from this Protocol explicitly (it is
    subclassable) so the type checker verifies their signatures against
    the contract.
    """

    name: str
    """Stable strategy identity.

    Recorded in checkpoint files and the per-sample strategy pin
    (§4.7).
    """

    async def setup(self, env: SandboxEnvironment, ctx: SnapshotContext) -> None:
        """Provision a new sandbox instance (fresh sample *and* resume).

        Called before any other method that touches the sandbox: inject
        tooling (for restic, this is where the restic binary is
        installed into the sandbox); when ``ctx.resuming`` is false,
        also initialize fresh strategy state (restic: init the
        in-sandbox repo).
        """
        ...

    async def snapshot(
        self,
        env: SandboxEnvironment,
        paths: SandboxBackupPaths,
        checkpoint_id: int,
        ctx: SnapshotContext,
    ) -> SnapshotDetails:
        """Capture ``paths``; complete under the storage area on return.

        Raise (with context) on failure — the core's
        ``max_consecutive_failures`` handling decides whether the
        sample continues.
        """
        ...

    async def restore(
        self,
        env: SandboxEnvironment,
        ref: SnapshotDetails | None,
        ctx: SnapshotContext,
    ) -> None:
        """Materialize the latest committed snapshot into a fresh sandbox.

        ``ref`` is that snapshot's details from the latest committed
        checkpoint file (``None`` only in degenerate resume states with
        no per-sandbox record; strategies that need it must raise). May
        assume ``setup``, ``adopt``, and ``discard_orphans`` ran first.
        """
        ...

    async def adopt(self, prior: PriorAttempt, ctx: SnapshotContext) -> None:
        """Carry strategy state from a prior attempt into this one.

        After ``adopt``, ``restore``/``discard_orphans``/``snapshot``
        must work against this attempt's storage area.
        """
        ...

    async def discard_orphans(
        self, latest_committed_id: int, ctx: SnapshotContext
    ) -> None:
        """Drop snapshots with ``checkpoint_id > latest_committed_id``.

        Orphans come from fires that completed their capture but never
        committed a checkpoint file.
        """
        ...


class SandboxSnapshotSession(NamedTuple):
    """One sandbox's live snapshot machinery for the current attempt."""

    strategy: SandboxSnapshotStrategy
    context: SnapshotContext
    paths: SandboxBackupPaths


def snapshot_strategy_name(details: SnapshotDetails) -> str:
    """The strategy that wrote ``details``.

    The ``strategy`` field rides as an ``extra="allow"`` extra rather
    than a declared schema field (the design's compat rule: absent ⇒
    ``restic-incremental``, so pre-strategy checkpoint files parse
    unchanged and the public log/event schema is unaffected).
    """
    extra = details.model_extra or {}
    name = extra.get("strategy")
    return name if isinstance(name, str) else DEFAULT_STRATEGY_NAME
