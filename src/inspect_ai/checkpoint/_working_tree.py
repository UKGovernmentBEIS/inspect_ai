"""Host-local working tree management.

Each attempt has a working-tree directory rooted at
``inspect_cache_dir("checkpoints")/<log-basename>/<sample-id>__<epoch>[_<retry>]/``
that holds the two files (``context.json``, ``store.json``) restic
snapshots each cycle. Working trees are host-local and ephemeral —
overwritten in place at every fire. See
``design/plans/checkpointing-working.md`` §5.
"""

from __future__ import annotations

from pathlib import Path

import anyio

from inspect_ai._util.appdirs import inspect_cache_dir
from inspect_ai._util.file import basename

_LOG_SUFFIX = ".eval"


def working_tree_root(log_location: str) -> Path:
    """Per-eval-log working-tree root."""
    log_base = basename(log_location)
    if log_base.endswith(_LOG_SUFFIX):
        log_base = log_base[: -len(_LOG_SUFFIX)]
    return inspect_cache_dir("checkpoints") / log_base


def attempt_working_tree(log_location: str, sample_id: int | str, epoch: int) -> Path:
    """Per-attempt working-tree directory.

    Phase 3 (in progress): the optional ``_<retry>`` suffix is omitted
    until ``ActiveSample`` exposes the attempt index.
    """
    return working_tree_root(log_location) / f"{sample_id}__{epoch}"


async def write_working_tree(
    log_location: str, sample_id: int | str, epoch: int, turn: int
) -> Path:
    """Materialize the per-attempt working tree.

    Phase 3 (in progress): writes placeholder ``context.json`` and
    ``store.json``. Each carries the current ``turn`` so successive
    fires produce distinct content — that lets the upcoming restic
    backup slice verify it captures real change between snapshots.
    Replaced by real condensed-context and ``Store`` serialization in
    subsequent slices.
    """
    return await anyio.to_thread.run_sync(
        _write_working_tree_blocking, log_location, sample_id, epoch, turn
    )


def _write_working_tree_blocking(
    log_location: str, sample_id: int | str, epoch: int, turn: int
) -> Path:
    attempt = attempt_working_tree(log_location, sample_id, epoch)
    attempt.mkdir(parents=True, exist_ok=True)

    # TODO(checkpointing-phase-3): replace with the condensed
    # representation produced by `condense_sample()` (§5).
    (attempt / "context.json").write_text(
        f'{{"turn": {turn}, "messages": [], "events": []}}\n'
    )
    # TODO(checkpointing-phase-3): replace with the sample's `Store`
    # key/value state.
    (attempt / "store.json").write_text(f'{{"turn": {turn}}}\n')
    return attempt


__all__ = ["attempt_working_tree", "working_tree_root", "write_working_tree"]
