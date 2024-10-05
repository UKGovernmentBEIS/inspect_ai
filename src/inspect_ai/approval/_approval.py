from typing import Literal

from pydantic import BaseModel, Field

ApprovalDecision = Literal["approve", "reject", "terminate", "escalate"]
"""Represents the possible decisions in an approval.

Possible values:
  "approve": The action is approved.
  "reject": The action is rejected.
  "terminate": Evaluation of the sample should be terminated.
  "escalate": The decision is escalated to another approver.
"""


class Approval(BaseModel):
    decision: ApprovalDecision
    """Approval decision."""

    explanation: str | None = Field(default=None)
    """Explanation for decision."""
