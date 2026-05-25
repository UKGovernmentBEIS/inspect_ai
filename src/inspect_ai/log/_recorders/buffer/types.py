import abc
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Literal, TypeAlias

from pydantic import BaseModel, JsonValue

from inspect_ai._display.core.display import TaskDisplayMetric

from ..._log import EvalSampleSummary

if TYPE_CHECKING:
    from inspect_ai.util._checkpoint._transcript_store import CheckpointTranscriptStore

    from .history import SampleHistory

JsonData: TypeAlias = dict[str, JsonValue]


class Samples(BaseModel):
    samples: list[EvalSampleSummary]
    metrics: list[TaskDisplayMetric]
    refresh: int
    etag: str


class EventData(BaseModel):
    id: int
    event_id: str
    sample_id: str
    epoch: int
    event: JsonData


class AttachmentData(BaseModel):
    id: int
    sample_id: str
    epoch: int
    hash: str
    content: str


class MessagePoolData(BaseModel):
    id: int
    sample_id: str
    epoch: int
    msg_id: str
    data: str


class CallPoolData(BaseModel):
    id: int
    sample_id: str
    epoch: int
    hash: str
    data: str


class SampleData(BaseModel):
    events: list[EventData]
    attachments: list[AttachmentData]
    message_pool: list[MessagePoolData] = []
    call_pool: list[CallPoolData] = []


class SegmentRef(BaseModel):
    id: int
    """Segment id (matches `Segment.id` in the manifest)."""
    member_name: str
    """File inside the segment zip to extract (e.g. "42_0.json")."""
    direct_url: str | None
    """Presigned URL for the segment zip, or None when unavailable."""


class PendingSampleUrls(BaseModel):
    segments: list[SegmentRef]
    """Segments to fetch, already pruned by the server against the cursors."""
    complete: bool
    """Whether the sample has completed (matches EvalSampleSummary.completed)."""
    has_more: bool = False
    """True when the server truncated the segment list (more remain past this chunk)."""


class SampleBuffer(abc.ABC):
    @classmethod
    @abc.abstractmethod
    def running_tasks(cls, log_dir: str) -> list[str] | None: ...

    @abc.abstractmethod
    def get_samples(
        self, etag: str | None = None
    ) -> Samples | Literal["NotModified"] | None:
        """Get the manifest of all running samples.

        Args:
          etag: Optional etag (returned in `Samples`) for checking
            whether there are any changes in the datatabase.

        Returns:
          - `Samples` if the database exists and has updates
          - "NotModifed" if the database exists and has no updates.
          - None if the database no longer exists

        """
        ...

    @abc.abstractmethod
    def get_sample_data(
        self,
        id: str | int,
        epoch: int,
        after_event_id: int | None = None,
        after_attachment_id: int | None = None,
        after_message_pool_id: int | None = None,
        after_call_pool_id: int | None = None,
    ) -> SampleData | None:
        """Get event and attachment data for a sample.

        Args:
          id: Sample id
          epoch: Sample epoch
          after_event_id: Optional. Fetch only event data greater than this id.
          after_attachment_id: Optional. Fetch only attachment data greater than this id.
          after_message_pool_id: Optional. Fetch only message pool data greater than this id.
          after_call_pool_id: Optional. Fetch only call pool data greater than this id.

        Returns:
          - `SampleData` with event, attachment, and pool data.
          - None if the database no longer exists
        """
        ...

    @abc.abstractmethod
    def sample_event_count(self, id: str | int, epoch: int) -> int:
        """Return the number of distinct events recorded for a sample."""
        ...

    @abc.abstractmethod
    def import_checkpoint_events(
        self, id: str | int, epoch: int, transcript_store: "CheckpointTranscriptStore"
    ) -> int:
        """Import a sample's full event history into a checkpoint transcript store."""
        ...

    @abc.abstractmethod
    def open_sample_history_tail(
        self,
        id: str | int,
        epoch: int,
        n: int,
    ) -> AbstractContextManager["SampleHistory"]:
        """Open a consistent snapshot of the last ``n`` sample events."""
        ...

    @abc.abstractmethod
    def open_sample_history_from(
        self,
        id: str | int,
        epoch: int,
        start: int,
    ) -> AbstractContextManager["SampleHistory"]:
        """Open a consistent sample-history snapshot from ``start`` onward."""
        ...

    @abc.abstractmethod
    def open_sample_history(
        self,
        id: str | int,
        epoch: int,
    ) -> AbstractContextManager["SampleHistory"]:
        """Open a consistent snapshot of the full sample history."""
        ...

    @abc.abstractmethod
    def cleanup(self) -> None:
        """Remove this buffer's backing storage."""
        ...
