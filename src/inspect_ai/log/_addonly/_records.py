"""Records in the add-only store and their keys.

Tamper-evident logs. Keys, under the store prefix:

    <eval-id>/start
    <eval-id>/closing
    <eval-id>/<sample-id>.<epoch>/<attempt>/<sequence-number>
    <eval-id>/<sample-id>.<epoch>/<attempt>/closing
    rescores/<eval-id>/<rescore-id>/start
    rescores/<eval-id>/<rescore-id>/<sample-id>.<epoch>
    rescores/<eval-id>/<rescore-id>/closing
"""

from typing import Annotated, Literal, Sequence

from pydantic import BaseModel, Field, ValidationError

from inspect_ai.event import Event, InfoEvent
from inspect_ai.log._log import EvalResults, EvalStats, EvalStatus
from inspect_ai.log._recorders.buffer.types import BufferRows
from inspect_ai.scorer._metric import SampleScore

from ._store import sample_key_part

START = "start"
CLOSING = "closing"
RESCORES = "rescores"
RESCORE_MARKER_SOURCE = "tamper_evident_rescore"


class SampleAttemptRef(BaseModel):
    sample_id: str | int
    epoch: int
    attempt: int

    def key(self, eval_id: str, last: str) -> str:
        return (
            f"{eval_id}/{sample_key_part(self.sample_id, self.epoch)}/"
            f"{self.attempt}/{last}"
        )


class StartRecord(BaseModel):
    type: Literal["start"] = "start"
    eval_id: str
    nonce: str
    prior_eval_id: str | None = None
    """The eval a retry reuses samples from (itself a retry, possibly).

    Each reused sample has no records under this eval.
    """


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


class EvalClosingRecord(BaseModel):
    type: Literal["eval_closing"] = "eval_closing"
    eval_id: str
    nonce: str
    status: EvalStatus
    stats: EvalStats
    results: EvalResults | None = None
    samples: list[SampleAttemptRef]
    """Every sample attempt the eval started."""
    copied: list[str]
    """``<sample-id>.<epoch>`` of each sample a retry copied from its prior log.

    Its .eval file must hold each one.
    """


class RescoreRef(BaseModel, frozen=True):
    eval_id: str
    """The eval id of the .eval file that was rescored."""
    rescore_id: str


class RescoreMarker(BaseModel):
    """Data of the info event a rescore adds to each sample's new scorer events.

    Names the rescore, so a rescored .eval file says which rescores to apply
    to the original run, without a change to the log schema.
    """

    rescore: RescoreRef
    chain_length: int
    """The number of rescores in the sample's chain, this one included."""

    def event(self) -> InfoEvent:
        return InfoEvent(source=RESCORE_MARKER_SOURCE, data=self.model_dump())


def latest_marker(events: Sequence[Event]) -> RescoreMarker | None:
    """The marker of the sample's latest rescore, if any.

    The one with the longest chain: event order does not say, as an append
    moves its events under the old scorers span with the span ids of the
    dropped new one, and an overwrite can remove the marker that an earlier
    append's marker builds on. A marker that is not valid is skipped; the
    event comparison reports it.
    """

    def marker(event: Event) -> RescoreMarker | None:
        if not (isinstance(event, InfoEvent) and event.source == RESCORE_MARKER_SOURCE):
            return None
        try:
            return RescoreMarker.model_validate(event.data)
        except ValidationError:
            return None

    return max(
        filter(None, map(marker, events)),
        key=lambda m: m.chain_length,
        default=None,
    )


class RescoreStartRecord(BaseModel):
    type: Literal["rescore_start"] = "rescore_start"
    eval_id: str
    rescore_id: str
    nonce: str
    action: Literal["append", "overwrite"]


class RescoreSampleRecord(BaseModel):
    """One sample's new scores and the events the scorers added."""

    type: Literal["rescore_sample"] = "rescore_sample"
    eval_id: str
    rescore_id: str
    nonce: str
    sample_id: str | int
    epoch: int
    built_on: RescoreRef | None = None
    """The sample's latest rescore before this one (None: the original run)."""
    scores: dict[str, SampleScore]
    events: list[Event]
    """With attachments resolved."""


class RescoreClosingRecord(BaseModel):
    type: Literal["rescore_closing"] = "rescore_closing"
    eval_id: str
    rescore_id: str
    nonce: str
    results: EvalResults | None = None


StoreRecord = Annotated[
    StartRecord
    | SampleRecord
    | SampleClosingRecord
    | EvalClosingRecord
    | RescoreStartRecord
    | RescoreSampleRecord
    | RescoreClosingRecord,
    Field(discriminator="type"),
]
