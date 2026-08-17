"""Resume payload copying — the transport half of checkpoint resume.

Copying moves a sample's checkpoint payload (every checkpoint file,
the restic repos behind them, and the restic config) into the new
attempt's dir. It is pure file transport — no sandboxes, no live
framework state; that is hydration's restore side (``hydrate.py``),
which runs later, at sample start, and never writes anything a future
retry needs.

Copying is *greedy*: ``copy_resume_payloads`` runs once at retry
startup, before any sample runs. Copying lazily (at sample start)
loses progress across a double interrupt: a sample still queued when
the retry is interrupted has copied nothing into the new attempt's
dir, so the next retry — which resolves the immediately prior
attempt's dir — finds nothing and re-runs the sample from scratch
(#4870).

Interrupt safety rests on two things (see :class:`ResumeSource` and
``resolve_resumable_sample_dir_in_chain``):

1. The pass's very first write is the eval dir's permanent
   ``resume-source.json`` marker, recording the attempt this one
   retried. The markers link attempts into a chain; resume detection
   walks it and takes the first attempt whose sample dir holds a
   committed checkpoint. If this one write fails, the retry fails —
   everything below depends on the chain existing.
2. Within one sample, files copy in commit-point order — restic repos,
   then the restic config, then checkpoint files last and
   newest-id-first (the order the fire path and ``host_egress`` also
   follow). A torn copy therefore either holds the true latest
   checkpoint or commits nothing at all, and an uncommitted dir simply
   falls through the chain to the intact attempt behind it.

That covers every interrupt and failure the same way: a sample whose
copy failed (warned loudly), a sample still queued when the pass died,
a sample skipped as reusable that turns out invalidated, a sample a
``SampleSource`` feed injects mid-run — detection walks the chain and
finds the newest committed payload, and hydration re-copies it lazily
at sample start.
"""

from __future__ import annotations

from functools import partial
from logging import getLogger
from typing import Awaitable, Callable, NamedTuple, Sequence

import anyio

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.file import dirname
from inspect_ai._util.trace import trace_action

from ._async_fs import async_mkdir
from ._layout.sample_checkpoints_dir import (
    read_resume_source_marker,
    resolve_resumable_sample_dir,
    sample_checkpoints_dir,
    sample_dir_name,
    write_resume_source_marker,
)

logger = getLogger(__name__)

# How many samples copy concurrently during the greedy startup pass.
# Each sample already fans its repo copies out in parallel, and the
# shared S3 client pools 50 connections — a modest sample-level bound
# keeps the fan-out product under it.
_GREEDY_COPY_CONCURRENCY = 8


async def copy_resume_payloads(
    *,
    source_eval_dir: str,
    destination_eval_dir: str,
    planned: Sequence[tuple[int | str, int]],
    reusable_ids: Callable[[], Awaitable[set[tuple[int | str, int]]]],
) -> None:
    """Copy every resumable candidate's payload into this attempt's eval dir.

    Runs once at retry startup, before any sample runs (see the module
    docstring for why greedy, and for the write order interrupts rely
    on). Candidates are the ``planned`` ``(sample_id, epoch)`` pairs
    minus the ``reusable_ids`` the prior log will satisfy directly;
    candidates with nothing to resume are skipped.

    Failure handling follows the marker: the marker write is the only
    fatal step (without it the chain — and every recovery path — is
    gone). Everything after it degrades: a failure anywhere in the
    copying logs a warning and returns, and each sample then resolves
    its checkpoint lazily through the chain at sample start.

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
        # the chain link everything else depends on — written before any
        # other work, and a failure here fails the retry
        await async_mkdir(destination_eval_dir)
        await write_resume_source_marker(destination_eval_dir, source_eval_dir)
        try:
            reusable = await reusable_ids()
            candidates = [pair for pair in planned if pair not in reusable]
            if not candidates:
                return
            limiter = anyio.CapacityLimiter(_GREEDY_COPY_CONCURRENCY)
            jobs = await _resolve_copy_jobs(
                source_eval_dir, destination_eval_dir, candidates, limiter
            )
            if not jobs:
                return
            logger.info(
                f"Checkpoint resume: copying {len(jobs)} sample payload(s) from "
                f"{source_eval_dir}"
            )
            await tg_collect([partial(_copy_job, job, limiter) for job in jobs])
        except Exception as ex:
            # the chain exists, so a transient failure here (e.g. an S3
            # throttle) must not kill the retry — samples resolve their
            # checkpoints lazily through the chain at sample start
            logger.warning(
                f"Checkpoint resume copy abandoned (samples will resume "
                f"lazily instead): {ex}"
            )


class _CopyJob(NamedTuple):
    """One candidate's resolved copy: source holds a committed checkpoint."""

    sample_id: int | str
    epoch: int
    source_dir: str
    destination_dir: str


