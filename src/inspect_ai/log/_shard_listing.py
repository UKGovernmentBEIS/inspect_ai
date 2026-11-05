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

    visible_shards: bool
    """Whether any shard log was left visible."""


def merged_logs_to_check(logs: list[EvalLogInfo]) -> list[EvalLogInfo]:
    """Return the merged logs whose status decides whether shards are hidden.

    These are the merged logs in the listing that are newer than at least one
    of their shards in the listing; no other merged log can hide a shard, so
    only these need their headers read.
    """
    mtimes = {log.name: log.mtime for log in logs}
    names: set[str] = set()
    for log in logs:
        candidates = merged_log_candidates_for_shard(log.name)
        if candidates is None or log.mtime is None:
            continue
        for candidate in candidates:
            merged_mtime = mtimes.get(candidate)
            if merged_mtime is not None and log.mtime < merged_mtime:
                names.add(candidate)
    return [log for log in logs if log.name in names]


def filter_merged_shards(
    logs: list[EvalLogInfo], finished: AbstractSet[str]
) -> MergedShardsFilter:
    """Remove shard logs already covered by their merged log.

    A shard at ``<dir>/<name>.shards/<k>/`` is hidden when its merged log
    (``<dir>/<name>.eval``) is in the same listing with status ``success``
    and the shard was last written before it. A tie keeps the shard visible,
    since coarse mtimes (one second on S3) cannot order a shard write and a
    merge in the same tick. A shard with no merged log in the listing, or
    written after the merge (retried, or added later), stays visible so
    ongoing work is never hidden. Listing the ``.shards`` directory itself
    shows every shard, since the merged log is outside it.

    Comparing mtimes needs no reads beyond the listing, so it works for any
    merger that writes the merged log after reading its shards. The status
    condition keeps running shards visible: a running shard's file is
    rewritten only at log flushes, so it can be older than a merge run while
    it is still producing samples, and a merge publishes ``success`` only
    once every shard has finished. Shards of a failed or cancelled run stay
    visible too.

    Args:
        logs: The listing.
        finished: Names of merged logs whose status is ``success`` (see
            :func:`merged_logs_to_check`). Shards of other merged logs are
            never hidden.
    """
    mtimes = {log.name: log.mtime for log in logs}
    visible: list[EvalLogInfo] = []
    visible_shards = False
    for log in logs:
        candidates = merged_log_candidates_for_shard(log.name)
        if candidates is None:
            visible.append(log)
            continue
        merged_mtime = _merged_log_mtime(candidates, mtimes, finished)
        if merged_mtime is None or log.mtime is None or log.mtime >= merged_mtime:
            visible.append(log)
            visible_shards = True
    return MergedShardsFilter(logs=visible, visible_shards=visible_shards)


def _merged_log_mtime(
    candidates: list[str],
    mtimes: dict[str, float | None],
    finished: AbstractSet[str],
) -> float | None:
    """Return the oldest mtime among the merged logs present in the listing.

    When both ``<name>.eval`` and ``<name>-recovered.eval`` exist, either may
    be stale, so the older one decides and fewer shards are hidden. Returns
    ``None`` (hide nothing) unless every present merged log is finished.
    """
    present = [c for c in candidates if c in mtimes]
    if not present or any(c not in finished for c in present):
        return None
    merged = [m for c in present if (m := mtimes[c]) is not None]
    return min(merged) if len(merged) == len(present) else None
