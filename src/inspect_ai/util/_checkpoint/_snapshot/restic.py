"""``restic-incremental``: the default sandbox snapshot strategy.

An extraction of the code that was previously inlined at the
checkpointer call sites (see the extraction table in
``design/checkpoint-snapshot-strategy.md`` §3):

- ``setup``    ← ``inject_restic`` (both paths) + ``init_sandbox_repo``
  (fresh only)
- ``snapshot`` ← ``run_sandbox_backup`` + ``egress_sandbox`` +
  ``list_changed_files``
- ``restore``  ← ``ingress_sandbox``
- ``discard_orphans`` ← ``forget_unrecorded_snapshots``

The sandbox proposes a snapshot id. The host checks that it identifies
a newly received snapshot with the expected tag, resolves it to its
full id, and returns that id for recording. This does not authenticate
the captured state. Restore uses the recorded id, lists that snapshot
on the host and refuses one that reaches outside this attempt's capture
roots (see ``ingress_sandbox``); orphan discard keeps only recorded
snapshots. A sandbox with no committed record is never restored.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from inspect_ai.util._restic import list_changed_files, resolve_restic
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .._copy import probe_dd_fullblock
from .._layout.schemas import SnapshotDetails
from .._repo_ops import checkpoint_tag, forget_unrecorded_snapshots
from .._restore_scope import RestoreRoots, check_recorded_roots
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
        # `strategy` and `roots` ride as extra fields (see
        # `snapshot_strategy_name` and `_restore_scope.recorded_roots`).
        return SnapshotDetails.model_validate(
            dict(
                snapshot_id=snapshot_id,
                size_bytes=summary.data_added_packed,
                duration_ms=int(summary.total_duration * 1000),
                files=files,
                additional_files=extra or None,
                strategy=self.name,
                roots=list(paths.include),
            )
        )

    async def restore(
        self,
        env: SandboxEnvironment,
        paths: SandboxBackupPaths,
        ref: SnapshotDetails,
        ctx: SnapshotContext,
    ) -> None:
        label = f"restic snapshot restore for sandbox {ctx.sandbox_name!r}"
        roots = RestoreRoots.from_include(paths.include, label=label)
        check_recorded_roots(ref, roots, label=label)
        await ingress_sandbox(
            env,
            ctx.storage_dir,
            ctx.secret,
            snapshot_id=ref.snapshot_id,
            roots=roots,
            host_restic=await self._host_restic(),
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
