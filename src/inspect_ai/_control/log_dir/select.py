"""Sample identity, source selection and totals for one logical task.

One function (:func:`select_source`) decides where each sample key's current
record is, a log record or a shared-buffer row, and every read (task-row
counts, sample rows, per-sample reads) goes through it, so they cannot
disagree. See "Sample identity and source selection" in
``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NamedTuple

from inspect_ai._util.dateutil import datetime_from_iso_format_safe
from inspect_ai.log._recover._api import sample_record_time

if TYPE_CHECKING:
    from inspect_ai._util.async_zip import CentralDirectory
    from inspect_ai.log._log import EvalLog, EvalSampleSummary

    from .buffer import BufferSnapshot
    from .walk import LogFile


class SampleKey(NamedTuple):
    """A sample's identity: ``(str(id), epoch)``, the readers' dedup key."""

    id: str
    epoch: int


@dataclass(frozen=True)
class LogPlan:
    """One log's identity, read from its central directory and header."""

    file: LogFile
    central_directory: CentralDirectory
    """The central directory the header was read through."""

    header: EvalLog
    """``header.json`` for a finished log; for a running one, a header built
    from ``_journal/start.json`` (status ``started``, no results or stats)."""

    finished: bool
    """Whether the log has ``header.json``."""

    version: str | None = None
    """The version of the log object ``central_directory`` was read from
    (see :func:`~.consistency.read_version`); ``None`` when unknown."""

    @property
    def running(self) -> bool:
        """Whether the log's status is ``started``."""
        return self.header.status == "started"

    @property
    def shared_buffer(self) -> bool:
        """Whether a running log may have a shared buffer to read.

        The eval ran with ``log_shared`` and the walk saw a ``.buffer/``
        beside the log.
        """
        return (
            self.running
            and bool(self.header.eval.config.log_shared)
            and self.file.buffer_dir is not None
        )


@dataclass(frozen=True)
class MemberSnapshot:
    """One member log's plan, sample summaries and manifest, read consistently."""

    plan: LogPlan
    summaries: dict[SampleKey, EvalSampleSummary] = field(default_factory=dict)
    """Last row per key, in log order."""

    buffer: BufferSnapshot | None = None
    """The member's shared-buffer manifest, when one was read."""

    @property
    def live_samples(self) -> bool | None:
        """Whether this member's running samples are visible.

        ``None`` for a member whose log is not running.
        """
        if not self.plan.running:
            return None
        return self.buffer is not None


class KnownKey(NamedTuple):
    """A key of the task's key set, with the id as recorded (int or str)."""

    key: SampleKey
    sample_id: int | str


def known_keys(members: list[MemberSnapshot]) -> list[KnownKey]:
    """The key set of the current attempt, in first-seen order.

    The union over the members of the recorded selection
    (``dataset.sample_ids`` times ``epochs``, when the header records ids),
    the keys of the members' summaries and the keys of their manifest rows.
    The recorded selection is a seed, not an index: a ``SampleSource`` can
    admit samples it does not record, which enter the set once their
    summaries or manifest rows appear.
    """
    seen: dict[SampleKey, KnownKey] = {}
    for member in members:
        spec = member.plan.header.eval
        epochs = max(1, spec.config.epochs or 1)
        for sample_id in spec.dataset.sample_ids or []:
            for epoch in range(1, epochs + 1):
                key = SampleKey(str(sample_id), epoch)
                seen.setdefault(key, KnownKey(key, sample_id))
        for key, summary in member.summaries.items():
            seen.setdefault(key, KnownKey(key, summary.id))
        if member.buffer is not None:
            for key, row in member.buffer.samples.items():
                seen.setdefault(key, KnownKey(key, row.summary.id))
    return list(seen.values())


SourceKind = Literal["log", "buffer", "pending", "conflict"]


class Candidate(NamedTuple):
    """One member's current record for a key (see :func:`member_candidate`)."""

    kind: Literal["log", "buffer"]
    summary: EvalSampleSummary


def member_candidate(member: MemberSnapshot, key: SampleKey) -> Candidate | None:
    """The member's current record for ``key``: its buffer row or its log record.

    The buffer row wins when the log has no record for the key, or when the
    row started after the log record's ``sample_record_time`` (a seeded retry
    re-running a key it inherited, or an in-process requeue of a flushed key:
    recovery's rule). Both timestamps come from the one worker that wrote the
    member. Otherwise the log record wins: a buffer row that started before
    it is the same attempt, already flushed.
    """
    logged = member.summaries.get(key)
    row = member.buffer.samples.get(key) if member.buffer is not None else None
    if row is not None and (logged is None or _started_after(row.summary, logged)):
        return Candidate("buffer", row.summary)
    if logged is not None:
        return Candidate("log", logged)
    return None


def _started_after(buffered: EvalSampleSummary, logged: EvalSampleSummary) -> bool:
    ended = sample_record_time(logged)
    started = (
        datetime_from_iso_format_safe(buffered.started_at)
        if buffered.started_at is not None
        else None
    )
    return ended is not None and started is not None and started > ended


class SourceChoice(NamedTuple):
    """Result of :func:`select_source` for one key."""

    kind: SourceKind
    key: KnownKey
    member: MemberSnapshot | None
    """The member holding the chosen record (``log`` and ``buffer`` only)."""

    summary: EvalSampleSummary | None
    """The chosen record's summary (``log`` and ``buffer`` only)."""

    holders: list[MemberSnapshot]
    """Every member with a record for the key (``conflict``: more than one)."""


def select_source(members: list[MemberSnapshot], key: KnownKey) -> SourceChoice:
    """Where ``key``'s current record is: a log record, a buffer row, pending, or a conflict.

    More than one member holding the key (overlapping members) is a
    ``conflict``: members come from different hosts, so no timestamps are
    compared across them. Within one member, :func:`member_candidate` picks
    the record. A key no member holds (recorded but not started, or started
    with no shared buffer) is ``pending``.
    """
    candidates = [
        (m, c) for m in members if (c := member_candidate(m, key.key)) is not None
    ]
    holders = [m for m, _ in candidates]
    if len(candidates) > 1:
        return SourceChoice("conflict", key, None, None, holders)
    if candidates:
        member, candidate = candidates[0]
        return SourceChoice(candidate.kind, key, member, candidate.summary, holders)
    return SourceChoice("pending", key, None, None, [])


class Totals(NamedTuple):
    """A logical task's sample total (see :func:`totals`)."""

    total: int
    total_final: bool
    """Whether ``total`` is an authoritative total rather than a lower bound."""

    pending_unlisted: int | None
    """Pending samples the authoritative total counts but no record names
    (``None`` when the total is not final)."""


def authoritative_total(plan: LogPlan) -> int | None:
    """A finished log's ``results.total_samples``, which counts admitted samples.

    ``None`` for a running log and for a finished one without ``results`` (an
    eval that failed before any sample was scored).
    """
    if not plan.finished or plan.header.results is None:
        return None
    return plan.header.results.total_samples


def totals(authoritative: int | None, known: int) -> Totals:
    """The total over ``known`` keys, final only when an authoritative total covers them.

    An authoritative total below the known-key count (samples it does not
    count) is not final; the known-key count is reported instead.
    """
    if authoritative is None or authoritative < known:
        return Totals(total=known, total_final=False, pending_unlisted=None)
    return Totals(
        total=authoritative,
        total_final=True,
        pending_unlisted=authoritative - known,
    )
