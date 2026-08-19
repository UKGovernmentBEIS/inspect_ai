"""Resume payload copying — the transport half of checkpoint resume.

Copying replicates sample checkpoint payloads (every checkpoint file,
the restic repos behind them, and the restic config) from the attempt
being retried into the new attempt's eval checkpoints dir. It is pure
file transport — no sandboxes, no live framework state; that is
hydration's restore side (``hydrate.py``), which runs later, at sample
start, and never writes anything a future retry needs.

The design is one rule with two supports:

- **A clean attempt contains everything.** ``copy_resume_payloads``
  runs once at retry startup, before any sample runs, and copies
  *every* sample dir the source attempt has — completed samples
  included. Checkpoints are a permanent record (planned work allows
  branching from arbitrary checkpoints), so each usable attempt is a
  complete, self-contained archive and everything older is superseded.
- **A dirty attempt is skipped.** The pass's first write is the eval
  dir's ``resume-source.json`` marker (see :class:`ResumeSource`); its
  deletion, after every copy lands, is the pass's commit point. An
  attempt whose marker is still present died during its startup copy —
  it holds nothing of its own, so the next retry follows its marker
  past it (and past any run of dead attempts) to the newest clean
  attempt and copies from there.

Resume detection then never looks past a sample's own dir
(``resolve_resumable_sample_dir``): a sample either has a committed
checkpoint in this attempt or it runs fresh.

Failures fail the retry. An interrupt or error anywhere in the pass
leaves the marker in place, this attempt errors, and the next retry
skips it — the skip *is* the recovery; there is no partial-recovery
machinery.
"""

from __future__ import annotations

from functools import partial
from logging import getLogger

import anyio

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.file import dirname
from inspect_ai._util.trace import trace_action

from ._async_fs import async_mkdir
from ._layout.sample_checkpoints_dir import (
    delete_resume_source_marker,
    read_resume_source_marker,
    write_resume_source_marker,
)

logger = getLogger(__name__)

# How many samples copy concurrently during the startup copy.
# Each sample already fans its repo copies out in parallel, and the
# shared S3 client pools 50 connections — a modest sample-level bound
# keeps the fan-out product under it.
_STARTUP_COPY_CONCURRENCY = 8


class _MissingRepoError(RuntimeError):
    """A repo subtree enumerated zero files during a payload copy."""

    def __init__(self, *, label: str, subpath: str, src_base: str) -> None:
        super().__init__(
            f"resume: expected {label} repo at {src_base}, but no files were found"
        )
        self.subpath = subpath


async def copy_resume_payloads(
    *,
    source_eval_dir: str,
    destination_eval_dir: str,
) -> None:
    """Copy every sample dir from the newest clean attempt into this one.

    Runs once at retry startup, before any sample runs.
    ``source_eval_dir`` is the retried attempt's eval checkpoints dir;
    if that attempt died during its own startup copy (its marker is
    still present) the walk follows markers back to the newest clean
    attempt and copies from there. Any failure propagates: the marker
    stays, this retry errors, and the next retry skips this attempt
    the same way.

    A same-dir retry (source and destination eval dirs coincide, e.g. a
    log location reused within the same second) has nothing to copy.
    """
    if source_eval_dir == destination_eval_dir:
        return

    with trace_action(
        logger,
        "Checkpoint Resume Copy",
        f"eval {source_eval_dir} -> {destination_eval_dir}",
    ):
        await async_mkdir(destination_eval_dir)
        await write_resume_source_marker(destination_eval_dir, source_eval_dir)

        source = await _newest_clean_attempt(source_eval_dir)
        sample_dirs = await _dir_names(source)
        if sample_dirs:
            logger.info(
                f"Checkpoint resume: copying {len(sample_dirs)} sample "
                f"dir(s) from {source}"
            )
            limiter = anyio.CapacityLimiter(_STARTUP_COPY_CONCURRENCY)
            await tg_collect(
                [
                    partial(
                        _copy_sample_dir,
                        source,
                        destination_eval_dir,
                        name,
                        limiter,
                    )
                    for name in sample_dirs
                ]
            )
        await delete_resume_source_marker(destination_eval_dir)