async def _resolve_copy_jobs(
    source_eval_dir: str,
    destination_eval_dir: str,
    candidates: Sequence[tuple[int | str, int]],
    limiter: anyio.CapacityLimiter,
) -> list[_CopyJob]:
    """Resolve candidates to copy jobs via the source listing chain.

    One listing per eval dir in the chain (rather than a per-candidate
    existence probe — candidate counts scale with the dataset, existing
    sample dirs only with the prior attempt's in-flight window). A
    candidate found in a listing still goes through
    ``resolve_resumable_sample_dir``; a dir with no committed
    checkpoint (e.g. a torn copy) falls through to the deeper listings
    rather than shadowing an intact payload further back.
    """
    listings = await _source_listings(source_eval_dir)

    located: list[tuple[int | str, int]] = [
        (sample_id, epoch)
        for sample_id, epoch in candidates
        if any(sample_dir_name(sample_id, epoch) in names for _, names in listings)
    ]

    async def resolve_one(sample_id: int | str, epoch: int) -> _CopyJob | None:
        name = sample_dir_name(sample_id, epoch)
        resolved = None
        async with limiter:
            for eval_dir, names in listings:
                if name in names:
                    resolved = await resolve_resumable_sample_dir(f"{eval_dir}/{name}")
                    if resolved is not None:
                        break
        if resolved is None:
            return None
        destination = sample_checkpoints_dir(destination_eval_dir, sample_id, epoch)
        if resolved.sample_dir == destination:
            return None
        return _CopyJob(
            sample_id=sample_id,
            epoch=epoch,
            source_dir=resolved.sample_dir,
            destination_dir=destination,
        )

    jobs = await tg_collect(
        [partial(resolve_one, sample_id, epoch) for sample_id, epoch in located]
    )
    return [job for job in jobs if job is not None]


async def _source_listings(source_eval_dir: str) -> list[tuple[str, set[str]]]:
    """Sample-dir names in the source eval dir, chained through eval markers.

    Each eval dir's permanent resume-source marker points at the attempt
    it retried — candidates missing from a listing (never copied there:
    the attempt's greedy pass was interrupted, or skipped them as
    reusable, or never saw them) may still exist further back, so walk
    the chain and return each dir's listing in order (nearest first).
    The seen-set bails on cycles.
    """
    seen: set[str] = set()
    listings: list[tuple[str, set[str]]] = []
    current: str | None = source_eval_dir
    while current is not None and current not in seen:
        seen.add(current)
        listings.append((current, set(await _dir_names(current))))
        marker = await read_resume_source_marker(current)
        current = marker.source_dir if marker is not None else None
    return listings


async def _dir_names(base: str) -> list[str]:
    """Terminal names of ``base``'s immediate subdirectories (missing → [])."""
    names: list[str] = []
    try:
        async for uri in get_async_filesystem().iter_dirs(base):
            names.append(uri.rstrip("/").rsplit("/", 1)[-1])
    except FileNotFoundError:
        pass
    return names


async def _copy_job(job: _CopyJob, limiter: anyio.CapacityLimiter) -> None:
    async with limiter:
        try:
            await copy_sample_payload(job.source_dir, job.destination_dir)
        except Exception as ex:
            # nothing to clean up: the torn dir commits nothing, so
            # detection falls through the chain and the sample re-copies
            # lazily at sample start, erroring there if it still fails
            logger.warning(
                f"Checkpoint resume copy failed for sample {job.sample_id} "
                f"epoch {job.epoch} (from {job.source_dir}): {ex}. The copy "
                "will be retried when the sample starts."
            )


async def copy_sample_payload(source_dir: str, destination_dir: str) -> None:
    """Copy one sample's payload from ``source_dir`` into ``destination_dir``.

    A same-dir copy (an in-eval requeue re-resolving into its own dir)
    is a no-op — the copies would copy files onto themselves.
    """
    if source_dir == destination_dir:
        return
    await copy_payload_files(source_dir, destination_dir)


async def copy_payload_files(source_dir: str, destination_dir: str) -> list[str]:
    """Copy the checkpoint payload from one sample dir to another.

    Either side may be local or remote. Write order is the commit-point
    order: restic repos (host + every ``restic/sandboxes/*`` repo the
    source actually has — not a set filtered by the current sandbox
    config), then the restic config, then checkpoint files last and
    newest-first, so a checkpoint file's presence always implies the
    bytes it indexes are in place and a torn multi-file copy still
    surfaces the *latest* checkpoint, never a stale one.

    Also used by ``hydrate`` to pull a remote destination's payload
    into its local staging dir, where the order is irrelevant (staging
    is never resolved for recovery) but harmless.

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
            raise RuntimeError(
                f"resume: expected {label} repo at {src_base}, but no files were found"
            )
    return written
