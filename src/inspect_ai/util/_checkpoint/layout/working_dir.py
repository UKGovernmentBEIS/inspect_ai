"""Eval and sample working dirs (host-local, ephemeral).

The eval working dir lives at
``inspect_cache_dir("checkpoints")/<log-basename>/``; under it, each
attempt has its sample working dir
(``<sample-id>__<epoch>[_<retry>]/``) holding the JSON files restic
snapshots each cycle (``events.json``, ``events_data.json``,
``attachments.json``, ``store.json``, and optionally
``agent_state.json``). Working dirs are overwritten in place at every
fire. See ``design/plans/checkpointing-working.md`` §5.
"""

from __future__ import annotations

from pathlib import Path

import anyio

from inspect_ai._util.appdirs import inspect_cache_dir

from .eval_checkpoints_dir import log_basename


def _eval_working_dir(log_location: str) -> str:
    return str(inspect_cache_dir("checkpoints") / log_basename(log_location))


def _sample_working_dir(log_location: str, sample_id: int | str, epoch: int) -> str:
    return f"{_eval_working_dir(log_location)}/{sample_id}__{epoch}"


async def ensure_sample_working_dir(
    log_location: str, sample_id: int | str, epoch: int
) -> str:
    """Create (idempotent) and return the sample working dir path.

    Also ensures the eval working dir exists; that's an implementation
    detail callers shouldn't have to repeat.
    """
    return await anyio.to_thread.run_sync(
        _ensure_sample_working_dir_blocking, log_location, sample_id, epoch
    )


def _ensure_sample_working_dir_blocking(
    log_location: str, sample_id: int | str, epoch: int
) -> str:
    _ensure_eval_working_dir(log_location)
    sample_dir = _sample_working_dir(log_location, sample_id, epoch)
    Path(sample_dir).mkdir(exist_ok=True)
    return sample_dir


def _ensure_eval_working_dir(log_location: str) -> str:
    eval_dir = _eval_working_dir(log_location)
    Path(eval_dir).mkdir(parents=True, exist_ok=True)
    return eval_dir
