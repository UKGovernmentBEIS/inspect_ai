"""Sample checkpoints dir contents.

Each ``(sample, epoch[, retry])`` attempt gets its own sample
checkpoints dir under the eval checkpoints dir. The dir holds:

- ``ckpt-NNNNN.json`` — one plaintext checkpoint file per fired
  checkpoint; the index into the host + sandbox restic repos.
- ``restic/`` — restic state subdir, containing
  ``restic-config.json`` (per-sample restic password),
  ``host/`` (host restic repo), and
  ``sandboxes/<name>/`` (per-sandbox restic repos).
- ``context/`` — restic backup source (host context JSON files).

The optional ``_<retry>`` suffix on the dir name is omitted until
``ActiveSample`` exposes the attempt index — see the TODO at the
``Checkpointer.__aenter__`` identity capture.
"""

from __future__ import annotations

import secrets
from functools import partial
from typing import TypeVar

import anyio
from pydantic import BaseModel, ValidationError

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import get_async_filesystem

from .._async_fs import async_mkdir
from .schemas import Checkpoint, ResticConfig
from .staging_dir import restic_config_path, restic_dir

_M = TypeVar("_M", bound=BaseModel)

_SCAN_READ_CONCURRENCY = 16
"""Concurrent checkpoint-file reads in :func:`scan_committed_checkpoints`.

Bounds the GET fan-out against a remote location so a sample with
hundreds of checkpoint files does not trip request throttling."""


def sample_checkpoints_dir(eval_dir: str, sample_id: int | str, epoch: int) -> str:
    """Return the per-sample checkpoints dir path (no FS side effects)."""
    return f"{eval_dir}/{sample_id}__{epoch}"


async def has_sample_checkpoint(
    eval_dir: str, sample_id: int | str, epoch: int
) -> bool:
    """Return True if any ``ckpt-*.json`` checkpoint file exists for this sample attempt.

    Doesn't pre-check the dir's existence — S3 has no real directories,
    so ``AsyncFilesystem.exists(prefix)`` always returns False for an
    S3 dir prefix even when there are checkpoint files under it. The
    iteration handles the "no checkpoint files" case naturally
    (yields nothing).
    """
    sample_dir = sample_checkpoints_dir(eval_dir, sample_id, epoch)
    return bool(await _list_checkpoint_ids(sample_dir))


async def ensure_sample_checkpoints_dir(
    eval_dir: str, sample_id: int | str, epoch: int
) -> str:
    """Create (idempotent) and return the sample checkpoints dir path.

    Single mkdir — for local fs, ``async_mkdir`` resolves to
    ``makedirs`` which creates parents; for S3, it's a no-op (no
    directory concept).
    """
    sample_dir = sample_checkpoints_dir(eval_dir, sample_id, epoch)
    await async_mkdir(sample_dir)
    return sample_dir


async def ensure_restic_config(sample_root: str) -> ResticConfig:
    """Ensure ``<sample_root>/restic/restic-config.json`` exists; return its contents.

    Mints a fresh restic password and writes the file on first call.
    Subsequent calls read and return the existing file. Idempotent
    across concurrent samples (different sample roots) — there is no
    cross-sample race.

    Also ensures the ``restic/`` subdir exists, since restic-config.json
    is the first file written into it.
    """
    path = restic_config_path(sample_root)
    if await get_async_filesystem().exists(path):
        return await _load_model_json(path, ResticConfig)
    await async_mkdir(restic_dir(sample_root))
    config = ResticConfig(restic_password=secrets.token_urlsafe(32))
    await _write_model_json(path, config)
    return config


async def _read_restic_config(sample_root: str) -> ResticConfig:
    """Read ``<sample_root>/restic/restic-config.json``. Caller must have ensured it exists."""
    return await _load_model_json(restic_config_path(sample_root), ResticConfig)


async def scan_latest_committed_id(sample_checkpoints_dir: str) -> int | None:
    """Return the highest checkpoint id whose checkpoint file parses cleanly.

    See :func:`scan_latest_committed_checkpoint` for the commit-point contract.
    """
    checkpoint = await scan_latest_committed_checkpoint(sample_checkpoints_dir)
    return checkpoint.checkpoint_id if checkpoint is not None else None


async def scan_latest_committed_checkpoint(
    sample_checkpoints_dir: str,
) -> Checkpoint | None:
    """Return the highest checkpoint whose checkpoint file parses cleanly.

    Walks ``ckpt-NNNNN.json`` files in the sample dir from highest N
    to lowest; the first whose contents validate as a
    :class:`Checkpoint` is the commit point. A torn-write checkpoint
    file is silently skipped (see :func:`_read_checkpoint_file` for
    what counts as torn). Returns ``None`` if no checkpoint file
    exists or none parses (caller is responsible for treating that as
    a meaningful state — typically an error on resume).
    """
    ids = await _list_checkpoint_ids(sample_checkpoints_dir)
    for n in sorted(ids, reverse=True):
        checkpoint = await _read_checkpoint_file(sample_checkpoints_dir, n)
        if checkpoint is not None:
            return checkpoint
    return None


