from pydantic import BaseModel, Field, model_validator

from inspect_ai.log._transcript import Event
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.scorer._metric import Score


class SampleEvent(BaseModel):
    id: str | int
    epoch: int
    event: Event


class EvalSampleSummary(BaseModel):
    """Summary information (including scoring) for a sample."""

    id: int | str
    """Unique id for sample."""

    epoch: int
    """Epoch number for sample."""

    input: str | list[ChatMessage]
    """Sample input."""

    target: str | list[str]
    """Sample target value(s)"""

    scores: dict[str, Score] | None = Field(default=None)
    """Scores for sample."""

    error: str | None = Field(default=None)
    """Error that halted sample."""

    limit: str | None = Field(default=None)
    """Limit that halted the sample"""

    retries: int | None = Field(default=None)
    """Number of retries for the sample."""

    completed: bool = Field(default=False)
    """Is the sample complete."""

    @model_validator(mode="after")
    def thin_scores(self) -> "EvalSampleSummary":
        if self.scores is not None:
            self.scores = {
                key: Score(value=score.value) for key, score in self.scores.items()
            }
        return self
