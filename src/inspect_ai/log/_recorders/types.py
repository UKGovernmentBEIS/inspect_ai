from pydantic import BaseModel

from inspect_ai.log._transcript import Event


class SampleEvent(BaseModel):
    id: str | int
    epoch: int
    event: Event
