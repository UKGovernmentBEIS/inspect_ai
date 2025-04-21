from pydantic import BaseModel, Field, model_validator

from inspect_ai.log._transcript import Event
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.scorer._metric import Score


class SampleEvent(BaseModel):
    id: str | int
    epoch: int
    event: Event


class SampleSummary(BaseModel):
    id: int | str
    epoch: int
    input: str | list[ChatMessage]
    target: str | list[str]
    completed: bool = Field(default=False)
    scores: dict[str, Score] | None = Field(default=None)
    error: str | None = Field(default=None)
    limit: str | None = Field(default=None)
    retries: int | None = Field(default=None)

    @model_validator(mode="after")
    def thin_scores(self) -> "SampleSummary":
        if self.scores is not None:
            self.scores = {
                key: Score(value=score.value) for key, score in self.scores.items()
            }
        return self
