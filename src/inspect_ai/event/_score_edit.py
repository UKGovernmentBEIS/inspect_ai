from typing import Literal

from pydantic import ConfigDict, Field

from inspect_ai.event._base import BaseEvent
from inspect_ai.scorer._metric import ScoreEdit


class ScoreEditEvent(BaseEvent):
    """Event recorded when a score is edited."""

    model_config = ConfigDict(ser_json_inf_nan="constants")

    event: Literal["score_edit"] = Field(default="score_edit")
    """Event type."""

    score_name: str
    """Name of the score being edited."""

    edit: ScoreEdit
    """The edit being applied to the score."""
