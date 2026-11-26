"""Hide shard logs that their merged log already covers from viewer listings."""

from __future__ import annotations

from typing import TYPE_CHECKING, AbstractSet, NamedTuple

from inspect_ai._util.log_layout import merged_log_for_shard

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
        merged = merged_log_for_shard(log.name)
        if merged is None or log.mtime is None:
            continue
        merged_mtime = mtimes.get(merged)
        if merged_mtime is not None and log.mtime < merged_mtime:
            names.add(merged)
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
        merged = merged_log_for_shard(log.name)
        if merged is None:
            visible.append(log)
            continue
        merged_mtime = mtimes.get(merged) if merged in finished else None
        if merged_mtime is None or log.mtime is None or log.mtime >= merged_mtime:
            visible.append(log)
            visible_shards = True
    return MergedShardsFilter(logs=visible, visible_shards=visible_shards)
