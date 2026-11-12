"""Building the merged log's zip, computing results with the caller's task."""

import functools
import json
import zipfile
import zlib
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from typing import IO, TYPE_CHECKING, Any, BinaryIO, NamedTuple

import anyio
from pydantic import BaseModel

from inspect_ai._util.async_zip import AsyncZipReader, _check_crc
from inspect_ai._util.compression import PieceDecompressor
from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.error import EvalError
from inspect_ai._util.json import (
    ExcludingObjectBuilder,
    JSONPushParser,
    is_ijson_float_overflow_error,
    is_ijson_int_overflow_error,
    is_ijson_nan_inf_error,
    to_json_safe,
)
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai._util.zip_common import ZipEntry
from inspect_ai._util.zipfile import zipfile_compress_kwargs
from inspect_ai.log._edit import ProvenanceData
from inspect_ai.log._log import (
    EvalLog,
    EvalMetricDefinition,
    EvalResults,
    EvalSampleReductions,
    EvalSampleSummary,
)
from inspect_ai.log._recorders.eval import (
    HEADER_JSON,
    REDUCTIONS_JSON,
    SUMMARIES_JSON,
    _sample_filename,
)
from inspect_ai.log._recorders.recorder import SampleRecordKey
from inspect_ai.scorer._metric import SampleScore, Score

from ._errors import ShardSetError
from ._owned import run_owned

if TYPE_CHECKING:
    from inspect_ai._eval.task.task import Task


class _SampleInputs(NamedTuple):
    """What computing the results keeps of a sample."""

    id: int | str
    scores: dict[str, Score]
    initial_metadata: dict[str, Any] | None
    """The dataset metadata its `SampleInitEvent` records, before any solver
    changed it; None without that event."""
    initialized: bool
    """Whether the sample has a `SampleInitEvent`."""
    scoring_ran: bool
    """Whether a declared scorer ran on the sample (it has a `scorer` span),
    which a run with `score=False` never does."""
    error: bool
    invalidated: bool


class MergedScoring(NamedTuple):
    """What the merged header takes from the merged samples."""

    results: EvalResults | None
    invalidated: bool
    """Whether any merged sample is invalidated."""


def check_task_matches(task: "Task", header: EvalLog, source: str) -> None:
    """Refuse a task that is not the one the shards ran.

    Compares names only, not options: the task name, the scorer names, the
    metric names (each scorer's and the task's), the number of epochs and the
    epoch reducer names, where no reducer (the default mean) differs from an
    empty list (no reduction). Passing the task the shards ran, with the same
    options, is the caller's responsibility.

    Raises:
        ShardSetError: The task differs from what `header` records.
    """
    from inspect_ai._eval.task.log import resolve_eval_metrics, resolve_eval_scorers
    from inspect_ai.scorer._metric import to_metric_specs
    from inspect_ai.scorer._reducer import reducer_log_names
    from inspect_ai.scorer._scorer import as_scorer_spec

    recorded = header.eval
    scorers = resolve_eval_scorers(
        [as_scorer_spec(scorer) for scorer in task.scorer]
        if task.scorer is not None
        else None
    )
    metrics = resolve_eval_metrics(
        to_metric_specs(task.metrics) if task.metrics is not None else None
    )
    for field, given, ran in [
        ("task name", task.name, recorded.task),
        (
            "scorers",
            [s.name for s in scorers or []],
            [s.name for s in recorded.scorers or []],
        ),
        (
            "scorer metrics",
            [_metric_names(s.metrics) for s in scorers or []],
            [_metric_names(s.metrics) for s in recorded.scorers or []],
        ),
        ("task metrics", _metric_names(metrics), _metric_names(recorded.metrics)),
        ("epochs", task.epochs or 1, recorded.config.epochs or 1),
        (
            "epoch reducers",
            reducer_log_names(task.epochs_reducer),
            recorded.config.epochs_reducer,
        ),
    ]:
        if given != ran:
            raise ShardSetError(
                f"The task passed to the merge differs from the one {source} "
                f"ran in its {field} ({given!r}, not {ran!r}). Pass the task the "
                "shards ran."
            )


def _metric_names(metrics: Any) -> Any:
    """The metric names of a recorded metrics structure, without options."""

    def group(group: dict[str, list[EvalMetricDefinition]]) -> dict[str, list[str]]:
        return {key: [m.name for m in values] for key, values in group.items()}

    if metrics is None:
        return None
    if isinstance(metrics, dict):
        return group(metrics)
    return [group(item) if isinstance(item, dict) else item.name for item in metrics]


