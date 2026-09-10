import abc
from collections.abc import Callable, Sequence
from typing import IO, TYPE_CHECKING, NamedTuple

import anyio

from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem, bind_async_filesystem
from inspect_ai._util.error import EvalError
from inspect_ai.dataset._util import SampleIdEpoch, SampleKeyLookup
from inspect_ai.log._config_update import ConfigUpdate
from inspect_ai.log._edit import LogUpdate
from inspect_ai.log._log import (
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
    EvalSampleSummary,
    EvalSpec,
    EvalStats,
    EvalStatus,
)
from inspect_ai.log._recorders.streaming import materialize_streaming_sample

if TYPE_CHECKING:
    from inspect_ai.log._recorders.buffer.history import SampleHistory


class SampleRecordKey(NamedTuple):
    """The ``(str(sample_id), epoch)`` key a recorder names a sample's record by.

    Always the string form of the dataset id: the ``.eval`` recorder's member
    for a sample is ``samples/{id}_epoch_{epoch}.json``, so an int-id sample
    answers to its string id, and the control channel routes on strings. A
    NamedTuple rather than a bare ``tuple[str, int]`` so this key space stays
    nominally distinct from the dataset-typed ``(id, epoch)`` keys (which a
    bare tuple is silently assignable to).
    """

    sample_id: str
    epoch: int


class SeedSamples:
    """An attempt's prior log, indexed once for seeding.

    Holds the prior's sample keys in source order and a :class:`SampleKeyLookup`
    over them. A ``.eval`` prior keeps only a shared zip reader and reads
    selected bodies in bounded batches; a ``.json`` or in-memory prior keeps
    its bodies (its reader loads the whole file anyway). The recorder owns
    this source and closes it on finish, discard, or task exit.
    """

    def __init__(self) -> None:
        self.keys: list[SampleIdEpoch] = []
        self.lookup = SampleKeyLookup()
        self._by_record: dict[SampleRecordKey, SampleIdEpoch] = {}
        self._samples: dict[SampleIdEpoch, EvalSample] = {}
        self._fs = AsyncFilesystem()
        self._reader: AsyncZipReader | None = None
        self._location: str | None = None

    async def load(self, prior: str | Sequence[EvalSample]) -> None:
        """Read the prior's keys once, retaining JSON bodies and the Eval reader."""
        from inspect_ai.log._file import read_eval_log_async
        from inspect_ai.log._recorders.eval import (
            EvalRecorder,
            _read_all_summaries_async,
        )

        with bind_async_filesystem(self._fs):
            if isinstance(prior, str) and EvalRecorder.handles_location(prior):
                self._location = prior
                self._reader = AsyncZipReader(self._fs, prior)
                summaries, _ = await _read_all_summaries_async(self._reader)
                keys = [(s.id, s.epoch) for s in summaries]
            else:
                samples = (
                    (await read_eval_log_async(prior)).samples or []
                    if isinstance(prior, str)
                    else prior
                )
                for sample in samples:
                    self._samples.setdefault((sample.id, sample.epoch), sample)
                keys = list(self._samples)
        self.keys = keys
        self.lookup = SampleKeyLookup(keys)
        self._by_record = {}
        for key in keys:
            self._by_record.setdefault(SampleRecordKey(str(key[0]), key[1]), key)

    def key_for(self, id: str, epoch: int) -> SampleIdEpoch | None:
        """The prior key a seeded record's string-form ``(id, epoch)`` came from."""
        return self._by_record.get(SampleRecordKey(id, epoch))

    def select(self, keep: set[SampleIdEpoch] | None) -> list[SampleIdEpoch]:
        """The prior keys ``keep`` resolves to, in source order (every key when None).

        Each planned key resolves through :attr:`lookup` (exact first, then
        normalised), so a plan of ``1`` selects a prior stored as ``"001"``.
        The record keeps the prior's id; ``TaskLogger.read_prior_sample``
        adopts it under the planned id when the two differ.
        """
        if keep is None:
            return list(self.keys)
        selected = {
            match
            for id, epoch in keep
            if (match := self.lookup.get(id, epoch)) is not None
        }
        return [key for key in self.keys if key in selected]

    async def read(self, keys: list[SampleIdEpoch]) -> list[EvalSample]:
        """Read a selected batch without retaining Eval bodies between calls."""
        from inspect_ai.log._file import read_eval_log_samples_by_id_async

        if self._reader is not None:
            assert self._location is not None
            with bind_async_filesystem(self._fs):
                return await read_eval_log_samples_by_id_async(
                    self._location, keys, concurrency=8, reader=self._reader
                )
        return [self._samples[key] for key in keys]

    async def close(self) -> None:
        """Release cached bodies, index and filesystem clients, including on cancellation."""
        self._samples.clear()
        self.keys = []
        self.lookup = SampleKeyLookup()
        self._by_record = {}
        self._reader = None
        with anyio.CancelScope(shield=True):
            await self._fs.close()