async def _newest_clean_attempt(source_eval_dir: str) -> str:
    """Follow dirty markers back to the newest clean attempt.

    A marker is present only on an attempt that died during its startup
    copy — clean attempts deleted theirs — so each hop skips one dead
    attempt. A dangling marker (source since deleted) resolves to the
    missing dir, which lists no sample dirs and copies nothing. A
    marker cycle can only come from corrupted markers; failing loudly
    beats silently building a "clean" attempt from a dead one.
    """
    seen: set[str] = set()
    current = source_eval_dir
    while current not in seen:
        seen.add(current)
        marker = await read_resume_source_marker(current)
        if marker is None:
            return current
        current = marker.source_dir
    raise RuntimeError(
        f"resume: cycle in resume-source markers starting at {source_eval_dir}"
    )


async def _copy_sample_dir(
    source_eval_dir: str,
    destination_eval_dir: str,
    name: str,
    limiter: anyio.CapacityLimiter,
) -> None:
    async with limiter:
        try:
            await copy_payload_files(
                f"{source_eval_dir}/{name}", f"{destination_eval_dir}/{name}"
            )
        except _MissingRepoError as ex:
            if ex.subpath != "restic/host":
                raise
            # a sample dir with no host repo (its provisioning died before
            # `restic init` finished) holds nothing committed — skipping it
            # loses nothing, and it must not poison this source forever.
            # Anything else propagates and fails the retry.
            logger.warning(f"Checkpoint resume: skipping sample dir {name}: {ex}")


async def _dir_names(base: str) -> list[str]:
    """Terminal names of ``base``'s immediate subdirectories (missing → [])."""
    names: list[str] = []
    try:
        async for uri in get_async_filesystem().iter_dirs(base):
            names.append(uri.rstrip("/").rsplit("/", 1)[-1])
    except FileNotFoundError:
        pass
    return names


async def copy_payload_files(source_dir: str, destination_dir: str) -> list[str]:
    """Copy the checkpoint payload from one sample dir to another.

    Either side may be local or remote. Copies restic repos (host +
    every ``restic/sandboxes/*`` repo the source actually has — not a
    set filtered by the current sandbox config), then the restic
    config, then checkpoint files, newest-first. Interrupt recovery
    does not depend on this order — the eval-level dirty marker covers
    the whole pass — but it keeps every intermediate state honest (no
    checkpoint file ever precedes the bytes it indexes), matching the
    order the fire path and ``host_egress`` follow.

    Also used by ``hydrate`` to pull a remote destination's payload
    into its local staging dir.

    Returns the list of paths written, relative to ``destination_dir``.
    """
    sandbox_names = await _dir_names(f"{source_dir}/restic/sandboxes")
    written_per_repo = await tg_collect(
        [
            partial(
                _fs_copy_repo,
                source_dir,
                "restic/host",
                f"{destination_dir}/restic/host",
                label="host",
            ),
            *[
                partial(
                    _fs_copy_repo,
                    source_dir,
                    f"restic/sandboxes/{name}",
                    f"{destination_dir}/restic/sandboxes/{name}",
                    label=f"sandbox {name!r}",
                )
                for name in sandbox_names
            ],
        ]
    )
    written = [path for repo_paths in written_per_repo for path in repo_paths]
    written += await _fs_copy_restic_config(source_dir, destination_dir)
    written += await _fs_copy_checkpoint_files(source_dir, destination_dir)
    return written


async def _fs_copy_restic_config(old_sample_dir: str, new_sample_dir: str) -> list[str]:
    """Copy ``restic/restic-config.json`` from old to new sample dir.

    Either side may be local or remote (e.g. ``s3://``). Returns the
    list of paths written, relative to ``new_sample_dir``.
    """
    async_fs = get_async_filesystem()
    written: list[str] = []

    with trace_action(logger, "Checkpoint Resume Copy", "fs-copy restic config"):
        src_restic_config = f"{old_sample_dir}/restic/restic-config.json"
        if await async_fs.exists(src_restic_config):
            await async_mkdir(f"{new_sample_dir}/restic")
            await async_fs.copy_file(
                src_restic_config, f"{new_sample_dir}/restic/restic-config.json"
            )
            written.append("restic/restic-config.json")
    return written


