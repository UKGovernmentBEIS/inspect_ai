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
import shutil
from functools import partial
from logging import getLogger
from typing import NamedTuple, TypeVar

import anyio.to_thread
from pydantic import BaseModel

from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.file import filesystem, local_path

from .._async_fs import async_mkdir
from .schemas import Checkpoint, ResticConfig
from .staging_dir import restic_config_path, restic_dir

logger = getLogger(__name__)

_M = TypeVar("_M", bound=BaseModel)


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
    exists or none parses (caller is responsible for treating that as
    a meaningful state — typically an error on resume).
    """
    ids = await _list_checkpoint_ids(sample_checkpoints_dir)
    return await _first_parseable_checkpoint(sample_checkpoints_dir, ids)


async def _first_parseable_checkpoint(
    sample_checkpoints_dir: str, ids: list[int]
) -> Checkpoint | None:
    async_fs = get_async_filesystem()
    for n in sorted(ids, reverse=True):
        path = f"{sample_checkpoints_dir}/ckpt-{n:05d}.json"
        try:
            raw = await async_fs.read_file(path)
            return Checkpoint.model_validate_json(raw)
        except (ValueError, FileNotFoundError):
            # torn write (unparseable; ValidationError is a ValueError) or
            # a file deleted since the listing — fall back to the next
            # lower checkpoint. Anything else (e.g. a transient S3 error)
            # propagates: this scan is a sample's only shot at resuming,
            # and swallowing an I/O failure would silently run it fresh.
            continue
    return None


class ResolvedResumeDir(NamedTuple):
    """A sample dir holding a committed checkpoint, plus that checkpoint."""

    sample_dir: str
    checkpoint: Checkpoint


async def resolve_resumable_sample_dir(sample_dir: str) -> ResolvedResumeDir | None:
    """The dir plus its latest committed checkpoint, or ``None``.

    ``None`` means the dir holds no committed checkpoint (it doesn't
    exist, is empty, or its files never committed) — the sample runs
    fresh. Detection never looks past a sample's own dir: the startup
    copy already brought everything a clean attempt has (see
    ``_resume_copy``).
    """
    # one listing serves both the scan and the none-parse warning below
    ids = await _list_checkpoint_ids(sample_dir)
    checkpoint = await _first_parseable_checkpoint(sample_dir, ids)
    if checkpoint is not None:
        return ResolvedResumeDir(sample_dir=sample_dir, checkpoint=checkpoint)
    # checkpoint files present but none parse: surface it — resume
    # used to fail loudly here, and silently running fresh would
    # hide substantial progress loss (the restic repos may be fine)
    if ids:
        logger.warning(
            f"Checkpoint files exist in {sample_dir} but none parse as a "
            "valid checkpoint; treating the dir as holding no committed "
            "checkpoint. The restic repos may still be intact — see the "
            "checkpoint docs for manual recovery."
        )
    return None


async def delete_sample_checkpoints_dir(
    eval_dir: str, sample_id: int | str, epoch: int
) -> None:
    """Delete a sample's checkpoints dir (all schemes; idempotent).

    Used when a prior sample was invalidated: invalidation means the
    sample restarts from scratch, so its copied checkpoints are thrown
    out rather than resumed.
    """
    target = sample_checkpoints_dir(eval_dir, sample_id, epoch)
    if filesystem(target).is_local():
        try:
            await anyio.to_thread.run_sync(partial(shutil.rmtree, local_path(target)))
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
    # checkpoint files first: they are the dir's commit point, so an
    # interrupted delete de-commits the dir before touching its data
    files.sort(key=lambda uri: not uri.rsplit("/", 1)[-1].startswith("ckpt-"))
    for uri in files:
        try:
            await async_fs.delete_file(uri)
        except FileNotFoundError:
            pass


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
