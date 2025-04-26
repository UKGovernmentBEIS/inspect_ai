import abc
from typing import Literal, TypeAlias

from pydantic import BaseModel, JsonValue

from inspect_ai._display.core.display import TaskDisplayMetric

from ..._log import EvalSampleSummary

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


class SampleData(BaseModel):
    events: list[EventData]
    attachments: list[AttachmentData]


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
    ) -> SampleData | None:
        """Get event and attachment data for a sample.

        Args:
          id: Sample id
          epoch: Sample epoch
          after_event_id: Optional. Fetch only event data greater than this id.
          after_attachment_id: Optioinal. Fetch only attachment data greater than this id.

        Returns:
          - `SampleData` with event and attachment data.
          - None if the database no longer exists
        """
        ...