async def write_merged_zip(
    out: BinaryIO,
    *,
    keys: Sequence[SampleRecordKey],
    read_member: Callable[[SampleRecordKey], Awaitable["SampleMember"]],
    summaries: Sequence[EvalSampleSummary],
    task: "Task",
    total_samples: int,
    make_header: Callable[[MergedScoring], EvalLog],
) -> EvalLog:
    """Write the merged log's members to `out` and return its header.

    Each sample member that `read_member` locates is decompressed as it
    streams, written under the name rebuilt from its key and parsed as it
    passes, keeping only what computing the results needs. Then the
    summaries, the reductions and the header (made by `make_header` from the
    results and the samples' invalidation) are written. No journal is
    written: the merged log is always written finished. The results are computed in the caller's model
    context: the merge builds no model from what the shards record.

    Raises:
        ShardSetError: A sample member's id or epoch does not match its name,
            it has a deprecated field (`score`, `transcript`) or a key holding
            "." where the merge reads events (Inspect writes none), a sample
            with a declared score has no `SampleInitEvent`, or some samples
            were scored and others ran without scoring.
        pydantic.ValidationError: A sample member does not parse.
        ZipCrcError: A sample member's bytes do not match its CRC-32.
        zlib.error: A sample member's deflate stream is incomplete.
    """
    with zipfile.ZipFile(out, "w", **zipfile_compress_kwargs) as zf:
        inputs: list[_SampleInputs] = []
        for key in keys:
            inputs.append(await _copy_sample(zf, key, read_member))
        results, reductions = _results(task, inputs, total_samples)
        header = make_header(
            MergedScoring(
                results=results,
                invalidated=any(sample.invalidated for sample in inputs),
            )
        )
        await run_owned(
            functools.partial(_write_members, zf, list(summaries), reductions, header)
        )
    return header


class SampleMember(NamedTuple):
    """A sample member to copy into the merged log."""

    reader: AsyncZipReader
    """A reader of the log holding it, which verifies CRCs."""
    entry: ZipEntry
    location: str
    """The log holding it, as errors name it."""


_KEPT_FIELDS = frozenset({"id", "epoch", "scores", "error", "invalidation"})
"""The sample fields the merge keeps; it reads the rest only from `events`.
Other fields, including any a later version of Inspect adds, are skipped."""
_DEPRECATED_FIELDS = frozenset({"score", "transcript"})
"""Fields that `EvalSample` migrates to `scores` and `events`, written only
by versions of Inspect from before shards."""

# ijson prefixes of an event, its kind and type, and its sample's metadata
_EVENT = "events.item"
_EVENT_FIELDS = {"events.item.event": "event", "events.item.type": "type"}
_INIT_METADATA = "events.item.sample.metadata"
_INIT_METADATA_CHILD = f"{_INIT_METADATA}."
_READ_OBJECTS = frozenset({"", _EVENT, "events.item.sample"})
"""Prefixes of the objects whose keys the parse reads by prefix: the sample,
each event and each event's sample. ijson joins keys with ".", so a key
holding "." in one of them could pose as an event field. Inspect writes none
there, and the merge refuses them."""


class _ScoringFields(BaseModel):
    """What the merge validates of a sample member."""

    id: int | str
    epoch: int
    scores: dict[str, Score] | None = None
    error: EvalError | None = None
    invalidation: ProvenanceData | None = None
    initial_metadata: dict[str, Any] | None = None


class _ParsedSample(NamedTuple):
    fields: dict[str, Any]
    """The kept top-level fields."""
    deprecated: list[str]
    """The deprecated top-level fields present."""
    dotted: list[str]
    """Keys holding "." in the objects of `_READ_OBJECTS`."""
    initialized: bool
    initial_metadata: Any
    scoring_ran: bool


