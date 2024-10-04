import json
from typing import Any, cast

import yaml
from pydantic import BaseModel, Field

from inspect_ai._util.registry import registry_create
from inspect_ai.util._resource import resource

from ._approver import Approver
from ._policy import ApprovalPolicy, policy_approver

"""
approvers:
   - name: human
     tools: [bash, python, web_browser*]

   - name: auto
     tools: *
"""


class ApproverPolicyConfig(BaseModel):
    name: str
    tools: str | list[str]
    params: dict[str, Any] = Field(default_factory=dict)


class ApprovalPolicyConfig(BaseModel):
    approvers: list[ApproverPolicyConfig]


def approver_from_config(policy_config: str) -> Approver:
    policies = approval_policies_from_config(policy_config)
    return policy_approver(policies)


def approval_policies_from_config(policy_config: str) -> list[ApprovalPolicy]:
    # map config -> policy
    def policy_from_config(config: ApproverPolicyConfig) -> ApprovalPolicy:
        approver = cast(
            Approver, registry_create("approver", config.name, **config.params)
        )
        return ApprovalPolicy(approver=approver, tools=config.tools)

    # resolve into approval policies
    return [
        policy_from_config(config)
        for config in read_policy_config(policy_config).approvers
    ]


def read_policy_config(policy_config: str) -> ApprovalPolicyConfig:
    # save specified policy for error message
    specified_policy_config = policy_config

    # accept string or filename
    policy_config = resource(policy_config)

    # detect json vs. yaml
    is_json = policy_config.strip().startswith("{")
    policy_config_dict = (
        json.loads(policy_config) if is_json else yaml.safe_load(policy_config)
    )
    if not isinstance(policy_config_dict, dict):
        raise ValueError(f"Invalid approval policy: {specified_policy_config}")

    # parse and validate config
    return ApprovalPolicyConfig(**policy_config_dict)
