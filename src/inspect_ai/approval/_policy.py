from pydantic import BaseModel


class ApproverPolicy:
    name: str
    tools: str | list[str]


class ApprovalPolicy(BaseModel):
    approvers: list[ApproverPolicy]
