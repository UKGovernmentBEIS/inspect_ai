"""``restic-incremental``: the default sandbox snapshot strategy.

An extraction of the code that was previously inlined at the
checkpointer call sites (see the extraction table in
``design/checkpoint-snapshot-strategy.md`` §3):

- ``setup``    ← ``inject_restic`` (both paths) + ``init_sandbox_repo``
  (fresh only)
- ``snapshot`` ← ``run_sandbox_backup`` + ``egress_sandbox`` +
  ``list_changed_files``
- ``restore``  ← ``ingress_sandbox``
- ``adopt``    ← the per-sandbox ``fs_copy_repo``
- ``discard_orphans`` ← ``forget_unrecorded_snapshots``

The snapshot id recorded in checkpoint files is the one the *host*
verified the destination gained during egress, not the id the
in-sandbox backup reported; ``restore`` restores exactly that recorded
snapshot, and ``discard_orphans`` keeps exactly the recorded ones.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from inspect_ai.util._restic import list_changed_files, resolve_restic
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .._copy import probe_dd_fullblock
from .._layout.schemas import SnapshotDetails
from .._repo_ops import checkpoint_tag, forget_unrecorded_snapshots, fs_copy_repo
from .._sandbox_restic import (
    egress_sandbox,
    ingress_sandbox,
    init_sandbox_repo,
    inject_restic,
    run_sandbox_backup,
)
from ..config import MAX_LISTED_FILES
from ..sandbox_paths import SandboxBackupPaths
from .types import (
    CommittedSnapshot,
    PriorAttempt,
    SandboxSnapshotStrategy,
    SnapshotContext,
)


class ResticIncrementalStrategy(SandboxSnapshotStrategy):
    """Incremental restic snapshots into a per-sandbox host-side repo."""

    name = "restic-incremental"

    def __init__(self) -> None:
        self._dd_fullblock = False

    async def setup(self, env: SandboxEnvironment, ctx: SnapshotContext) -> None:
        await inject_restic(env)
        if not ctx.resuming:
            await init_sandbox_repo(env, ctx.secret)
        self._dd_fullblock = await probe_dd_fullblock(env)

    async def snapshot(
        self,
        env: SandboxEnvironment,
        paths: SandboxBackupPaths,
        checkpoint_id: int,
        ctx: SnapshotContext,
    ) -> SnapshotDetails:
        tag = checkpoint_tag(checkpoint_id)
        summary = await run_sandbox_backup(
            env, ctx.secret, paths.include, tag, exclude=paths.exclude
        )
        host_restic = await self._host_restic()
        snapshot_id = await egress_sandbox(
            env,
            dest_repo=ctx.storage_dir,
            password=ctx.secret,
            host_restic=host_restic,
            tag=tag,
            snapshot_id=summary.snapshot_id,
            max_bytes=ctx.max_snapshot_bytes,
            dd_fullblock=self._dd_fullblock,
        )
        # Diff host-side against the just-egressed repo so the in-sandbox
        # exec-output limit is never hit.
        files, extra = await list_changed_files(
            host_restic,
            ctx.storage_dir,
            ctx.secret,
            snapshot_id,
            MAX_LISTED_FILES,
        )
        # `strategy` rides as an extra field (see `snapshot_strategy_name`).
        return SnapshotDetails.model_validate(
            dict(
                snapshot_id=snapshot_id,
                size_bytes=summary.data_added_packed,
                duration_ms=int(summary.total_duration * 1000),
                files=files,
                additional_files=extra or None,
                strategy=self.name,
            )
        )

    async def restore(
        self,
        env: SandboxEnvironment,
        ref: SnapshotDetails | None,
        ctx: SnapshotContext,
    ) -> None:
        # `ref is None` only in the degenerate resume with no committed
        # record for this sandbox (orphan discard is skipped in exactly
        # that case): fall back to whatever the adopted repo calls latest.
        await ingress_sandbox(
            env,
            ctx.storage_dir,
            ctx.secret,
            snapshot_id=ref.snapshot_id if ref is not None else None,
        )

    async def adopt(self, prior: PriorAttempt, ctx: SnapshotContext) -> None:
        await fs_copy_repo(
            prior.sample_checkpoints_dir,
            prior.storage_subpath,
            ctx.storage_dir,
            label=f"sandbox {ctx.sandbox_name!r}",
        )

    async def discard_orphans(
        self, committed: Sequence[CommittedSnapshot], ctx: SnapshotContext
    ) -> None:
        if not committed:
            raise RuntimeError(
                f"resume: no committed checkpoint records a snapshot for sandbox "
                f"{ctx.sandbox_name!r}; refusing to discard from {ctx.storage_dir}"
            )
        latest = max(committed, key=lambda c: c.checkpoint_id)
        await forget_unrecorded_snapshots(
            await self._host_restic(),
            ctx.storage_dir,
            ctx.secret,
            recorded_ids=[c.details.snapshot_id for c in committed],
            required_id=latest.details.snapshot_id,
        )

    async def _host_restic(self) -> Path:
        # `resolve_restic()` caches the resolved binary path internally;
        # resolving per-call keeps this strategy free of construction-time
        # I/O.
        return await resolve_restic()
