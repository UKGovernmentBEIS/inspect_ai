import json
from typing import Any

import yaml
from pydantic import BaseModel, Field

from inspect_ai.util._resource import resource


class ApproverPolicyConfig(BaseModel):
    name: str
    tools: str | list[str]
    params: dict[str, Any] = Field(default_factory=dict)


class ApprovalPolicyConfig(BaseModel):
    approvers: list[ApproverPolicyConfig]


def read_policy_config(policy: str | dict[str, Any]) -> ApprovalPolicyConfig:
    # save specified policy for error message
    specified_policy = policy

    # first resolve policy to dict
    if isinstance(policy, str):
        # accept string or filename
        policy = resource(policy)

        # detect json vs. yaml
        is_json = policy.strip().startswith("{")
        policy = json.loads(policy) if is_json else yaml.safe_load(policy)
        if not isinstance(policy, dict):
            raise ValueError(f"Invalid approval policy: {specified_policy}")

    # parse and validate config
    return ApprovalPolicyConfig(**policy)
