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

import re
import secrets
import shutil
from logging import getLogger
from pathlib import Path
from typing import TypeVar

import anyio.to_thread
from pydantic import BaseModel, ValidationError

from inspect_ai._util.asyncfiles import (
    get_async_filesystem,
    is_s3_filename,
    s3_bucket_and_key,
)
from inspect_ai._util.file import local_path

from .._async_fs import async_mkdir
from .schemas import Checkpoint, ResticConfig
from .staging_dir import clear_sample_staging_dir, restic_config_path, restic_dir

logger = getLogger(__name__)

_M = TypeVar("_M", bound=BaseModel)


_CHECKPOINT_FILE_RE = re.compile(r"^ckpt-(\d+)\.json$")


def checkpoint_file_id(name: str) -> int | None:
    """The id of a ``ckpt-NNNNN.json`` file name, or ``None`` for any other name.

    The one predicate for "is this a checkpoint file" — the copy, the
    delete, host egress, hydrate's validation, and the id scan all use it.
    """
    match = _CHECKPOINT_FILE_RE.match(name)
    return int(match.group(1)) if match else None


def sample_dir_name(sample_id: int | str, epoch: int) -> str:
    """The name of a sample's checkpoints dir within its eval checkpoints dir."""
    return f"{sample_id}__{epoch}"


def sample_checkpoints_dir(eval_dir: str, sample_id: int | str, epoch: int) -> str:
    """Return the per-sample checkpoints dir path (no FS side effects)."""
    return f"{eval_dir}/{sample_dir_name(sample_id, epoch)}"


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
    file is silently skipped. Returns ``None`` if no checkpoint file
    exists or none parses — the dir holds nothing committed, and a
    sample resolving against it runs fresh (with a warning when files
    were present).
    """
    ids = await _list_checkpoint_ids(sample_checkpoints_dir)
    for n in sorted(ids, reverse=True):
        try:
            checkpoint = await _read_checkpoint_file(sample_checkpoints_dir, n)
        except FileNotFoundError:
            # Preserve latest-only scanning's tolerance for a concurrent delete.
            continue
        if checkpoint is not None:
            return checkpoint
    if ids:
        # checkpoint files present but none parse: callers treat the dir
        # as holding nothing committed, and that should not pass silently
        # — a torn write of the only checkpoint file is the likeliest cause
        logger.warning(
            f"Checkpoint files exist in {sample_checkpoints_dir} but none "
            "parse as a valid checkpoint; treating the dir as holding no "
            "committed checkpoint."
        )
    return None


async def scan_committed_checkpoints(sample_checkpoints_dir: str) -> list[Checkpoint]:
    """Return every checkpoint whose file parses cleanly, in ascending id order.

    Same commit-point contract as :func:`scan_latest_committed_checkpoint`
    (a torn-write file is silently skipped); the last element is that
    function's result when files remain available during both scans.
    Unlike the latest-only scan, a listed file disappearing is an error.
    Resume uses the full list to decide which strategy
    snapshots are acknowledged by a committed checkpoint — and deletes
    the rest — so a file that cannot be *read* fails the scan rather
    than passing as absent (see :func:`_read_checkpoint_file`).
    """
    ids = await _list_checkpoint_ids(sample_checkpoints_dir)
    committed: list[Checkpoint] = []
    for n in sorted(ids):
        checkpoint = await _read_checkpoint_file(sample_checkpoints_dir, n)
        if checkpoint is not None:
            committed.append(checkpoint)
    return committed


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


async def delete_sample_checkpoints_dir(
    eval_dir: str, sample_id: int | str, epoch: int, *, log_location: str
) -> None:
    """Delete a sample's checkpoints dir and its staging dir (idempotent).

    Used when a sample runs fresh in an attempt whose dir for it is not
    empty: an invalidated prior's copied checkpoints, or repos from an
    attempt that never committed a checkpoint file. Checkpoint files go
    first, newest first: they are the dir's commit point, so an
    interrupted delete leaves at most an older checkpoint behind. The
    host-local staging dir a remote destination stages through is
    cleared too, so fresh provisioning starts from nothing on both sides.
    """
    await clear_sample_staging_dir(log_location, sample_id, epoch)
    target = sample_checkpoints_dir(eval_dir, sample_id, epoch)
    if not is_s3_filename(target):

        def rmtree_checkpoints_first() -> None:
            root = Path(local_path(target))
            for checkpoint_file in sorted(
                root.glob("ckpt-*.json"),
                key=lambda f: checkpoint_file_id(f.name) or 0,
                reverse=True,
            ):
                checkpoint_file.unlink(missing_ok=True)
            shutil.rmtree(root)

        try:
            await anyio.to_thread.run_sync(rmtree_checkpoints_first)
        except FileNotFoundError:
            pass
        return
    async_fs = get_async_filesystem()
    # collect first: deleting while iterating a paginated S3 listing is
    # undefined
    try:
        files = [uri async for uri in async_fs.iter_files(target, recursive=True)]
    except FileNotFoundError:
        files = []
    bucket, key = s3_bucket_and_key(target)
    prefix_len = len(f"s3://{bucket}/{key}".rstrip("/")) + 1
    # top-level checkpoint files first (the anchored name pattern rejects
    # any nested path), newest first
    files.sort(
        key=lambda uri: (
            checkpoint_file_id(uri[prefix_len:]) is None,
            -(checkpoint_file_id(uri[prefix_len:]) or 0),
        )
    )
    for uri in files:
        await async_fs.delete_file(uri)


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
    yields nothing, so no existence pre-check is needed — S3 has no
    real directories, and ``AsyncFilesystem.exists(prefix)`` returns
    False for an S3 dir prefix even when files exist under it.
    """
    ids: list[int] = []
    try:
        async for uri in get_async_filesystem().iter_files(
            sample_dir, pattern="ckpt-*.json"
        ):
            checkpoint_id = checkpoint_file_id(uri.rsplit("/", 1)[-1])
            if checkpoint_id is not None:
                ids.append(checkpoint_id)
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
