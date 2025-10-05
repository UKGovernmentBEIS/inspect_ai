from pydantic import BaseModel

from inspect_ai.event._event import Event


class SampleEvent(BaseModel):
    id: str | int
    epoch: int
    event: Event
