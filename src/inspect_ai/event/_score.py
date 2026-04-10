from typing import Any, Literal

from pydantic import Field, model_validator

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

    role_usage: dict[str, ModelUsage] | None = Field(default=None)
    """Cumulative model usage by role at the time of this score."""

    @model_validator(mode="before")
    @classmethod
    def _coerce_null_score_value(cls, data: Any) -> Any:
        """Convert null score values to NaN for backward compatibility.

        Older eval logs (e.g. inspect_ai 0.3.134) can have intermediate
        ScoreEvents where score.value is null due to scoring errors during
        the eval run. Convert these to NaN so they can be deserialized as
        a standard Score.
        """
        if isinstance(data, dict):
            score = data.get("score")
            if isinstance(score, dict) and score.get("value") is None:
                data = {**data, "score": {**score, "value": float("nan")}}
        return data
