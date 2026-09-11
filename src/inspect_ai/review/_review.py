from typing import Any, Literal

from pydantic import BaseModel, Field

ReviewDecision = Literal["continue", "terminate", "escalate"]
"""Represents the possible decisions in a review.

Possible values:
  "continue": The result is passed to the model unchanged.
  "terminate": Evaluation of the sample should be terminated.
  "escalate": The decision is escalated to the next reviewer.
"""


class Review(BaseModel):
    """Review details (decision, explanation, etc.)"""

    decision: ReviewDecision
    """Review decision."""

    explanation: str | None = Field(default=None)
    """Explanation for decision."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional review metadata."""
