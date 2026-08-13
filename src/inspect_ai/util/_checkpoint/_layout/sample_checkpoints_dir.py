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
- ``resume-source.json`` — present only while a resume copy into this
  dir is incomplete: points at the dir being copied from, and is
  deleted when the copy completes (see :class:`ResumeSource`).

The optional ``_<retry>`` suffix on the dir name is omitted until
``ActiveSample`` exposes the attempt index — see the TODO at the
``Checkpointer.__aenter__`` identity capture.
"""

from __future__ import annotations

import secrets
from logging import getLogger
from typing import NamedTuple, TypeVar

from pydantic import BaseModel, ValidationError

from inspect_ai._util.asyncfiles import get_async_filesystem

from .._async_fs import async_mkdir
from .schemas import Checkpoint, ResticConfig, ResumeSource
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
    async_fs = get_async_filesystem()
    for n in sorted(ids, reverse=True):
        path = f"{sample_checkpoints_dir}/ckpt-{n:05d}.json"
        try:
            raw = await async_fs.read_file(path)
            return Checkpoint.model_validate_json(raw)
        except Exception:
            continue
    return None


RESUME_SOURCE_FILE = "resume-source.json"


class ResolvedResumeDir(NamedTuple):
    """A sample dir holding a committed checkpoint, plus that checkpoint."""

    sample_dir: str
    checkpoint: Checkpoint


async def write_resume_source_marker(destination_dir: str, source_dir: str) -> None:
    """Write the resume-source marker into ``destination_dir``.

    Must be the *first* write of the copy into ``destination_dir``, so
    that however early the copy is interrupted, the trail back to the
    source survives (see :class:`ResumeSource`). ``destination_dir`` is
    a sample checkpoints dir for per-sample copies, or the eval
    checkpoints dir for the greedy copy's eval-level marker.
    """
    await _write_model_json(
        f"{destination_dir}/{RESUME_SOURCE_FILE}",
        ResumeSource(source_dir=source_dir),
    )


async def delete_resume_source_marker(destination_dir: str) -> None:
    """Delete ``destination_dir``'s resume-source marker.

    This is the copy's completeness commit point (see
    :class:`ResumeSource`). Idempotent: a missing marker (e.g. a
    same-dir resume that never wrote one) is a no-op.
    """
    try:
        await get_async_filesystem().delete_file(
            f"{destination_dir}/{RESUME_SOURCE_FILE}"
        )
    except FileNotFoundError:
        pass


async def resolve_resumable_sample_dir(sample_dir: str) -> ResolvedResumeDir | None:
    """Resolve ``sample_dir`` to the dir a resume should restore from.

    The dir's own committed checkpoint wins. Failing that, follow the
    resume-source marker — present only while a resume copy into the
    dir is incomplete — back toward the source the copy was pulling
    from, which held a committed checkpoint when the marker was
    written. Returns ``None`` when the chain ends with neither a
    checkpoint nor a marker (nothing ever committed — run fresh), or
    on a dangling marker (source since deleted).
    """
    seen: set[str] = set()
    current = sample_dir
    while current not in seen:
        seen.add(current)
        checkpoint = await scan_latest_committed_checkpoint(current)
        if checkpoint is not None:
            return ResolvedResumeDir(sample_dir=current, checkpoint=checkpoint)
        # checkpoint files present but none parse: surface it — resume
        # used to fail loudly here, and silently running fresh would
        # hide substantial progress loss (the restic repos may be fine)
        if await _list_checkpoint_ids(current):
            logger.warning(
                f"Checkpoint files exist in {current} but none parse as a "
                "valid checkpoint; treating the dir as holding no committed "
                "checkpoint. The restic repos may still be intact — see the "
                "checkpoint docs for manual recovery."
            )
        marker = await read_resume_source_marker(current)
        if marker is None:
            return None
        current = marker.source_dir
    # a marker cycle is bounded to self-pointing in practice (an in-eval
    # requeue re-resolves into the same sample dir — see the source ==
    # destination guard in `copy_sample_payload`); the seen-set bails on
    # any cycle rather than looping
    return None


async def resolve_resumable_sample_dir_in_chain(
    eval_dir: str, sample_id: int | str, epoch: int
) -> ResolvedResumeDir | None:
    """Resolve a sample's resume dir across the eval-dir retry chain.

    Each eval checkpoints dir carries a permanent resume-source marker
    naming the attempt it retried (see ``_resume_copy``). Try the
    sample's dir in ``eval_dir`` first (its own committed checkpoints,
    or its per-sample marker trail), then walk the eval-level chain for
    attempts where no per-sample trail exists — a sample skipped by the
    greedy copy as reusable, or fed in mid-run, may live any number of
    attempts back. Returns ``None`` when no attempt in the chain holds
    anything for the sample.
    """
    seen: set[str] = set()
    current: str | None = eval_dir
    while current is not None and current not in seen:
        seen.add(current)
        resolved = await resolve_resumable_sample_dir(
            sample_checkpoints_dir(current, sample_id, epoch)
        )
        if resolved is not None:
            return resolved
        marker = await read_resume_source_marker(current)
        current = marker.source_dir if marker is not None else None
    return None


async def read_resume_source_marker(dir_path: str) -> ResumeSource | None:
    """The dir's resume-source marker, or ``None`` (absent or torn).

    A torn marker means the copy was interrupted mid-way through its
    very first write — nothing had been copied yet, so treating it
    as absent (run fresh) loses nothing. Only definitive absence
    (missing file) and tears (unparseable content) map to ``None``;
    transient read failures (e.g. an S3 throttle) propagate, so a
    resumable torn dir is never silently downgraded to a fresh run.
    """
    try:
        return await _load_model_json(f"{dir_path}/{RESUME_SOURCE_FILE}", ResumeSource)
    except FileNotFoundError:
        return None
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