class _SampleParse:
    """An include-only parse of a sample member, fed its bytes in chunks.

    Builds only the kept top-level fields, with the builder behind
    `read_eval_log(exclude_fields=...)`. Of the events, which it never
    builds, it keeps the first `sample_init` event's `sample.metadata` and
    whether a `scorer` span began. Peak memory follows the largest single
    JSON value it tokenises (a long string), not the size of the member.
    """

    def __init__(self) -> None:
        self._parser = JSONPushParser()
        self._fields = ExcludingObjectBuilder(set(), include_fields=_KEPT_FIELDS)
        self._deprecated: list[str] = []
        self._dotted: list[str] = []
        self._event: dict[str, Any] = {}
        self._metadata: ExcludingObjectBuilder | None = None
        self._initialized = False
        self._initial_metadata: Any = None
        self._scoring_ran = False

    def feed(self, chunk: bytes) -> None:
        self._take(self._parser.feed(chunk))

    def finish(self) -> _ParsedSample:
        self._take(self._parser.close())
        return _ParsedSample(
            fields=self._fields.data,
            deprecated=self._deprecated,
            dotted=self._dotted,
            initialized=self._initialized,
            initial_metadata=self._initial_metadata,
            scoring_ran=self._scoring_ran,
        )

    def _take(self, events: list[tuple[str, str, Any]]) -> None:
        for prefix, event, value in events:
            self._fields.event(event, value)
            if event == "map_key" and prefix in _READ_OBJECTS:
                if "." in value:
                    self._dotted.append(value)
                elif prefix == "" and value in _DEPRECATED_FIELDS:
                    self._deprecated.append(value)
            if prefix.startswith(_EVENT):
                self._sample_event(prefix, event, value)

    def _sample_event(self, prefix: str, event: str, value: Any) -> None:
        if prefix == _EVENT:
            if event == "start_map":
                self._event = {}
                self._metadata = None
            elif event == "end_map":
                self._end_event()
        elif prefix in _EVENT_FIELDS:
            self._event[_EVENT_FIELDS[prefix]] = value
        elif prefix == _INIT_METADATA or prefix.startswith(_INIT_METADATA_CHILD):
            if self._metadata is None:
                # a builder that excludes nothing builds the value under its key
                self._metadata = ExcludingObjectBuilder(set())
                self._metadata.event("start_map", None)
                self._metadata.event("map_key", "metadata")
            self._metadata.event(event, value)

    def _end_event(self) -> None:
        kind = self._event.get("event")
        if kind == "sample_init" and not self._initialized:
            self._initialized = True
            if self._metadata is not None:
                self._initial_metadata = self._metadata.data.get("metadata")
        elif kind == "span_begin" and self._event.get("type") == "scorer":
            self._scoring_ran = True
        self._metadata = None


def _parse_whole(data: bytes) -> _ParsedSample:
    """What `_SampleParse` keeps, from a member parsed whole with `json`.

    For members holding numbers the streaming parser refuses (NaN, Infinity,
    or a number too large for it), as `read_eval_log(exclude_fields=...)`
    falls back.
    """
    sample = json.loads(data)
    if not isinstance(sample, dict):
        return _ParsedSample(
            fields={},
            deprecated=[],
            dotted=[],
            initialized=False,
            initial_metadata=None,
            scoring_ran=False,
        )
    events = [e for e in sample.get("events") or [] if isinstance(e, dict)]
    init = next((e for e in events if e.get("event") == "sample_init"), None)
    init_sample = init.get("sample") if init is not None else None
    read_objects = [sample, *events]
    read_objects.extend(
        e["sample"] for e in events if isinstance(e.get("sample"), dict)
    )
    return _ParsedSample(
        fields={k: v for k, v in sample.items() if k in _KEPT_FIELDS},
        deprecated=[k for k in sample if k in _DEPRECATED_FIELDS],
        dotted=[k for obj in read_objects for k in obj if "." in k],
        initialized=init is not None,
        initial_metadata=(
            init_sample.get("metadata") if isinstance(init_sample, dict) else None
        ),
        scoring_ran=any(
            e.get("event") == "span_begin" and e.get("type") == "scorer" for e in events
        ),
    )


def _takes_whole_parse(ex: Exception) -> bool:
    """Whether a streaming parse error is a number only `json` reads."""
    return (
        is_ijson_nan_inf_error(ex)
        or is_ijson_int_overflow_error(ex)
        or is_ijson_float_overflow_error(ex)
    )


_PIECE_SIZE = 64 * 1024
"""Bytes of a decompressed member parsed at once. The parser returns every
event of a piece together, which takes several times the piece's size when
its JSON holds many small values."""