async def scan_committed_checkpoints(sample_checkpoints_dir: str) -> list[Checkpoint]:
    """Return every checkpoint whose file parses cleanly, in ascending id order.

    Same commit-point contract as :func:`scan_latest_committed_checkpoint`
    (a torn-write file is silently skipped); the last element is that
    function's result. Resume uses the full list to decide which strategy
    snapshots are acknowledged by a committed checkpoint — and deletes
    the rest — so a file that cannot be *read* fails the scan rather
    than passing as absent (see :func:`_read_checkpoint_file`).
    """
    ids = await _list_checkpoint_ids(sample_checkpoints_dir)
    limiter = anyio.Semaphore(_SCAN_READ_CONCURRENCY)

    async def read_one(n: int) -> Checkpoint | None:
        async with limiter:
            return await _read_checkpoint_file(sample_checkpoints_dir, n)

    # Concurrent reads: with a remote location and a turn trigger a sample
    # can hold hundreds of checkpoint files, and serial GETs would dominate
    # resume. tg_collect preserves input order, so the result stays ascending.
    results = await tg_collect([partial(read_one, n) for n in sorted(ids)])
    return [checkpoint for checkpoint in results if checkpoint is not None]


async def _read_checkpoint_file(
    sample_checkpoints_dir: str, n: int
) -> Checkpoint | None:
    """Read ``ckpt-NNNNN.json``; ``None`` if its contents don't validate.

    Only a parse/validation failure is the torn-write case the commit
    point contract skips. An I/O error (a throttled or reset remote GET)
    propagates: treating an unreadable file as absent would present a
    committed checkpoint as uncommitted to callers that act on the
    result — orphan discard would delete its snapshot, the next fire
    would reuse its id and overwrite it.
    """
    raw = await get_async_filesystem().read_file(
        f"{sample_checkpoints_dir}/ckpt-{n:05d}.json"
    )
    try:
        return Checkpoint.model_validate_json(raw)
    except ValidationError:
        return None


async def write_checkpoint_file(
    *,
    sample_checkpoints_dir: str,
    checkpoint: Checkpoint,
) -> str:
    """Write ``ckpt-NNNNN.json`` for this checkpoint. Returns the path.

    Non-atomic on purpose. Per ``checkpointing-working.md`` §4d, the
    commit point is "checkpoint file that parses": resume globs
    ``ckpt-*.json``, parse-and-skips torn / missing entries, and falls
    back to the prior parseable checkpoint file. A mid-write crash
    costs at most one checkpoint's progress — same as crashing before
    the file starts.
    """
    path = f"{sample_checkpoints_dir}/ckpt-{checkpoint.checkpoint_id:05d}.json"
    await _write_model_json(path, checkpoint)
    return path


async def _list_checkpoint_ids(sample_dir: str) -> list[int]:
    """Return every checkpoint id present as ``ckpt-NNNNN.json`` in ``sample_dir``.

    Unsorted. Names that don't parse as an int are silently skipped.
    Works over any ``AsyncFilesystem``-supported scheme; a missing dir
    yields nothing (no pre-check needed — see note on
    ``has_sample_checkpoint``).
    """
    ids: list[int] = []
    try:
        async for uri in get_async_filesystem().iter_files(
            sample_dir, pattern="ckpt-*.json"
        ):
            name = uri.rsplit("/", 1)[-1]
            try:
                ids.append(int(name.removeprefix("ckpt-").removesuffix(".json")))
            except ValueError:
                continue
    except FileNotFoundError:
        pass
    return ids


async def _load_model_json(path: str, model_cls: type[_M]) -> _M:
    """Load a pydantic model from a JSON file via ``AsyncFilesystem``."""
    raw = await get_async_filesystem().read_file(path)
    return model_cls.model_validate_json(raw)


async def _write_model_json(path: str, model: BaseModel) -> None:
    """Write a pydantic model to a JSON file via ``AsyncFilesystem``.

    Pretty-printed (``indent=2``); non-atomic. ``exclude_none`` keeps
    opt-in fields (e.g. ``SnapshotDetails.files``) out of the file when
    unset — no other field is ever ``None``.
    """
    await get_async_filesystem().write_file(
        path, model.model_dump_json(indent=2, exclude_none=True).encode()
    )
