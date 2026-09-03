"""Resume payload copying — the transport half of checkpoint resume.

Copying replicates sample checkpoint dirs from the attempt being retried
into the new attempt's eval checkpoints dir, verbatim: every file a
sample dir holds (the host restic repo, each sandbox strategy's storage
area, the restic config, the strategy pin, the checkpoint files) except
the live ``context/`` working dir, whose contents are already inside
the host repo. The copy knows nothing about the layout beneath a sample
dir — strategy storage areas are opaque file trees — which is what
lets ``hydrate`` skip any per-strategy "adopt prior state" step. It is
pure file transport — no sandboxes, no live framework state; that is
hydration's restore side (``hydrate.py``), which runs later, at sample
start, and never writes anything a future retry needs.

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
from typing import Iterable

import anyio

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.file import dirname, filesystem
from inspect_ai._util.trace import trace_action

from ._async_fs import async_mkdir

logger = getLogger(__name__)

# How many samples copy concurrently during the startup copy, and how
# many files copy concurrently within one sample dir. The product must
# stay under the shared S3 client's 50-connection pool.
_STARTUP_COPY_CONCURRENCY = 8
_SAMPLE_FILE_COPY_CONCURRENCY = 6

# Top-level names in a sample dir that are not payload. ``context/`` is
# the host restic backup source — its committed contents live in the
# host repo, and restore re-materializes it from there.
_EXCLUDED_TOP_LEVEL: frozenset[str] = frozenset({"context"})


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
                        f"{source_eval_dir}/{name}",
                        f"{destination_eval_dir}/{name}",
                        limiter,
                    )
                    for name in sample_dirs
                ]
            )


async def _copy_sample_dir(
    source_dir: str, destination_dir: str, limiter: anyio.CapacityLimiter
) -> None:
    async with limiter:
        await copy_payload_files(source_dir, destination_dir)


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
    """Copy one sample dir's checkpoint payload to another sample dir.

    Either side may be local or remote. Copies every file under the
    source except the live ``context/`` dir, in two passes: everything
    that is not a checkpoint file (bounded-parallel — restic repos hold
    many small pack files, and one awaited round-trip per file would
    serialize the startup path that gates the whole retry), then the
    ``ckpt-*.json`` files, newest first. Interrupt recovery does not
    depend on this order — the destination log's deferred first write
    gates the whole pass — but it keeps every intermediate state honest
    (no checkpoint file ever precedes the bytes it indexes), matching
    the order the fire path and ``host_egress`` follow.

    Also used by ``hydrate`` to pull a remote destination's payload
    into its local staging dir. A missing or empty source copies
    nothing.

    Returns the list of paths written, relative to ``destination_dir``.
    """
    data, checkpoints = await _list_payload(source_dir)
    written = await _copy_payload_data(source_dir, destination_dir, data)
    written += await _copy_checkpoint_files(source_dir, destination_dir, checkpoints)
    return written


async def _list_payload(source_dir: str) -> tuple[list[str], list[str]]:
    """Relative paths under ``source_dir``: (non-checkpoint files, checkpoint files).

    Checkpoint files come back newest first. Names under an excluded
    top-level dir are dropped.
    """
    async_fs = get_async_filesystem()
    try:
        uris = [uri async for uri in async_fs.iter_files(source_dir, recursive=True)]
    except FileNotFoundError:
        uris = []
    rels = _relativize(source_dir, uris)
    data = [
        rel
        for rel in rels
        if rel.split("/", 1)[0] not in _EXCLUDED_TOP_LEVEL
        and _checkpoint_id(rel) is None
    ]
    checkpoints = sorted(
        (rel for rel in rels if _checkpoint_id(rel) is not None),
        key=lambda rel: _checkpoint_id(rel) or 0,
        reverse=True,
    )
    return data, checkpoints


def _relativize(base: str, uris: Iterable[str]) -> list[str]:
    """Paths of ``uris`` relative to ``base``.

    ``iter_files`` yields URIs verbatim-prefixed by ``base`` for S3, but
    fsspec-normalized (absolute) for local sources — so slicing by
    ``len(base)`` mangles local relative sources. Normalize both sides
    the same way the backend does before stripping the prefix.
    """
    fs = filesystem(base).fs
    prefix = fs._strip_protocol(base).rstrip("/") + "/"
    rels: list[str] = []
    for uri in uris:
        stripped = fs._strip_protocol(uri)
        assert stripped.startswith(prefix), (stripped, prefix)
        rels.append(stripped[len(prefix) :])
    return rels


def _checkpoint_id(rel: str) -> int | None:
    """The id of a top-level ``ckpt-NNNNN.json`` path, else ``None``."""
    if "/" in rel or not (rel.startswith("ckpt-") and rel.endswith(".json")):
        return None
    try:
        return int(rel.removeprefix("ckpt-").removesuffix(".json"))
    except ValueError:
        return None


async def _copy_payload_data(
    source_dir: str, destination_dir: str, rels: list[str]
) -> list[str]:
    """Bounded-parallel copy of the non-checkpoint payload files."""
    async_fs = get_async_filesystem()
    with trace_action(logger, "Checkpoint Resume Copy", "fs-copy payload"):
        for parent in {dirname(f"{destination_dir}/{rel}") for rel in rels}:
            await async_mkdir(parent)
        limiter = anyio.CapacityLimiter(_SAMPLE_FILE_COPY_CONCURRENCY)

        async def copy_one(rel: str) -> None:
            async with limiter:
                await async_fs.copy_file(
                    f"{source_dir}/{rel}", f"{destination_dir}/{rel}"
                )

        await tg_collect([partial(copy_one, rel) for rel in rels])
    return list(rels)


async def _copy_checkpoint_files(
    source_dir: str, destination_dir: str, rels: list[str]
) -> list[str]:
    """Sequential copy of the checkpoint files, in the order given (newest first).

    The commit point of the payload copy: called after the data pass,
    so a checkpoint file's presence always implies the bytes it indexes
    are in place. Landing the latest first means a torn prefix still
    resolves to the newest checkpoint rather than a stale one.
    """
    async_fs = get_async_filesystem()
    with trace_action(logger, "Checkpoint Resume Copy", "fs-copy checkpoint files"):
        if rels:
            await async_mkdir(destination_dir)
        for rel in rels:
            await async_fs.copy_file(f"{source_dir}/{rel}", f"{destination_dir}/{rel}")
    return list(rels)