class _MemberPieces:
    """Takes a sample member's decompressed pieces as they arrive.

    Each piece is added to the CRC-32, written to the merged member and
    parsed. It holds nothing that feeds it, so the decompressor writing to
    it forms no reference cycle. Blocking: each call runs in a worker thread.
    """

    def __init__(self, zf: zipfile.ZipFile, name: str) -> None:
        self._zf = zf
        self._name = name
        self.writer: IO[bytes] | None = None
        self.parse: _SampleParse | None = _SampleParse()
        self.crc = 0

    def take(self, piece: bytes) -> None:
        self.crc = zlib.crc32(piece, self.crc)
        self.open().write(piece)
        if self.parse is not None:
            try:
                self.parse.feed(piece)
            except Exception as ex:
                if not _takes_whole_parse(ex):
                    raise
                self.parse = None

    def open(self) -> IO[bytes]:
        if self.writer is None:
            self.writer = self._zf.open(self._name, "w", force_zip64=True)
        return self.writer


class _SampleCopy:
    """Writes a sample member to the merged zip, parsing it as it passes.

    Fed the member's compressed bytes, it decompresses them in bounded
    pieces, each written, parsed and added to the CRC-32 before the next.
    Blocking: each call runs in a worker thread.
    """

    def __init__(self, zf: zipfile.ZipFile, name: str, member: SampleMember) -> None:
        self._member = member
        self._pieces = _MemberPieces(zf, name)
        self._decompressor = PieceDecompressor(
            member.entry.compression_method, self._pieces.take, _PIECE_SIZE
        )

    def write(self, data: bytes) -> None:
        """Take the next chunk of the member's compressed bytes."""
        self._decompressor.write(data)

    def finish(self) -> _ParsedSample | None:
        """Finish the member; None when it must be parsed whole."""
        self._decompressor.finish()
        _check_crc(self._member.location, self._member.entry, self._pieces.crc)
        self._pieces.open().close()
        parse = self._pieces.parse
        if parse is None:
            return None
        try:
            return parse.finish()
        except Exception as ex:
            if not _takes_whole_parse(ex):
                raise
            return None

    @property
    def closed(self) -> bool:
        """Whether the member is closed, or was never opened."""
        return self._pieces.writer is None or self._pieces.writer.closed

    def close(self) -> None:
        """Close the member if `finish` did not, so the zip can close."""
        if self._pieces.writer is not None:
            self._pieces.writer.close()


async def _copy_sample(
    zf: zipfile.ZipFile,
    key: SampleRecordKey,
    read_member: Callable[[SampleRecordKey], Awaitable[SampleMember]],
) -> _SampleInputs:
    """Copy one sample member into `zf` and return what the results need of it.

    The member is streamed, so only one chunk of its compressed bytes and one
    bounded piece of its decompressed bytes are in memory at a time, unless it
    holds a number the streaming parser refuses; it is then read again and
    parsed whole.
    """
    member = await read_member(key)
    copy = _SampleCopy(zf, _sample_filename(key.sample_id, key.epoch), member)
    chunks: AsyncGenerator[bytes, None] | None = None
    try:
        raw = await member.reader.open_member_raw(member.entry)
        chunks = raw.__aiter__()
        async for chunk in chunks:
            await run_owned(functools.partial(copy.write, chunk))
        parsed = await run_owned(copy.finish)
    finally:
        with anyio.CancelScope(shield=True):
            try:
                if chunks is not None:
                    # closes the member's input, which a loop left early does not
                    await chunks.aclose()
            finally:
                if not copy.closed:
                    # the close can flush much compressed output, so it runs in
                    # a worker; closing again here is a no-op unless the
                    # worker never ran (a native cancellation)
                    try:
                        await run_owned(copy.close)
                    finally:
                        copy.close()
    if parsed is None:
        data = await member.reader.read_member_fully(member.entry)
        parsed = await run_owned(functools.partial(_parse_whole, data))
    return _sample_inputs(key, parsed)


def _sample_inputs(key: SampleRecordKey, parsed: _ParsedSample) -> _SampleInputs:
    name = _sample_filename(key.sample_id, key.epoch)
    if parsed.deprecated:
        raise ShardSetError(
            f"Sample member {name} has the deprecated fields {parsed.deprecated}, "
            "which only logs from before shards hold. Re-run the shard holding it."
        )
    if parsed.dotted:
        raise ShardSetError(
            f"Sample member {name} has the keys {parsed.dotted}, which Inspect "
            "does not write in a sample, its events or their samples."
        )
    sample = _ScoringFields.model_validate(
        {**parsed.fields, "initial_metadata": parsed.initial_metadata},
        context=get_deserializing_context(),
    )
    if str(sample.id) != key.sample_id or sample.epoch != key.epoch:
        raise ShardSetError(
            f"Sample member {name} holds sample {sample.id!r}, epoch {sample.epoch}."
        )
    return _SampleInputs(
        id=sample.id,
        scores=dict(sample.scores or {}),
        initial_metadata=sample.initial_metadata,
        initialized=parsed.initialized,
        scoring_ran=parsed.scoring_ran,
        error=sample.error is not None,
        invalidated=sample.invalidation is not None,
    )


