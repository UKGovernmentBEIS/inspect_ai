from typing import Literal

from pydantic import BaseModel, Field

ApprovalDecision = Literal["approve", "reject", "escalate", "terminate"]


class Approval(BaseModel):
    decision: ApprovalDecision
    explanation: str | None = Field(default=None)
