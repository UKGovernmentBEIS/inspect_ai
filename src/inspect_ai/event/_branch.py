from typing import Any, Literal

from pydantic import Field, model_validator

from inspect_ai.event._base import BaseEvent


class BranchEvent(BaseEvent):
    """Marks where a branched trajectory's unique content begins.

    Emitted at the point where a branch transitions from replaying its
    parent's prefix to live execution. Events before this in the trajectory's
    span are replay-phase re-execution; events after are the branch's
    genuine new content.
    """

    event: Literal["branch"] = Field(default="branch")
    """Event type."""

    from_anchor: str = ""
    """Anchor at the branch point (matches an ``AnchorEvent.anchor_id`` in the parent)."""

    @model_validator(mode="before")
    @classmethod
    def _migrate(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data.pop("from_span", None)
            if "from_anchor" not in data and "from_message" in data:
                data["from_anchor"] = data.pop("from_message") or ""
        return data