def sample_read_exclusions(exclude_fields: set[str] | None) -> set[str]:
    """Keep required fields and omit event-dependent data with excluded events.

    Included events need their pool to resolve references. Excluded events
    cannot support timelines, whose UUID references point back into them.
    """
    fields = EvalSample.model_fields
    excluded = {
        field
        for field in exclude_fields or set()
        if field not in fields or not fields[field].is_required()
    }
    if "events" in excluded:
        excluded.update({"events_data", "timelines"})
    else:
        excluded.discard("events_data")
    return excluded


def exclude_sample_fields(
    sample: EvalSample, exclude_fields: set[str] | None
) -> EvalSample:
    """Omit optional fields from a resident sample without changing the stored copy."""
    excluded = sample_read_exclusions(exclude_fields)
    if not excluded:
        return sample
    fields = EvalSample.model_fields
    return sample.model_copy(
        update={
            field: fields[field].get_default(call_default_factory=True)
            for field in excluded
            if field in fields
        }
    )


class Recorder(abc.ABC):
    def __init__(self) -> None:
        self._seed_sources: dict[str, SeedSamples] = {}

    async def seed_source(
        self, eval: EvalSpec, prior: str | Sequence[EvalSample]
    ) -> SeedSamples:
        """Return this attempt's prior source, loading it once before dispatch."""
        source = self._seed_sources.get(eval.eval_id)
        if source is None:
            source = SeedSamples()
            try:
                await source.load(prior)
            except BaseException:
                await source.close()
                raise
            self._seed_sources[eval.eval_id] = source
        return source

    async def close_seed_source(self, eval: EvalSpec) -> None:
        """Release this attempt's cached prior on finish, discard, or task exit."""
        source = self._seed_sources.pop(eval.eval_id, None)
        if source is not None:
            await source.close()

    @classmethod
    @abc.abstractmethod
    def handles_location(cls, location: str) -> bool: ...

    @classmethod
    @abc.abstractmethod
    def handles_bytes(cls, first_bytes: bytes) -> bool: ...

    @abc.abstractmethod
    def default_log_buffer(self, sample_count: int, high_throughput: bool) -> int: ...

    @abc.abstractmethod
    def is_writeable(self) -> bool: ...

    @abc.abstractmethod
    async def log_init(self, eval: EvalSpec, location: str | None = None) -> str: ...

    async def log_seed(
        self,
        eval: EvalSpec,
        prior: "str | Sequence[EvalSample]",
        keep: set[tuple[str | int, int]] | None,
    ) -> None:
        """Seed an initialized (not yet started) log with a prior attempt's samples.

        A retry attempt's log starts out holding every sample record the
        prior attempt's log holds (restricted to the planned ``keep`` keys
        when given), so the attempt's log is a superset of the prior log from
        its first flush no matter how the attempt ends (see
        ``design/retry-seeded-attempt-log.md``). ``prior`` is the prior log's
        location or, for an in-memory prior log, its samples.

        The base implementation re-logs each kept sample through
        :meth:`log_sample` with ``write_through`` set; a recorder with a
        cheaper same-format path (``EvalRecorder`` copies a prior ``.eval``
        as bytes) overrides and falls back to this for anything else. Images
        are kept as the prior recorded them, matching the byte copy. Raises
        ``FileNotFoundError`` when a prior log location does not exist.
        Checkpoints between samples keep synchronous recorder implementations
        responsive to cancellation and other tasks on the event loop.
        Eval sources are selected by summary before bodies are read in bounded
        batches. JSON sources retain the reader's exact-first normalized IDs.
        """
        await self.log_seed_samples(eval, prior, keep)

    async def log_seed_samples(
        self,
        eval: EvalSpec,
        prior: "str | Sequence[EvalSample]",
        keep: set[tuple[str | int, int]] | None,
        *,
        on_sample: Callable[[str | int, int], None] | None = None,
    ) -> None:
        """Append selected prior records.

        Unlike the whole-file seed, this can extend a started log when a
        dynamic feed admits more samples under its limit. Only selected
        records absent from the recorder are written (a result this attempt
        already recorded is never replaced), under the prior's own ids. The
        prior's index and reader are shared across admissions until this
        attempt finishes or is discarded. ``on_sample`` runs before each
        record is written, so the caller can withhold pending records from
        live readers throughout the copy.
        """
        from inspect_ai.log._condense import condense_sample

        source = await self.seed_source(eval, prior)
        existing = {
            SampleRecordKey(str(sample.id), sample.epoch)
            for sample in await self.sample_summaries(eval) or []
        }
        keys = [
            key
            for key in source.select(keep)
            if SampleRecordKey(str(key[0]), key[1]) not in existing
        ]
        # Bound retained bodies as well as concurrent reads: the bulk
        # reader returns its entire request as a list.
        for offset in range(0, len(keys), 8):
            batch = await source.read(keys[offset : offset + 8])
            for sample in batch:
                if on_sample is not None:
                    on_sample(sample.id, sample.epoch)
                await self.log_sample(eval, condense_sample(sample), write_through=True)
                await anyio.lowlevel.checkpoint()
            del batch

    @abc.abstractmethod
    async def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None: ...

    def destination_written(self, eval: EvalSpec) -> bool:
        """Whether anything has reached the eval's in-progress destination log.

        Asked only for a log that is still in progress (after ``log_init``,
        before ``log_finish``); a finished log is known to be written
        without consulting the recorder. ``False`` when nothing has been
        flushed yet (an attempt that failed before its first flush). A
        recorder that tracks this should override and raise for an eval it
        is not tracking; this default is legacy behaviour for recorders
        that cannot tell, and always reports ``True``.
        """
        return True

    @abc.abstractmethod
    async def log_sample(
        self, eval: EvalSpec, sample: EvalSample, *, write_through: bool = False
    ) -> None:
        """Record a completed sample.

        Args:
            eval: Spec of the eval the sample belongs to.
            sample: The completed sample.
            write_through: Persist the sample to the recorder's cheap local
                buffer tier immediately (retaining at most a condensed,
                event-less copy in memory) rather than holding the full
                sample resident until the next flush. A memory hint for
                bulk re-logging (retry-reused samples): destination
                durability still requires a later ``flush``. Recorders
                without a distinct local tier (e.g. the in-memory ``.json``
                format) may ignore it.
        """
        ...

    async def log_sample_streaming(
        self, eval: EvalSpec, sample: EvalSample, history: "SampleHistory"
    ) -> None:
        await self.log_sample(eval, materialize_streaming_sample(sample, history))

    async def sample_summaries(self, eval: EvalSpec) -> list[EvalSampleSummary] | None:
        """Live per-sample summaries for an in-progress eval, if available.

        Returns the recorder's in-memory record of every sample logged so
        far (i.e. completed samples) — gap-free and ahead of what's been
        flushed to disk. Used by the control channel to list an eval's
        samples while it runs. Returns ``None`` when the recorder can't
        serve them in-memory (eg. the eval has finished and been torn
        down, or this recorder type doesn't retain summaries); callers
        then fall back to reading the on-disk log.
        """
        return None

    async def buffered_sample(
        self,
        eval: EvalSpec,
        id: str | int,
        epoch: int,
        *,
        exclude_fields: set[str] | None = None,
    ) -> EvalSample | None:
        """The full ``EvalSample`` for one sample, if held in-memory.

        Counterpart to :meth:`sample_summaries` for whole samples: returns the
        recorder's not-yet-flushed in-memory ``EvalSample`` (carrying the full
        ``error_retries`` / ``events`` / ``scores`` a summary omits) — gap-free
        and ahead of disk, so a just-completed sample is readable before it's
        flushed. Returns ``None`` when the recorder can't serve it in-memory
        (already flushed, eval torn down, or this recorder type doesn't buffer
        whole samples); callers then read the on-disk log. IDs match by their
        string form, as on-disk records do. ``exclude_fields`` omits optional
        fields; file-backed buffers should skip them during parsing so a
        lightweight read need not materialize the full transcript.
        """
        return None

    async def log_config_update(self, eval: EvalSpec, update: ConfigUpdate) -> None:
        """Record a mid-run config change (see ``EvalLog.config_updates``).

        Called while the eval runs, when a `inspect ctl config` retune is
        applied. The base implementation is a no-op so recorder subclasses
        that don't persist mid-run state keep working; the built-in
        recorders override it to journal the update (`.eval`) or accumulate
        it in the in-memory log (JSON) so it lands in the finished header.
        """

    @abc.abstractmethod
    async def flush(self, eval: EvalSpec) -> None: ...

    async def log_prune(self, eval: EvalSpec, keys: set[SampleRecordKey]) -> None:
        """Drop seeded sample records, including their journal summaries.

        Called just before a natural success's ``log_finish`` with the keys
        of prior records ``log_seed`` carried in that no sample
        of this attempt consulted: a dynamic feed (seeded with selected prior
        records, having no upfront plan) whose realized set no longer
        includes them. Dropping them keeps the finished log's samples to
        this attempt's plan. Also called mid-run when a normalized JSON ID
        re-runs under a different key and every planned ID sharing the
        prior record has completed: it must leave both the bodies and
        summaries in every subsequent flush. The base
        implementation is a no-op, as for :meth:`log_discard`; the built-in
        recorders override it.
        """

    async def log_discard(
        self, eval: EvalSpec, *, keep_destination: bool = False
    ) -> None:
        """Discard a never-finished log (``log_finish`` will never run for it).

        Drops the recorder's in-memory tracking for the eval and, unless
        ``keep_destination`` is set, removes a destination file the log has
        already written itself — never a pre-existing file it was seeded
        from. ``keep_destination`` leaves a written destination in place
        (an attempt whose final write failed: the file holds every sample
        flushed so far and the next attempt reads it), releasing only the
        in-memory resources. The base implementation is a no-op so recorder
        subclasses that track nothing between init and finish keep working;
        the built-in recorders override it.
        """

    @abc.abstractmethod
    async def log_finish(
        self,
        eval: EvalSpec,
        status: EvalStatus,
        stats: EvalStats,
        results: EvalResults | None,
        reductions: list[EvalSampleReductions] | None,
        error: EvalError | None = None,
        header_only: bool = False,
        invalidated: bool = False,
        log_updates: list[LogUpdate] | None = None,
        config_updates: list[ConfigUpdate] | None = None,
    ) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    async def read_log(
        cls,
        location: str,
        header_only: bool = False,
        exclude_fields: set[str] | None = None,
    ) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    async def read_log_bytes(
        cls, log_bytes: IO[bytes], header_only: bool = False
    ) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    async def read_log_sample(
        cls,
        location: str,
        id: str | int | None = None,
        epoch: int = 1,
        uuid: str | None = None,
        exclude_fields: set[str] | None = None,
        reader: AsyncZipReader | None = None,
    ) -> EvalSample: ...

    @classmethod
    @abc.abstractmethod
    async def read_log_sample_summaries(
        cls, location: str
    ) -> list[EvalSampleSummary]: ...

    @classmethod
    async def read_log_sample_ids(cls, location: str) -> list[tuple[str | int, int]]:
        return sorted(
            (
                (sample_summary.id, sample_summary.epoch)
                for sample_summary in await cls.read_log_sample_summaries(location)
            ),
            key=lambda x: (
                x[1],
                (x[0] if isinstance(x[0], str) else str(x[0]).zfill(20)),
            ),
        )

    @classmethod
    @abc.abstractmethod
    async def write_log(
        cls,
        location: str,
        log: EvalLog,
        if_match_etag: str | None = None,
        header_only: bool = False,
    ) -> str | None: ...
