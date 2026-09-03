"""Resume payload copying — the transport half of checkpoint resume.

Copying replicates sample checkpoint payloads (every checkpoint file,
the host restic repo and each sandbox strategy's storage area behind
them, the restic config, and the strategy pin) from the attempt being
retried into the new attempt's eval checkpoints dir. It is pure file
transport — no sandboxes, no live framework state; that is hydration's
restore side (``hydrate.py``), which runs later, at sample start, and
never writes anything a future retry needs. Strategy storage areas are
opaque to the copy: it replicates whatever file tree the source has
under each one, which is what lets ``hydrate`` skip any per-strategy
"adopt prior state" step.

The design is one rule with two supports:

- **A retry's log is its checkpoint commit point.** ``copy_resume_payloads``
  runs at retry startup *before the destination log's first write* — a
  retry attempt defers every destination log write until its reuse
  sweep settles (see ``design/retry-deferred-destination-log.md``), and
  a copy failure raises before ``log_start``, so the attempt dies
  without a destination log. Retries only ever source the newest log
  that *exists*, so a log's existence proves its checkpoint dirs are
  complete; a dead attempt's partial copies are unreachable orphans.
- **The copy replicates the whole attempt.** Every sample dir the
  source has is copied — completed samples included. Checkpoints are a
  permanent record (planned work allows branching from arbitrary
  checkpoints), so each attempt with a log is a complete,
  self-contained archive and everything older is superseded.

Resume detection then never looks past a sample's own dir
(``resolve_resumable_sample_dir``): a sample either has a committed
checkpoint in this attempt or it runs fresh. Within one sample, files
still copy in commit-point order (checkpoint files last, newest-first)
so every intermediate state stays honest, though recovery no longer
depends on it.
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
from ._snapshot.pin import STRATEGY_PIN_SUBPATH

logger = getLogger(__name__)

# How many samples copy concurrently during the startup copy, and how
# many files copy concurrently within one storage area. Each sample
# fans its storage-area copies out in parallel (host repo + each
# sandbox's area), so the fan-out product — samples × areas × files —
# must stay under the shared S3 client's 50-connection pool
# (8 × 2 × 3 = 48 for the common one-sandbox case).
_STARTUP_COPY_CONCURRENCY = 8
_REPO_FILE_COPY_CONCURRENCY = 3


class _MissingRepoError(RuntimeError):
    """A storage-area subtree enumerated zero files during a payload copy."""

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
    """Copy every sample dir from the retried attempt into this one.

    Runs at retry startup, before the destination log's first write —
    a failure here must raise before ``log_start`` so the attempt dies
    without a destination log and the next retry falls back to the
    newest log that exists (whose checkpoint dirs are complete by the
    same rule).

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
        sample_dirs = await _dir_names(source_eval_dir)
        if sample_dirs:
            logger.info(
                f"Checkpoint resume: copying {len(sample_dirs)} sample "
                f"dir(s) from {source_eval_dir}"
            )
            limiter = anyio.CapacityLimiter(_STARTUP_COPY_CONCURRENCY)
            await tg_collect(
                [
                    partial(
                        _copy_sample_dir,
                        source_eval_dir,
                        destination_eval_dir,
                        name,
                        limiter,
                    )
                    for name in sample_dirs
                ]
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

    Either side may be local or remote. Copies the host restic repo and
    every sandbox storage area the source actually has (each restic
    sandbox repo under ``restic/sandboxes/`` and each other strategy's
    area under ``sandboxes/<name>/<strategy>/`` — not a set filtered by
    the current sandbox config), then the cross-cutting files (restic
    config, strategy pin), then checkpoint files, newest-first.
    Interrupt recovery does not depend on this order — the destination
    log's deferred first write gates the whole pass — but it keeps
    every intermediate state honest (no checkpoint file ever precedes
    the bytes it indexes), matching the order the fire path and
    ``host_egress`` follow.

    Also used by ``hydrate`` to pull a remote destination's payload
    into its local staging dir.

    Returns the list of paths written, relative to ``destination_dir``.
    """
    storage_subpaths = await _sandbox_storage_subpaths(source_dir)
    written_per_area = await tg_collect(
        [
            partial(
                _fs_copy_repo,
                source_dir,
                "restic/host",
                f"{destination_dir}/restic/host",
                label="host",
            ),
            *[
                partial(_copy_sandbox_storage, source_dir, subpath, destination_dir)
                for subpath in storage_subpaths
            ],
        ]
    )
    written = [path for area_paths in written_per_area for path in area_paths]
    written += await _fs_copy_cross_cutting(source_dir, destination_dir)
    written += await _fs_copy_checkpoint_files(source_dir, destination_dir)
    return written


async def _sandbox_storage_subpaths(source_dir: str) -> list[str]:
    """Every sandbox storage area the source sample dir has.

    Mirrors ``strategy_storage_subpath``'s layout: the restic strategy
    stores at ``restic/sandboxes/<name>``, every other strategy at
    ``sandboxes/<name>/<strategy>``. Enumerated from the source rather
    than derived from config so the copy carries exactly what the
    retried attempt captured.
    """
    subpaths = [
        f"restic/sandboxes/{name}"
        for name in await _dir_names(f"{source_dir}/restic/sandboxes")
    ]
    for name in await _dir_names(f"{source_dir}/sandboxes"):
        subpaths += [
            f"sandboxes/{name}/{strategy}"
            for strategy in await _dir_names(f"{source_dir}/sandboxes/{name}")
        ]
    return subpaths


async def _copy_sandbox_storage(
    source_dir: str, subpath: str, destination_dir: str
) -> list[str]:
    """Copy one sandbox storage area, tolerating an empty source dir.

    On local filesystems a fire interrupted between a strategy's
    ``mkdir`` of its storage area and its first write there leaves an
    empty area inside an attempt that has a log. The fire path writes
    its checkpoint file only after every strategy's snapshot completes,
    so an empty area can never back a committed checkpoint — skipping
    it loses nothing, and raising would poison every future retry of
    that attempt.
    """
    try:
        return await _fs_copy_repo(
            source_dir, subpath, f"{destination_dir}/{subpath}", label=subpath
        )
    except _MissingRepoError as ex:
        logger.warning(f"Checkpoint resume: skipping empty sandbox storage: {ex}")
        return []


async def _fs_copy_cross_cutting(old_sample_dir: str, new_sample_dir: str) -> list[str]:
    """Copy the core-owned per-sample files that belong to no one storage area.

    Exactly ``restic/restic-config.json`` (the per-sample secret) and
    the strategy pin (``restic/snapshot-strategies.json``), each when
    present. Either side may be local or remote (e.g. ``s3://``).
    Returns the list of paths written, relative to ``new_sample_dir``.
    """
    async_fs = get_async_filesystem()
    written: list[str] = []

    with trace_action(logger, "Checkpoint Resume Copy", "fs-copy cross-cutting"):
        for subpath in ("restic/restic-config.json", STRATEGY_PIN_SUBPATH):
            src = f"{old_sample_dir}/{subpath}"
            if await async_fs.exists(src):
                await async_mkdir(dirname(f"{new_sample_dir}/{subpath}"))
                await async_fs.copy_file(src, f"{new_sample_dir}/{subpath}")
                written.append(subpath)
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
    partially-copied dir would resolve to a stale checkpoint and the
    orphan-snapshot drop would then forget every newer snapshot.

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
    """Recursively copy a storage-area subtree from old sample dir to new.

    ``subpath`` is the area's path under the old sample checkpoints dir
    (``"restic/host"``, ``"restic/sandboxes/<name>"``, or another
    strategy's ``"sandboxes/<name>/<strategy>"``). Either side may be
    local or remote. ``label`` is a short descriptor used only for the
    trace line.

    Returns the list of paths written, relative to the new sample root
    (i.e. each path starts with ``subpath``). Raises if the source
    enumerated no files — S3 has no real directories, so existence is
    only knowable via "any object with this prefix?", and a populated
    storage area always has at least one file (a restic repo's
    `config`; an archive strategy's first archive).
    """
    async_fs = get_async_filesystem()
    src_base = f"{old_sample_dir}/{subpath}"
    # `iter_files` yields URIs verbatim-prefixed by `src_base` for S3, but
    # fsspec-normalized (absolute) for local sources — so slicing by
    # `len(src_base)` mangles local relative sources. Relativize against the
    # `/<subpath>/` area-root boundary instead: it's the last such marker in
    # the URI (a storage area's own tree never contains `<subpath>`), so
    # this is correct regardless of how the backend normalizes the prefix.
    boundary = f"/{subpath}/"
    with trace_action(logger, "Checkpoint Resume Copy", f"fs-copy {label}"):
        rels = [
            uri.rsplit(boundary, 1)[-1]
            async for uri in async_fs.iter_files(src_base, recursive=True)
        ]
        if not rels:
            raise _MissingRepoError(label=label, subpath=subpath, src_base=src_base)
        # one mkdir per distinct parent, then bounded-parallel file copies:
        # restic repos hold many small pack files, and one awaited
        # round-trip per file would serialize the startup path that gates
        # the whole retry. Intra-area order doesn't matter (the checkpoint
        # files that index these bytes copy separately, afterward).
        for parent in {dirname(f"{new_repo}/{rel}") for rel in rels}:
            await async_mkdir(parent)
        limiter = anyio.CapacityLimiter(_REPO_FILE_COPY_CONCURRENCY)

        async def copy_one(rel: str) -> None:
            async with limiter:
                await async_fs.copy_file(f"{src_base}/{rel}", f"{new_repo}/{rel}")

        await tg_collect([partial(copy_one, rel) for rel in rels])
    return [f"{subpath}/{rel}" for rel in rels]
