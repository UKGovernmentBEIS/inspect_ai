import abc
from typing import TypeAlias

from pydantic import BaseModel, JsonValue

from ..types import SampleSummary

JsonData: TypeAlias = dict[str, JsonValue]


class Samples(BaseModel):
    samples: list[SampleSummary]
    etag: str


class SampleInfo(BaseModel):
    id: str
    epoch: int
    sample: SampleSummary | None


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
    @abc.abstractmethod
    def get_samples(self) -> Samples: ...

    @abc.abstractmethod
    def get_sample_data(
        self,
        id: str | int,
        epoch: int,
        after_event_id: int | None = None,
        after_attachment_id: int | None = None,
    ) -> SampleData: ...
