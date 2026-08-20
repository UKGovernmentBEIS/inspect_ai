"""``restic-incremental``: the default sandbox snapshot strategy.

A behavior-preserving extraction of the code that was previously inlined
at the checkpointer call sites (see the extraction table in
``design/checkpoint-snapshot-strategy.md`` §3):

- ``setup``    ← ``inject_restic`` (both paths) + ``init_sandbox_repo``
  (fresh only)
- ``snapshot`` ← ``run_sandbox_backup`` + ``egress_sandbox`` +
  ``list_changed_files``
- ``restore``  ← ``ingress_sandbox``
- ``adopt``    ← the per-sandbox ``fs_copy_repo``
- ``discard_orphans`` ← ``drop_orphan_snapshots``
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai.util._restic import list_changed_files, resolve_restic
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .._layout.schemas import SnapshotDetails
from .._repo_ops import checkpoint_tag, drop_orphan_snapshots, fs_copy_repo
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
    PriorAttempt,
    SandboxSnapshotStrategy,
    SnapshotContext,
)


class ResticIncrementalStrategy(SandboxSnapshotStrategy):
    """Incremental restic snapshots into a per-sandbox host-side repo."""

    name = "restic-incremental"

    async def setup(self, env: SandboxEnvironment, ctx: SnapshotContext) -> None:
        await inject_restic(env)
        if not ctx.resuming:
            await init_sandbox_repo(env, ctx.secret)

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
        await egress_sandbox(
            env,
            dest_repo=ctx.storage_dir,
            password=ctx.secret,
            host_restic=host_restic,
            tag=tag,
            snapshot_id=summary.snapshot_id,
        )
        # Diff host-side against the just-egressed repo so the in-sandbox
        # exec-output limit is never hit.
        files, extra = await list_changed_files(
            host_restic,
            ctx.storage_dir,
            ctx.secret,
            summary.snapshot_id,
            MAX_LISTED_FILES,
        )
        # `strategy` rides as an extra field (see `snapshot_strategy_name`).
        return SnapshotDetails.model_validate(
            dict(
                snapshot_id=summary.snapshot_id,
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
        # `ref` is unused: after `discard_orphans`, "latest" in the adopted
        # repo is exactly the latest committed snapshot.
        await ingress_sandbox(env, ctx.storage_dir, ctx.secret)

    async def adopt(self, prior: PriorAttempt, ctx: SnapshotContext) -> None:
        await fs_copy_repo(
            prior.sample_checkpoints_dir,
            prior.storage_subpath,
            ctx.storage_dir,
            label=f"sandbox {ctx.sandbox_name!r}",
        )

    async def discard_orphans(
        self, latest_committed_id: int, ctx: SnapshotContext
    ) -> None:
        await drop_orphan_snapshots(
            await self._host_restic(), ctx.storage_dir, ctx.secret, latest_committed_id
        )

    async def _host_restic(self) -> Path:
        # `resolve_restic()` caches the resolved binary path internally;
        # resolving per-call keeps this strategy free of construction-time
        # I/O.
        return await resolve_restic()
