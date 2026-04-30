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
    log_base = basename(log_location)
    if log_base.endswith(_LOG_SUFFIX):
        log_base = log_base[: -len(_LOG_SUFFIX)]
    return inspect_cache_dir("checkpoints") / log_base


def _sample_working_dir(log_location: str, sample_id: int | str, epoch: int) -> Path:
    return _eval_working_dir(log_location) / f"{sample_id}__{epoch}"


async def ensure_sample_working_dir(
    log_location: str, sample_id: int | str, epoch: int
) -> Path:
    """Create (idempotent) and return the sample working dir path.

    Also ensures the eval working dir exists; that's an implementation
    detail callers shouldn't have to repeat.
    """
    return await anyio.to_thread.run_sync(
        _ensure_sample_working_dir_blocking, log_location, sample_id, epoch
    )


def _ensure_sample_working_dir_blocking(
    log_location: str, sample_id: int | str, epoch: int
) -> Path:
    _ensure_eval_working_dir(log_location)
    sample_dir = _sample_working_dir(log_location, sample_id, epoch)
    sample_dir.mkdir(exist_ok=True)
    return sample_dir


def _ensure_eval_working_dir(log_location: str) -> Path:
    eval_dir = _eval_working_dir(log_location)
    eval_dir.mkdir(parents=True, exist_ok=True)
    return eval_dir


async def write_sample_working_dir(sample_working_dir: Path, turn: int) -> None:
    """Materialize the sample working dir's contents.

    Phase 3 (in progress): writes placeholder ``context.json`` and
    ``store.json``. Each carries the current ``turn`` so successive
    fires produce distinct content — that lets the upcoming restic
    backup slice verify it captures real change between snapshots.
    Replaced by real condensed-context and ``Store`` serialization in
    subsequent slices.
    """
    await anyio.to_thread.run_sync(
        _write_sample_working_dir_blocking, sample_working_dir, turn
    )


def _write_sample_working_dir_blocking(sample_working_dir: Path, turn: int) -> None:
    # TODO(checkpointing-phase-3): replace with the condensed
    # representation produced by `condense_sample()` (§5).
    (sample_working_dir / "context.json").write_text(
        f'{{"turn": {turn}, "messages": [], "events": []}}\n'
    )
    # TODO(checkpointing-phase-3): replace with the sample's `Store`
    # key/value state.
    (sample_working_dir / "store.json").write_text(f'{{"turn": {turn}}}\n')