def _write_members(
    zf: zipfile.ZipFile,
    summaries: list[EvalSampleSummary],
    reductions: list[EvalSampleReductions] | None,
    header: EvalLog,
) -> None:
    zf.writestr(SUMMARIES_JSON, to_json_safe(summaries, indent=None))
    if reductions is not None:
        zf.writestr(REDUCTIONS_JSON, to_json_safe(reductions, indent=None))
    zf.writestr(HEADER_JSON, to_json_safe(header, indent=None))


def _results(
    task: "Task", inputs: list[_SampleInputs], total_samples: int
) -> tuple[EvalResults | None, list[EvalSampleReductions] | None]:
    """The merged samples' results and epoch reductions, computed with `task`.

    Through `eval_results`, with the task's scorers, metrics and epoch
    reducer, as a native run computes them. Each score is passed to the
    metrics as a fresh run passes it: with the sample's dataset metadata
    (from its `SampleInitEvent`) and the declared scorer's name.

    A score with no declared scorer (set by a solver) is refused: a fresh run
    and a retry give its metrics different inputs (decision: Ransom,
    2026-10-28).

    Shards run with `score=False` hold samples that completed without
    scoring. Their results have no scorer entries and no reductions, as a
    native unscored run's do. Samples that were scored beside samples that
    ran without scoring are refused, since the shards did not run alike.

    Raises:
        ShardSetError: A sample has a score with no declared scorer, or has
            scores but no `SampleInitEvent`, or some samples were scored and
            others ran without scoring.
    """
    from inspect_ai._eval.task.results import eval_results
    from inspect_ai.scorer._scorer import unique_scorer_name

    scorer_names: list[str] = []
    for scorer in task.scorer or []:
        scorer_names.append(unique_scorer_name(scorer, scorer_names))
    declared = {
        name: registry_unqualified_name(scorer)
        for name, scorer in zip(scorer_names, task.scorer or [])
    }
    unscored = next(
        (
            sample
            for sample in inputs
            if not (sample.scores or sample.scoring_ran or sample.error)
        ),
        None,
    )
    scored = next(
        (sample for sample in inputs if sample.scores or sample.scoring_ran), None
    )
    if unscored is not None and scored is not None:
        raise ShardSetError(
            f"Sample {str(scored.id)!r} was scored but sample "
            f"{str(unscored.id)!r} ran without scoring (score=False or "
            "--no-score), so the shards did not run with the same scoring. Re-run "
            "the shards so that all of them score, or none do."
        )
    scores: list[dict[str, SampleScore]] = []
    for sample in inputs:
        if not sample.scores:
            continue
        other = next((name for name in sample.scores if name not in declared), None)
        if other is not None:
            raise ShardSetError(
                f"Sample {str(sample.id)!r} has the score '{other}', which no "
                "scorer the task declares produced (a solver set it). The merge "
                "cannot merge solver-set scores: a fresh run and a retry give "
                "their metrics different inputs. Score with a scorer declared on "
                "the task (Task(scorer=...)) and re-run the shards."
            )
        if not sample.initialized:
            raise ShardSetError(
                f"Sample {str(sample.id)!r} has no sample_init event, which records "
                "the dataset metadata a fresh run gives its scorers' metrics (a "
                "sample whose record could not be serialized is logged without "
                "its events). Re-run the shard holding the sample."
            )
        scores.append(
            {
                name: SampleScore(
                    score=score,
                    sample_id=sample.id,
                    sample_metadata=sample.initial_metadata,
                    scorer=declared[name],
                )
                for name, score in sample.scores.items()
            }
        )
    return eval_results(
        samples=total_samples,
        scores=scores,
        reducers=task.epochs_reducer,
        scorers=task.scorer if unscored is None else None,
        metrics=task.metrics,
        scorer_names=(scorer_names or None) if unscored is None else None,
        completed_samples=sum(1 for sample in inputs if not sample.error),
        headline_metric=task.headline_metric,
    )
