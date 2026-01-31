from typing import Literal

from pydantic import Field

from inspect_ai.event._base import BaseEvent
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.scorer._metric import Score


class ScoreEvent(BaseEvent):
    """Event with score.

    Can be the final score for a `Sample`, or can be an intermediate score
    resulting from a call to `score`.
    """

    event: Literal["score"] = Field(default="score")
    """Event type."""

    score: Score
    """Score value."""

    target: str | list[str] | None = Field(default=None)
    """"Sample target."""

    intermediate: bool = Field(default=False)
    """Was this an intermediate scoring?"""

    model_usage: dict[str, ModelUsage] | None = Field(default=None)
    """Cumulative model usage at the time of this score."""
