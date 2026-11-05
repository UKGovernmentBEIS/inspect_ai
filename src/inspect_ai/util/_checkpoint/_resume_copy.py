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
  runs at retry startup before ``log_start`` — nothing writes the
  destination log before that — so a copy failure raises with no
  destination log written, and the attempt dies without one. Retries
  only ever source the newest log that *exists*, so a log's existence
  proves its checkpoint dirs are complete; a dead attempt's partial
  copies are unreachable orphans. Nothing reads a dir while it is being
  copied, so the copy needs no internal ordering.
- **The copy replicates the whole attempt.** Every sample dir the
  source has is copied — completed samples included. Checkpoints are a
  permanent record (planned work allows branching from arbitrary
  checkpoints), so each attempt with a log is a complete,
  self-contained archive and everything older is superseded. The one
  exception: a sample that re-runs from scratch in this attempt (an
  invalidated prior, or a dir with no committed checkpoint) has its
  copied dir discarded before it starts.

Resume detection then never looks past a sample's own dir
(``resolve_resume_checkpoint``): a sample either has a committed
checkpoint in this attempt or it runs fresh.
"""

from __future__ import annotations

from functools import partial
from logging import getLogger
from typing import Callable, Iterable

import anyio

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import (
    get_async_filesystem,
    is_s3_filename,
    s3_bucket_and_key,
)
from inspect_ai._util.file import dirname, filesystem, local_path
from inspect_ai._util.trace import trace_action

from ._async_fs import async_mkdir
from ._layout._paths import contained_component, contained_relative

logger = getLogger(__name__)

# How many samples copy concurrently during the startup copy, and how
# many files copy concurrently within one sample dir. Their product is
# one task's share of the process-wide S3 client's 50-connection pool;
# concurrent tasks (eval_set max_tasks) share it, and requests queue on
# the pool when they exceed it.
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
    same rule). Source and destination never coincide: a log location
    repeats only when the prior attempt wrote no log, and retries never
    source such an attempt.

    A ``file://`` side is resolved to its plain path before any name is
    joined onto it: the local copy sink resolves ``file://`` URIs with
    ``local_path``, which percent-decodes, so a validated segment such
    as ``%2e%2e`` joined onto a URI would reach the OS as ``..``. The
    string containment validated must be the string the OS receives.
    """
    source_eval_dir = local_path(source_eval_dir)
    destination_eval_dir = local_path(destination_eval_dir)
    assert source_eval_dir != destination_eval_dir

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
    """Terminal names of ``base``'s immediate subdirectories (missing → []).

    Each name is joined onto the destination eval dir, and the listing is
    untrusted (an object store yields whatever keys the prefix holds), so
    a name that is not one contained path component raises rather than
    walking the copy out of the destination. The startup copy never skips
    silently, so the error names the dir and the remedy (remove it from the
    source), since it recurs on every retry until then.

    The name is the URI's own terminal segment, not ``basename()``: that
    helper strips every trailing slash and flips backslashes, so a doubled
    slash key (``<eval>//``) would collapse to the eval dir's name and a
    local dir named with a backslash to the part after it, both passing
    containment and then copying nothing. ``iter_dirs`` yields exactly one
    trailing slash.
    """
    names: list[str] = []
    try:
        async for uri in get_async_filesystem().iter_dirs(base):
            name = uri.removesuffix("/").rsplit("/", 1)[-1]
            try:
                contained_component(name)
            except ValueError as exc:
                raise ValueError(
                    f"resume copy: sample dir name {name!r} under {base} "
                    f"cannot be copied: {exc}. Remove that directory from the "
                    "source checkpoints dir to retry."
                ) from exc
            names.append(name)
    except FileNotFoundError:
        pass
    return names


async def copy_payload_files(source_dir: str, destination_dir: str) -> list[str]:
    """Copy one sample dir's checkpoint payload to another sample dir.

    Either side may be local or remote. Copies every file under the
    source except the live ``context/`` dir, bounded-parallel — restic
    repos hold many small pack files, and one awaited round-trip per
    file would serialize the startup path that gates the whole retry.
    Also used by ``hydrate`` to pull a remote destination's payload into
    its local staging dir. A missing or empty source copies nothing.

    Returns the list of paths written, relative to ``destination_dir``.
    ``file://`` URIs are resolved to plain paths first, for the reason
    given on ``copy_resume_payloads``.
    """
    source_dir = local_path(source_dir)
    destination_dir = local_path(destination_dir)
    rels = await _list_payload(source_dir)
    await _copy_payload_data(source_dir, destination_dir, rels)
    return rels


async def _list_payload(source_dir: str) -> list[str]:
    """Files under ``source_dir``, relative to it, minus the excluded top-level dirs.

    Exclusion runs before containment: an excluded dir's entries are never
    joined onto the destination, so an odd key beneath ``context/`` must not
    fail the retry over a path the copy would not have touched.
    """
    async_fs = get_async_filesystem()
    try:
        uris = [uri async for uri in async_fs.iter_files(source_dir, recursive=True)]
    except FileNotFoundError:
        uris = []
    rels = [
        rel
        for rel in _relativize(source_dir, uris)
        if rel.split("/", 1)[0] not in _EXCLUDED_TOP_LEVEL
    ]
    _check_contained(source_dir, rels)
    return rels


def _normalize_s3_uri(uri: str) -> str:
    """The form ``iter_files`` yields: bucket and key with no leading slashes."""
    bucket, key = s3_bucket_and_key(uri)
    return f"s3://{bucket}/{key}"


def _relativize(base: str, uris: Iterable[str]) -> list[str]:
    """Paths of ``uris`` relative to ``base``.

    ``iter_files`` yields URIs verbatim-prefixed by ``base`` for S3, but
    fsspec-normalized (absolute) for local sources — so slicing by
    ``len(base)`` mangles local relative sources. For local bases,
    normalize both sides the same way fsspec does before stripping the
    prefix. (S3 is handled without touching fsspec's s3fs, which is
    unavailable under the trio backend.)

    The results are verbatim remainders, not yet checked for containment:
    ``_check_contained`` runs on the subset that is actually copied.
    """
    normalize: Callable[[str], str] = (
        _normalize_s3_uri
        if is_s3_filename(base)
        else filesystem(base).fs._strip_protocol
    )
    prefix = normalize(base).rstrip("/") + "/"
    stripped = [normalize(uri) for uri in uris]
    assert all(path.startswith(prefix) for path in stripped), (stripped, prefix)
    return [path[len(prefix) :] for path in stripped]


def _check_contained(base: str, rels: Iterable[str]) -> None:
    """Raise unless every path in ``rels`` stays inside the dir it is joined onto.

    Every relative path is joined onto the destination sample dir, and
    the listing is untrusted: an object-store key may carry ``..``
    segments, a doubled slash or a leading slash. A path that is not
    contained raises rather than being copied anywhere, so a key is
    copied exactly or not at all.
    """
    for rel in rels:
        try:
            contained_relative(rel)
        except ValueError as exc:
            raise ValueError(
                f"resume copy: entry {rel!r} under {base} cannot be copied: {exc}"
            ) from exc


async def _copy_payload_data(
    source_dir: str, destination_dir: str, rels: list[str]
) -> None:
    """Bounded-parallel copy of ``rels`` from one sample dir to another."""
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
