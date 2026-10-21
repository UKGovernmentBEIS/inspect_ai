"""Planning a shard merge: validation, the sample set, status and header.

Pure functions over what a merge pass has read: the merged log's header and
sample members, the shard listing, and the attempts read in the pass.
"""

import hashlib
import json
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime
from typing import Literal, NamedTuple

from shortuuid import uuid

from inspect_ai._util.async_zip import CentralDirectory
from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.error import EvalError
from inspect_ai._util.file import FileInfo
from inspect_ai._util.log_layout import merged_log_task_id
from inspect_ai._util.zip_common import ZipEntry
from inspect_ai.log._log import (
    EvalLog,
    EvalResults,
    EvalSampleSummary,
    EvalShardEntry,
    EvalShards,
    EvalStats,
    EvalStatus,
)
from inspect_ai.log._recorders.recorder import SampleRecordKey
from inspect_ai.model._model_output import ModelUsage

from ._errors import ShardSelectionError, ShardSetError
from ._walk import ShardDir, _name, attempt_sort_key

_SAMPLES_PREFIX = "samples/"
_EPOCH_SEPARATOR = "_epoch_"
_MAX_IDS_SHOWN = 10


def parse_sample_member(name: str) -> SampleRecordKey | None:
    """The ``(str(id), epoch)`` key of a monolith sample member name.

    ``samples/{id}_epoch_{epoch}.json``, split at the last ``_epoch_`` so an
    id containing ``/`` or ``_epoch_`` parses. ``None`` for any other name.
    """
    if not name.startswith(_SAMPLES_PREFIX) or not name.endswith(".json"):
        return None
    stem = name[len(_SAMPLES_PREFIX) : -len(".json")]
    id, separator, epoch = stem.rpartition(_EPOCH_SEPARATOR)
    if not separator or not (epoch.isascii() and epoch.isdigit()):
        return None
    if str(int(epoch)) != epoch:
        return None
    return SampleRecordKey(id, int(epoch))


def merged_records(cd: CentralDirectory, location: str) -> set[SampleRecordKey]:
    """The sample records of a merged log, from its member names.

    Raises:
        ShardSetError: A ``samples/`` member is not a monolith sample name;
            the merge writes only those, so the log was rewritten outside it.
    """
    records: set[SampleRecordKey] = set()
    for entry in cd.entries:
        if entry.filename.startswith(_SAMPLES_PREFIX):
            key = parse_sample_member(entry.filename)
            if key is None:
                raise ShardSetError(
                    f"{location} has a sample member the merge did not write "
                    f"({entry.filename}). Delete it so the next merge rebuilds it "
                    "from the shards."
                )
            records.add(key)
    return records


