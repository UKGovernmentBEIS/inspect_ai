"""Records in the add-only store and their keys.

PROTOTYPE (tamper-evident eval logs, step 1). Keys, under the store prefix:

    <eval-id>/start
    <eval-id>/closing
    <eval-id>/<sample-id>.<epoch>/<attempt>/<sequence-number>
    <eval-id>/<sample-id>.<epoch>/<attempt>/closing
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from inspect_ai.log._log import EvalPlan, EvalResults, EvalSpec, EvalStats, EvalStatus
from inspect_ai.log._recorders.buffer.types import BufferRows
from inspect_ai.scorer._metric import SampleScore

from ._store import sample_key_part

START = "start"
CLOSING = "closing"


class SampleAttemptRef(BaseModel):
    sample_id: str | int
    epoch: int
    attempt: int

    def key(self, eval_id: str, last: str) -> str:
        return (
            f"{eval_id}/{sample_key_part(self.sample_id, self.epoch)}/"
            f"{self.attempt}/{last}"
        )


class ReusedSampleRef(BaseModel):
    """A sample an eval retry reused from an earlier eval, with no records of its own."""

    sample_id: str | int
    epoch: int
    eval_id: str
    """The eval the retry read the sample from (itself a retry, possibly)."""


class StartRecord(BaseModel):
    type: Literal["start"] = "start"
    eval_id: str
    nonce: str
    eval: EvalSpec
    plan: EvalPlan


class SampleRecord(BaseModel):
    """The sample buffer's rows inserted since the attempt's previous record."""

    type: Literal["sample"] = "sample"
    eval_id: str
    nonce: str
    sample: SampleAttemptRef
    seq: int
    rows: BufferRows


class SampleClosingRecord(BaseModel):
    type: Literal["sample_closing"] = "sample_closing"
    eval_id: str
    nonce: str
    sample: SampleAttemptRef
    records: int
    """Number of sample records the attempt wrote."""
    scores: dict[str, SampleScore]
    error: str | None = None


class EvalClosingRecord(BaseModel):
    type: Literal["eval_closing"] = "eval_closing"
    eval_id: str
    nonce: str
    status: EvalStatus
    stats: EvalStats
    results: EvalResults | None = None
    samples: list[SampleAttemptRef]
    """Every sample attempt the eval started."""
    reused: list[ReusedSampleRef] = []
    """Every sample the eval reused from an earlier eval (eval_retry)."""


StoreRecord = Annotated[
    StartRecord | SampleRecord | SampleClosingRecord | EvalClosingRecord,
    Field(discriminator="type"),
]
