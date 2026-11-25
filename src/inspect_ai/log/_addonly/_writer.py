"""Writes an eval's records to the add-only store.

Tamper-evident logs. A sample writes at each
boundary (before each generate request, before each stage of tool calls,
and at sample end) and waits until the store confirms the write.
"""

import secrets
from contextvars import ContextVar

import anyio
from pydantic import BaseModel

from inspect_ai._util.json import to_json_safe
from inspect_ai.log._log import EvalPlan, EvalResults, EvalSpec, EvalStats, EvalStatus
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.types import BufferRows
from inspect_ai.scorer._metric import SampleScore

from ._records import (
    CLOSING,
    START,
    EvalClosingRecord,
    SampleAttemptRef,
    SampleClosingRecord,
    SampleRecord,
    StartRecord,
)
from ._store import AddOnlyStore, AddOnlyStoreError, StoreLocation


def _body(record: BaseModel) -> bytes:
    return to_json_safe(record, indent=None)


class EvalRecordWriter:
    """One eval's writes. Holds the eval's nonce, which exists only in memory."""

    def __init__(self, store: AddOnlyStore, eval_id: str, nonce: str) -> None:
        self.store = store
        self.eval_id = eval_id
        self.nonce = nonce
        self._attempts: list[SampleAttemptRef] = []

    @classmethod
    async def start(
        cls,
        location: StoreLocation,
        eval: EvalSpec,
        plan: EvalPlan,
        prior_eval_id: str | None = None,
    ) -> "EvalRecordWriter":
        """Write the start record and check the store's settings.

        ``prior_eval_id`` is the eval a retry reuses samples from.
        """
        writer = cls(AddOnlyStore(location), eval.eval_id, secrets.token_hex(32))
        await writer.store.put_start_and_check(
            f"{eval.eval_id}/{START}",
            _body(
                StartRecord(
                    eval_id=eval.eval_id,
                    nonce=writer.nonce,
                    eval=eval,
                    plan=plan,
                    prior_eval_id=prior_eval_id,
                )
            ),
        )
        return writer

    def sample_writer(
        self,
        buffer_db: SampleBufferDatabase,
        sample_id: str | int,
        epoch: int,
        attempt: int,
    ) -> "SampleRecordWriter":
        ref = SampleAttemptRef(sample_id=sample_id, epoch=epoch, attempt=attempt)
        self._attempts.append(ref)
        return SampleRecordWriter(self, buffer_db, ref)

    async def close(
        self, status: EvalStatus, stats: EvalStats, results: EvalResults | None
    ) -> None:
        await self.store.put(
            f"{self.eval_id}/{CLOSING}",
            _body(
                EvalClosingRecord(
                    eval_id=self.eval_id,
                    nonce=self.nonce,
                    status=status,
                    stats=stats,
                    results=results,
                    samples=self._attempts,
                )
            ),
        )


class SampleBufferInsertError(Exception):
    """An event of the sample could not be inserted into the sample buffer.

    The event can never reach the add-only store, so the sample stops at its
    next boundary.
    """


class SampleRecordWriter:
    """One sample attempt's writes, in one sequence.

    Each write takes every buffer row the sample inserted since the previous
    write, whichever agent or sub-agent recorded it, and the next sequence
    number. Nothing awaits between reading the rows and taking the number,
    so numbers follow row order without a lock. The put runs after that, so
    sub-agents' puts overlap, and each boundary then waits until every
    record numbered up to its own is confirmed.
    """

    def __init__(
        self,
        eval_writer: EvalRecordWriter,
        buffer_db: SampleBufferDatabase,
        ref: SampleAttemptRef,
    ) -> None:
        self._eval = eval_writer
        self._buffer_db = buffer_db
        self._ref = ref
        # rows from an earlier attempt (removed on retry) are not this one's
        self._marks = buffer_db.sample_row_marks(ref.sample_id, ref.epoch)
        self._seq = 0
        # puts not yet confirmed, by sequence number
        self._unconfirmed: dict[int, anyio.Event] = {}
        self._failure: Exception | None = None

    def insert_failed(self, ex: Exception) -> None:
        """Record that an event of this sample could not be inserted into the buffer."""
        self._failure = self._failure or SampleBufferInsertError(
            f"An event could not be inserted into the sample buffer, so it "
            f"cannot reach the add-only store: {ex}"
        )

    def _raise_if_failed(self) -> None:
        if self._failure is not None:
            raise self._failure

    async def write(self) -> None:
        """Store the rows recorded since the last write, and wait for the store."""
        self._raise_if_failed()
        rows, marks = self._buffer_db.sample_rows_after(
            self._ref.sample_id, self._ref.epoch, self._marks
        )
        seq = None
        if not rows.empty():
            self._seq, self._marks = self._seq + 1, marks
            seq = self._seq
            self._unconfirmed[seq] = anyio.Event()
        earlier = list(self._unconfirmed.values())
        if seq is not None:
            await self._put(seq, rows)
        for confirmed in earlier:
            await confirmed.wait()
        self._raise_if_failed()

    async def _put(self, seq: int, rows: BufferRows) -> None:
        record = SampleRecord(
            eval_id=self._eval.eval_id,
            nonce=self._eval.nonce,
            sample=self._ref,
            seq=seq,
            rows=rows,
        )
        try:
            # shielded: a cancel already pending would otherwise stop the put
            # before it starts, after its sequence number was taken, and the
            # cancelled sample could not then write its closing record
            with anyio.CancelScope(shield=True):
                await self._eval.store.put(
                    self._ref.key(self._eval.eval_id, str(seq)), _body(record)
                )
        except BaseException as ex:
            self._failure = self._failure or AddOnlyStoreError(
                f"An earlier write to the add-only store failed for this sample: {ex}"
            )
            raise
        finally:
            self._unconfirmed.pop(seq).set()

    async def close(self, scores: dict[str, SampleScore], error: str | None) -> None:
        """Write the last rows and the closing record.

        Writes nothing once a write or a buffer insert has failed: the
        missing closing record shows the attempt was cut short.
        """
        if self._failure is not None:
            return
        await self.write()
        await self._eval.store.put(
            self._ref.key(self._eval.eval_id, CLOSING),
            _body(
                SampleClosingRecord(
                    eval_id=self._eval.eval_id,
                    nonce=self._eval.nonce,
                    sample=self._ref,
                    records=self._seq,
                    scores=scores,
                    error=error,
                )
            ),
        )


_sample_writer: ContextVar[SampleRecordWriter | None] = ContextVar(
    "_addonly_sample_writer", default=None
)


def init_sample_record_writer(writer: SampleRecordWriter | None) -> None:
    _sample_writer.set(writer)


async def store_boundary() -> None:
    """Write the current sample's new events at a boundary (no-op without a store)."""
    writer = _sample_writer.get()
    if writer is not None:
        await writer.write()
