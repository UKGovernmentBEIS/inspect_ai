import abc
from typing import Iterator, TypeAlias

from pydantic import BaseModel, JsonValue

from ..types import SampleSummary

JsonData: TypeAlias = dict[str, JsonValue]


class SampleInfo(BaseModel):
    id: str
    epoch: int
    sample: SampleSummary | None


class EventInfo(BaseModel):
    id: int
    event_id: str
    sample_id: str
    epoch: int
    event: JsonData


class AttachmentInfo(BaseModel):
    id: int
    hash: str
    content: str


class SampleBuffer(abc.ABC):
    @abc.abstractmethod
    def get_samples(self, resolve_attachments: bool = True) -> Iterator[SampleInfo]: ...

    @abc.abstractmethod
    def get_events(
        self,
        id: str | int,
        epoch: int,
        after_event_id: int | None = None,
        resolve_attachments: bool = True,
    ) -> Iterator[EventInfo]: ...

    @abc.abstractmethod
    def get_attachments(
        self, after_attachment_id: int | None = None
    ) -> Iterator[AttachmentInfo]: ...

    @abc.abstractmethod
    def get_attachments_content(self, hashes: list[str]) -> dict[str, str | None]: ...
