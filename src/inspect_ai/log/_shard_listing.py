"""Hide shard logs that their merged log already covers from viewer listings."""

from __future__ import annotations

from typing import TYPE_CHECKING, AbstractSet, NamedTuple

from inspect_ai._util.log_layout import merged_log_candidates_for_shard

if TYPE_CHECKING:
    from ._file import EvalLogInfo


class MergedShardsFilter(NamedTuple):
    """A log listing with merged shard logs removed."""

    logs: list[EvalLogInfo]
    """The logs to show."""

    has_shards: bool
    """Whether the listing contained any shard log, hidden or not."""


def merged_logs_with_shards(logs: list[EvalLogInfo]) -> list[EvalLogInfo]:
    """Return the merged logs in the listing that have shards in the listing.

    These are the logs whose status :func:`filter_merged_shards` needs.
    """
    names = {log.name for log in logs}
    merged: set[str] = set()
    for log in logs:
        candidates = merged_log_candidates_for_shard(log.name)
        if candidates is not None:
            merged.update(c for c in candidates if c in names)
    return [log for log in logs if log.name in merged]


def filter_merged_shards(
    logs: list[EvalLogInfo], running: AbstractSet[str]
) -> MergedShardsFilter:
    """Remove shard logs already covered by their merged log.

    A shard at ``<dir>/<name>.shards/<k>/`` is hidden when its merged log
    (``<dir>/<name>.eval``) is in the same listing, is not still running, and
    the shard was last written before it. A tie keeps the shard visible,
    since coarse mtimes (one second on S3) cannot order a shard write and a
    merge in the same tick. A shard with no merged log in the listing, or
    written after the merge (still running, retried, or added later), stays
    visible so ongoing work is never hidden. Listing the ``.shards``
    directory itself shows every shard, since the merged log is outside it.

    Comparing mtimes needs no reads beyond the listing, so it works for any
    merger that writes the merged log after reading its shards. A merge run
    while shards are still running leaves the merged log ``started``; its
    shards stay visible then, because a running shard's file is rewritten
    only at log flushes and can be older than the merge while it runs.

    Args:
        logs: The listing.
        running: Names of merged logs whose status is ``started`` (or could
            not be read). Their shards are never hidden.
    """
    mtimes = {log.name: log.mtime for log in logs}
    visible: list[EvalLogInfo] = []
    has_shards = False
    for log in logs:
        candidates = merged_log_candidates_for_shard(log.name)
        if candidates is None:
            visible.append(log)
            continue
        has_shards = True
        merged_mtime = _merged_log_mtime(candidates, mtimes, running)
        if merged_mtime is None or log.mtime is None or log.mtime >= merged_mtime:
            visible.append(log)
    return MergedShardsFilter(logs=visible, has_shards=has_shards)


def _merged_log_mtime(
    candidates: list[str],
    mtimes: dict[str, float | None],
    running: AbstractSet[str],
) -> float | None:
    """Return the oldest mtime among the merged logs present in the listing.

    When both ``<name>.eval`` and ``<name>-recovered.eval`` exist, either may
    be stale, so the older one decides and fewer shards are hidden. Returns
    ``None`` (hide nothing) if any present merged log is still running.
    """
    present = [c for c in candidates if c in mtimes]
    if not present or any(c in running for c in present):
        return None
    merged = [m for c in present if (m := mtimes[c]) is not None]
    return min(merged) if len(merged) == len(present) else None