def selection_digest(ids: Iterable[str | int]) -> str:
    """SHA-256 (hex) of a selection, independent of order and of ``1`` vs ``"1"``."""
    canonical = json.dumps(
        sorted({str(i) for i in ids}), ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class Selection(NamedTuple):
    """The intended selection of a merge."""

    form: Literal["ids", "count", "none"]
    ids: list[str | int] | None = None
    sample_count: int | None = None

    def id_set(self) -> frozenset[str] | None:
        return frozenset(str(i) for i in self.ids) if self.ids is not None else None

    def same_as(self, other: "Selection") -> bool:
        if self.form != other.form:
            return False
        if self.form == "ids":
            return self.id_set() == other.id_set()
        return self.sample_count == other.sample_count

    def describe(self) -> str:
        if self.form == "ids":
            return f"{len(self.id_set() or [])} sample ids"
        if self.form == "count":
            return f"a count of {self.sample_count} samples"
        return "no selection (the whole dataset)"


def given_selection(
    sample_ids: Sequence[str | int] | None, sample_count: int | None
) -> Selection | None:
    """The selection passed by the caller, or ``None``.

    Raises:
        ValueError: Both are given, `sample_ids` is empty, or `sample_count`
            is below 1.
    """
    if sample_ids is not None and sample_count is not None:
        raise ValueError("Pass at most one of sample_ids and sample_count.")
    if sample_ids is not None:
        if isinstance(sample_ids, str) or len(sample_ids) == 0:
            raise ValueError("sample_ids must be a non-empty list of sample ids.")
        return Selection("ids", ids=list(sample_ids))
    if sample_count is not None:
        if sample_count < 1:
            raise ValueError("sample_count must be at least 1.")
        return Selection("count", sample_count=sample_count)
    return None


def recorded_selection(header: EvalLog) -> Selection:
    """The selection a merged log records (see `EvalShards.selection`)."""
    shards = header.eval.shards
    assert shards is not None
    if shards.selection == "ids":
        return Selection("ids", ids=list(header.eval.dataset.sample_ids or []))
    if shards.selection == "count":
        return Selection("count", sample_count=shards.sample_count)
    return Selection("none")


class AttemptRead(NamedTuple):
    """A shard's current attempt, read in this pass."""

    shard: str
    """The shard directory name, ``<k>``."""

    file: FileInfo
    """The attempt as listed."""

    header: EvalLog
    """Its header (synthesised from the journal while it runs)."""

    summaries: dict[SampleRecordKey, EvalSampleSummary]
    """Summaries of the records it holds (listed and with a sample member)."""

    members: dict[SampleRecordKey, ZipEntry]
    """The sample member of each held record."""

    etag: str | None
    """ETag of the bytes read, when the store reports one."""

    @property
    def selection(self) -> frozenset[str] | None:
        ids = self.header.eval.dataset.sample_ids
        return frozenset(str(i) for i in ids) if ids is not None else None


def is_unchanged(entry: EvalShardEntry | None, current: FileInfo) -> bool:
    """Whether a shard's current attempt is the one its ledger entry recorded."""
    if entry is None or entry.log != _name(current.name):
        return False
    if entry.etag is not None and current.etag is not None:
        return entry.etag == current.etag
    return entry.size == current.size and entry.mtime == current.mtime


def ledger_entry(read: AttemptRead) -> EvalShardEntry:
    """The ledger entry for an attempt read in this pass."""
    header = read.header
    ids = header.eval.dataset.sample_ids or []
    return EvalShardEntry(
        shard=read.shard,
        log=_name(read.file.name),
        eval_set_id=header.eval.eval_set_id,
        status=header.status,
        error=header.error if header.status in ("error", "cancelled") else None,
        samples=len(read.summaries),
        selected=len({str(i) for i in ids}),
        selection_digest=selection_digest(ids),
        started_at=header.stats.started_at,
        completed_at=header.stats.completed_at,
        model_usage=header.stats.model_usage,
        role_usage=header.stats.role_usage,
        size=read.file.size,
        etag=read.etag if read.etag is not None else read.file.etag,
        mtime=read.file.mtime,
    )


def attempt_regressed(shard: ShardDir, entry: EvalShardEntry) -> bool:
    """Whether a shard's current attempt sorts before the recorded one."""
    current = shard.current
    assert current is not None
    if _name(current.name) == entry.log:
        return False
    recorded = FileInfo(name=entry.log, type="file", size=entry.size, mtime=entry.mtime)
    return attempt_sort_key(current) < attempt_sort_key(recorded)


def check_attempt_order(shard: ShardDir, entry: EvalShardEntry) -> None:
    """Refuse a shard whose current attempt sorts before the recorded one."""
    if attempt_regressed(shard, entry):
        current = shard.current
        assert current is not None
        raise ShardSetError(
            f"Shard {shard.dir}: its current attempt {_name(current.name)} is older "
            f"than the attempt last merged ({entry.log}), which was deleted. "
            "Restore the deleted attempt; or delete the shards directory to keep "
            "the merged log as it is; or delete the merged log to rebuild it from "
            "the attempts now present."
        )


def check_headers(headers: list[tuple[str, EvalLog]]) -> None:
    """Refuse attempts that do not belong to one task run.

    Compares the task identifier, scorers, metrics, dataset size, epochs,
    epochs reducer and log format version of every header with the first.
    """
    from inspect_ai._eval.evalset import task_identifier

    for source, header in headers:
        if header.version > LOG_SCHEMA_VERSION:
            raise ShardSetError(
                f"{source} has log format version {header.version}, newer than "
                f"this version of Inspect writes ({LOG_SCHEMA_VERSION}). Upgrade "
                "Inspect to merge it."
            )
    if len(headers) < 2:
        return
    first_source, first = headers[0]
    first_id = task_identifier(first, None)
    for source, header in headers[1:]:
        if task_identifier(header, None) != first_id:
            detail = "task identifier (task, arguments, model, solver or limits)"
            if header.eval.task_file != first.eval.task_file:
                detail += (
                    f"; their task files differ ({first.eval.task_file} and "
                    f"{header.eval.task_file}), so the workers must be launched "
                    "from the same working directory relative to the task file"
                )
            _mismatch(first_source, source, detail)
        for field, a, b in [
            ("scorers", _dump(first.eval.scorers), _dump(header.eval.scorers)),
            ("metrics", _dump(first.eval.metrics), _dump(header.eval.metrics)),
            (
                "dataset size",
                first.eval.dataset.samples,
                header.eval.dataset.samples,
            ),
            ("epochs", first.eval.config.epochs, header.eval.config.epochs),
            (
                "epochs reducer",
                first.eval.config.epochs_reducer,
                header.eval.config.epochs_reducer,
            ),
            ("log format version", first.version, header.version),
        ]:
            if a != b:
                _mismatch(first_source, source, field)


def _mismatch(a: str, b: str, detail: str) -> None:
    raise ShardSetError(f"{a} and {b} differ in their {detail}; they cannot be merged.")


def _dump(value: object) -> object:
    from pydantic_core import to_jsonable_python

    return to_jsonable_python(value)


def check_reads(
    reads: list[AttemptRead],
    ledger: dict[str, EvalShardEntry],
    records: set[SampleRecordKey],
    merged_location: str | None,
) -> None:
    """Refuse attempts whose records cannot be attributed by selection.

    Every read attempt records a selection that covers what it holds; a
    changed shard's selection is the one merged before; the read selections
    are pairwise disjoint; and the merged records with ids in each read
    selection number exactly that shard's ledger count (zero for a new
    shard). See "The sample set" in the sharding design.
    """
    for read in reads:
        selection = read.selection
        if selection is None:
            raise ShardSetError(
                f"{read.file.name} records no sample selection "
                "(eval.dataset.sample_ids), so its samples cannot be attributed to "
                "it. Shards must be logs written by an Inspect version that "
                "records the selection."
            )
        outside = sorted(
            k.sample_id for k in read.summaries if k.sample_id not in selection
        )
        if outside:
            raise ShardSetError(
                f"{read.file.name} holds samples outside its recorded selection "
                f"({_ids_text(outside)}). Shards of tasks that add samples while "
                "they run cannot be merged."
            )
        entry = ledger.get(read.shard)
        if entry is not None and selection_digest(selection) != entry.selection_digest:
            raise ShardSetError(
                f"{read.file.name} selects different samples than {entry.log}, the "
                f"attempt last merged from shard {read.shard}. Move the new attempt "
                f"to its own shard directory, or delete {merged_location} so the "
                "next merge rebuilds it from the current attempts."
            )
    owner: dict[str, str] = {}
    for read in reads:
        for id in read.selection or ():
            other = owner.setdefault(id, read.shard)
            if other != read.shard:
                raise ShardSetError(
                    f"Shards {other} and {read.shard} both select sample {id!r}; "
                    "shard selections must not overlap."
                )
    for read in reads:
        selection = read.selection or frozenset()
        merged = sum(1 for key in records if key.sample_id in selection)
        entry = ledger.get(read.shard)
        expected = entry.samples if entry is not None else 0
        if merged != expected:
            if entry is None:
                raise ShardSetError(
                    f"New shard {read.shard} ({read.file.name}) selects samples "
                    f"already merged into {merged_location} from another shard; "
                    "shard selections must not overlap."
                )
            raise ShardSetError(
                f"{merged_location} holds {merged} records selected by shard "
                f"{read.shard}, but its ledger records {expected}: either the merged "
                "log was changed outside the merge or another shard's selection "
                f"overlaps shard {read.shard}'s. Delete {merged_location} so the "
                "next merge rebuilds it from the shards."
            )


def check_ledger_count(
    records: set[SampleRecordKey], ledger: Iterable[EvalShardEntry], location: str
) -> None:
    """Refuse a merged log whose records do not number its ledger's counts."""
    expected = sum(entry.samples for entry in ledger)
    if len(records) != expected:
        raise ShardSetError(
            f"{location} holds {len(records)} sample records but its ledger "
            f"records {expected}: its samples were changed outside the merge. "
            f"Delete {location} so the next merge rebuilds it from the shards."
        )


def check_vanished(vanished: list[str], merged_location: str, shards_dir: str) -> None:
    if vanished:
        raise ShardSetError(
            f"Shards vanished from {shards_dir} after they were merged into "
            f"{merged_location}: {', '.join(vanished)}. Finish deleting the shards "
            f"(merge again with delete_shards, or delete {shards_dir} by hand), or "
            "restore the files."
        )


def check_selection_covers(
    selection: Selection, held_ids: Collection[str], shards: list[str]
) -> None:
    """Refuse shards that hold ids outside the intended selection."""
    if selection.form == "ids":
        ids = selection.id_set() or frozenset()
        outside = sorted(i for i in held_ids if i not in ids)
        if outside:
            raise ShardSelectionError(
                f"The selection ({selection.describe()}) is narrower than what the "
                f"shards ({', '.join(shards)}) hold: {_ids_text(outside)} are outside "
                "it. Merge with a selection that includes them.",
                outside=outside,
            )
    elif selection.form == "count":
        assert selection.sample_count is not None
        if len(held_ids) > selection.sample_count:
            raise ShardSelectionError(
                f"The selection ({selection.describe()}) is narrower than what the "
                f"shards ({', '.join(shards)}) hold: {len(held_ids)} distinct samples. "
                "Merge with a selection that includes them.",
                outside=None,
            )


def _ids_text(ids: list[str]) -> str:
    shown = ", ".join(repr(i) for i in ids[:_MAX_IDS_SHOWN])
    more = f" and {len(ids) - _MAX_IDS_SHOWN} more" if len(ids) > _MAX_IDS_SHOWN else ""
    return f"{len(ids)} sample ids: {shown}{more}"


class Status(NamedTuple):
    status: Literal["started", "error", "success"]
    error: EvalError | None
    missing: list[str | int] | None
    running: list[str]
    failed: list[str]


def plan_status(
    ledger: list[EvalShardEntry],
    keys: Collection[SampleRecordKey],
    selection: Selection,
    epochs: int,
    dataset_samples: int | None,
) -> Status:
    """The merged status from the ledger and the planned records.

    ``error`` when any current attempt failed; else ``success`` when every
    attempt succeeded and the records are exactly the selection's ids times
    every epoch; else ``started``.
    """
    running = [e.shard for e in ledger if e.status == "started"]
    failed = [e.shard for e in ledger if e.status in ("error", "cancelled")]
    held = {key.sample_id for key in keys}
    if selection.form == "ids":
        expected_ids: set[str] | None = set(selection.id_set() or ())
    elif selection.form == "count":
        expected_ids = held if len(held) == selection.sample_count else None
    else:
        expected_ids = held if len(held) == dataset_samples else None
    complete = expected_ids is not None and set(keys) == {
        SampleRecordKey(id, epoch)
        for id in expected_ids
        for epoch in range(1, epochs + 1)
    }
    missing: list[str | int] | None = None
    if selection.form == "ids":
        missing = [
            id
            for id in dict.fromkeys(selection.ids or [])
            if any(
                SampleRecordKey(str(id), epoch) not in keys
                for epoch in range(1, epochs + 1)
            )
        ]
    if failed:
        first = next(e for e in ledger if e.status in ("error", "cancelled"))
        return Status("error", first.error, missing, running, failed)
    if complete and all(e.status == "success" for e in ledger):
        return Status("success", None, missing, running, failed)
    return Status("started", None, missing, running, failed)


def ledger_stats(ledger: list[EvalShardEntry]) -> EvalStats:
    """Merged statistics: earliest start, latest completion, summed usage."""
    starts = [e.started_at for e in ledger if e.started_at]
    completes = [e.completed_at for e in ledger]
    model_usage: dict[str, ModelUsage] = {}
    role_usage: dict[str, ModelUsage] = {}
    for entry in ledger:
        _add_usage(model_usage, entry.model_usage)
        _add_usage(role_usage, entry.role_usage)
    return EvalStats(
        started_at=min(starts, key=datetime.fromisoformat) if starts else "",
        completed_at=(
            max(completes, key=datetime.fromisoformat)
            if completes and all(completes)
            else ""
        ),
        model_usage=model_usage,
        role_usage=role_usage,
    )


def _add_usage(total: dict[str, ModelUsage], usage: dict[str, ModelUsage]) -> None:
    for key, value in usage.items():
        total[key] = total[key] + value if key in total else value


def selected_total(selection: Selection, held_ids: Collection[str]) -> int:
    """Number of samples the selection names (the held ids without one)."""
    if selection.form == "ids":
        return len(selection.id_set() or ())
    if selection.form == "count":
        assert selection.sample_count is not None
        return selection.sample_count
    return len(held_ids)


def build_header(
    *,
    base: EvalLog,
    merged: EvalLog | None,
    name: str,
    status: Status,
    ledger: list[EvalShardEntry],
    selection: Selection,
    summaries: Sequence[EvalSampleSummary],
    results: EvalResults | None,
) -> EvalLog:
    """The merged log's header.

    `base` is the template shard's header (or the merged header, when that
    was built from the same attempt); every field the sharding design does
    not list is taken from it. `merged` is the existing merged header, from
    which the ids minted at the first merge and the merged-log edits are
    carried.
    """
    if selection.form == "ids":
        sample_ids: list[str | int] = list(selection.ids or [])
    else:
        typed = {str(s.id): s.id for s in summaries}
        sample_ids = [typed[id] for id in sorted(typed)]
    eval_set_ids = {entry.eval_set_id for entry in ledger}
    if merged is not None:
        eval_id = merged.eval.eval_id
        run_id = merged.eval.run_id
        created = merged.eval.created
        task_id = merged.eval.task_id
    else:
        eval_id = uuid()
        run_id = uuid()
        created = iso_now()
        task_id = merged_log_task_id(name, task=base.eval.task, model=base.eval.model)
    eval = base.eval.model_copy(
        update={
            "eval_id": eval_id,
            "run_id": run_id,
            "created": created,
            "task_id": task_id,
            "eval_set_id": eval_set_ids.pop() if len(eval_set_ids) == 1 else None,
            "dataset": base.eval.dataset.model_copy(update={"sample_ids": sample_ids}),
            "config": base.eval.config.model_copy(
                update={"sample_id": None, "limit": None}
            ),
            "shards": EvalShards(
                selection=selection.form,
                sample_count=selection.sample_count
                if selection.form == "count"
                else None,
                ledger=ledger,
            ),
        }
    )
    merged_status: EvalStatus = status.status
    return EvalLog(
        version=base.version,
        status=merged_status,
        eval=eval,
        plan=base.plan,
        results=results,
        stats=ledger_stats(ledger),
        error=status.error,
        invalidated=merged.invalidated if merged is not None else False,
        log_updates=merged.log_updates if merged is not None else None,
    )
