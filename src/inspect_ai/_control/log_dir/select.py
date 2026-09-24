"""Sample identity, source selection and totals for one logical task.

One function (:func:`select_source`) decides where each sample key's current
record is, and every read (task-row counts, sample rows, per-sample reads)
goes through it, so they cannot disagree. This step reads log records only;
shared sample buffers are not consulted. See "Sample identity and source
selection" in ``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from inspect_ai._util.async_zip import CentralDirectory
    from inspect_ai.log._log import EvalLog, EvalSampleSummary

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


@dataclass(frozen=True)
class MemberSnapshot:
    """One member log's plan and sample summaries, read consistently."""

    plan: LogPlan
    summaries: dict[SampleKey, EvalSampleSummary] = field(default_factory=dict)
    """Last row per key, in log order."""


class KnownKey(NamedTuple):
    """A key of the task's key set, with the id as recorded (int or str)."""

    key: SampleKey
    sample_id: int | str


def known_keys(members: list[MemberSnapshot]) -> list[KnownKey]:
    """The key set of the current attempt, in first-seen order.

    The union over the members of the recorded selection
    (``dataset.sample_ids`` times ``epochs``, when the header records ids) and
    the keys of the members' summaries. The recorded selection is a seed, not
    an index: a ``SampleSource`` can admit samples it does not record, which
    enter the set once their summaries appear.
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
    return list(seen.values())


SourceKind = Literal["log", "pending", "conflict"]


class SourceChoice(NamedTuple):
    """Result of :func:`select_source` for one key."""

    kind: SourceKind
    key: KnownKey
    member: MemberSnapshot | None
    """The member holding the chosen record (``log`` only)."""

    summary: EvalSampleSummary | None
    """The chosen record's summary (``log`` only)."""

    holders: list[MemberSnapshot]
    """Every member with a record for the key (``conflict``: more than one)."""


def select_source(members: list[MemberSnapshot], key: KnownKey) -> SourceChoice:
    """Where ``key``'s current record is: a log record, pending, or a conflict.

    More than one member holding the key (overlapping members) is a
    ``conflict``: members come from different hosts, so no timestamps are
    compared across them. A key no member holds (recorded but not started) is
    ``pending``.
    """
    holders = [m for m in members if key.key in m.summaries]
    if len(holders) > 1:
        return SourceChoice("conflict", key, None, None, holders)
    if holders:
        member = holders[0]
        return SourceChoice("log", key, member, member.summaries[key.key], holders)
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
