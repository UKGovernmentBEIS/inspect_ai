"""Eval and sample working dirs (host-local, ephemeral).

The eval working dir lives at
``inspect_cache_dir("checkpoints")/<log-basename>/``; under it, each
attempt has its sample working dir
(``<sample-id>__<epoch>[_<retry>]/``) holding the two files
(``context.json``, ``store.json``) restic snapshots each cycle. Working
dirs are overwritten in place at every fire. See
``design/plans/checkpointing-working.md`` §5.
"""

from __future__ import annotations

from pathlib import Path

import anyio

from inspect_ai._util.appdirs import inspect_cache_dir
from inspect_ai._util.file import basename

_LOG_SUFFIX = ".eval"


def _eval_working_dir(log_location: str) -> Path:
    """Return the eval working dir path."""
    log_base = basename(log_location)
    if log_base.endswith(_LOG_SUFFIX):
        log_base = log_base[: -len(_LOG_SUFFIX)]
    return inspect_cache_dir("checkpoints") / log_base


def _sample_working_dir(log_location: str, sample_id: int | str, epoch: int) -> Path:
    """Return the sample working dir path."""
    return _eval_working_dir(log_location) / f"{sample_id}__{epoch}"


async def write_sample_working_dir(
    log_location: str, sample_id: int | str, epoch: int, turn: int
) -> Path:
    """Materialize the sample working dir.

    Phase 3 (in progress): writes placeholder ``context.json`` and
    ``store.json``. Each carries the current ``turn`` so successive
    fires produce distinct content — that lets the upcoming restic
    backup slice verify it captures real change between snapshots.
    Replaced by real condensed-context and ``Store`` serialization in
    subsequent slices.
    """
    return await anyio.to_thread.run_sync(
        _write_sample_working_dir_blocking, log_location, sample_id, epoch, turn
    )


def _write_sample_working_dir_blocking(
    log_location: str, sample_id: int | str, epoch: int, turn: int
) -> Path:
    sample_dir = _sample_working_dir(log_location, sample_id, epoch)
    sample_dir.mkdir(parents=True, exist_ok=True)

    # TODO(checkpointing-phase-3): replace with the condensed
    # representation produced by `condense_sample()` (§5).
    (sample_dir / "context.json").write_text(
        f'{{"turn": {turn}, "messages": [], "events": []}}\n'
    )
    # TODO(checkpointing-phase-3): replace with the sample's `Store`
    # key/value state.
    (sample_dir / "store.json").write_text(f'{{"turn": {turn}}}\n')
    return sample_dir
