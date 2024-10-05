from typing import Literal

from pydantic import BaseModel, Field

ApprovalDecision = Literal["approve", "reject", "escalate", "terminate"]


class Approval(BaseModel):
    decision: ApprovalDecision
    """Approval decision."""

    explanation: str | None = Field(default=None)
    """Explanation for decision."""
