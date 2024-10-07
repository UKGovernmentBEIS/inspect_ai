from typing import Literal

from pydantic import BaseModel, Field

from inspect_ai.tool._tool_call import ToolCall

ApprovalDecision = Literal["approve", "modify", "reject", "terminate", "escalate"]
"""Represents the possible decisions in an approval.

Possible values:
  "approve": The action is approved.
  "modify": The action is approved with modification.
  "reject": The action is rejected.
  "terminate": Evaluation of the sample should be terminated.
  "escalate": The decision is escalated to another approver.
"""


class Approval(BaseModel):
    decision: ApprovalDecision
    """Approval decision."""

    modified: ToolCall | None = Field(default=None)
    """Modified tool call for decision 'modify'."""

    explanation: str | None = Field(default=None)
    """Explanation for decision."""