async def _fs_copy_checkpoint_files(
    old_sample_dir: str, new_sample_dir: str
) -> list[str]:
    """Copy ``ckpt-*.json`` from old to new sample dir, highest id first.

    The commit point of the payload copy: called *after* the repo and
    config copies, so a checkpoint file's presence always implies the
    bytes it indexes are in place (see ``copy_payload_files``). The
    copy is itself multi-write, so it lands the *latest* checkpoint
    first — a torn prefix must contain the newest file, or a
    partially-copied dir would resolve to a stale checkpoint
    (outranking the marker) and the orphan-snapshot drop would then
    forget every newer snapshot.

    Names that don't parse as ``ckpt-NNNNN`` are skipped: they can
    never be a committed checkpoint (the resume scan reads only
    parseable ids), so copying them could only pad the torn window.

    Either side may be local or remote (e.g. ``s3://``). Returns the
    list of paths written, relative to ``new_sample_dir``.
    """
    async_fs = get_async_filesystem()
    written: list[str] = []

    with trace_action(logger, "Checkpoint Resume Copy", "fs-copy checkpoint files"):
        entries: list[tuple[int, str]] = []
        async for uri in async_fs.iter_files(old_sample_dir, pattern="ckpt-*.json"):
            name = uri.rsplit("/", 1)[-1]
            try:
                checkpoint_id = int(name.removeprefix("ckpt-").removesuffix(".json"))
            except ValueError:
                continue
            entries.append((checkpoint_id, uri))
        await async_mkdir(new_sample_dir)
        for checkpoint_id, uri in sorted(entries, reverse=True):
            name = f"ckpt-{checkpoint_id:05d}.json"
            await async_fs.copy_file(uri, f"{new_sample_dir}/{name}")
            written.append(name)
    return written


async def _fs_copy_repo(
    old_sample_dir: str, subpath: str, new_repo: str, *, label: str
) -> list[str]:
    """Recursively copy a restic repo subtree from old sample dir to new.

    ``subpath`` is the per-domain path under the old sample checkpoints
    dir (``"restic/host"`` or ``"restic/sandboxes/<name>"``). Either
    side may be local or remote. ``label`` is a short descriptor used
    only for the trace line.

    Returns the list of paths written, relative to the new sample root
    (i.e. each path starts with ``subpath``). Raises if the source
    enumerated no files — S3 has no real directories, so existence is
    only knowable via "any object with this prefix?", and a valid restic
    repo always has at least one file (`config`).
    """
    async_fs = get_async_filesystem()
    src_base = f"{old_sample_dir}/{subpath}"
    written: list[str] = []
    # `iter_files` yields URIs verbatim-prefixed by `src_base` for S3, but
    # fsspec-normalized (absolute) for local sources — so slicing by
    # `len(src_base)` mangles local relative sources. Relativize against the
    # `/<subpath>/` repo-root boundary instead: it's the last such marker in
    # the URI (a restic repo's own tree never contains `<subpath>`), so this
    # is correct regardless of how the backend normalizes the prefix.
    boundary = f"/{subpath}/"
    with trace_action(logger, "Checkpoint Resume Copy", f"fs-copy {label}"):
        async for uri in async_fs.iter_files(src_base, recursive=True):
            rel = uri.rsplit(boundary, 1)[-1]
            dst = f"{new_repo}/{rel}"
            await async_mkdir(dirname(dst))
            await async_fs.copy_file(uri, dst)
            written.append(f"{subpath}/{rel}")
        if not written:
            raise _MissingRepoError(label=label, subpath=subpath, src_base=src_base)
    return written
