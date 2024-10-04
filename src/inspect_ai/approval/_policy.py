import fnmatch
import json
import re
from dataclasses import dataclass
from re import Pattern
from typing import Any, Generator, cast

import yaml
from pydantic import BaseModel, Field

from inspect_ai._util.registry import registry_create
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.util._resource import resource

from ._approval import Approval
from ._approver import Approver
from ._call import call_approver, record_approval


@dataclass
class ApprovalPolicy:
    approver: Approver
    tools: str | list[str]


def policy_approver(
    policies: str | list[ApprovalPolicy], print: bool = True, log: bool = True
) -> Approver:
    # if policies is a str then its a config file
    if isinstance(policies, str):
        policies = approval_policies_from_config(policies)

    # compile policy into approvers and regexes for matching
    policy_matchers: list[tuple[list[Pattern[str]], Approver]] = []
    for policy in policies:
        tools = [policy.tools] if isinstance(policy.tools, str) else policy.tools
        patterns = [re.compile(fnmatch.translate(tool)) for tool in tools]
        policy_matchers.append((patterns, policy.approver))

    # generator for policies that match a tool_call
    def tool_approvers(tool_call: ToolCall) -> Generator[Approver, None, None]:
        for policy_matcher in iter(policy_matchers):
            if any(
                [pattern.match(tool_call.function) for pattern in policy_matcher[0]]
            ):
                yield policy_matcher[1]

    async def approve(
        tool_call: ToolCall, tool_view: str, state: TaskState | None = None
    ) -> Approval:
        # process approvers for this tool call (continue loop on "escalate")
        for approver in tool_approvers(tool_call):
            approval = await call_approver(
                approver, tool_call, tool_view, state, print, log
            )
            if approval.decision != "escalate":
                return approval

        # if there are no approvers then we reject
        reject = Approval(
            decision="reject",
            explanation=f"No approvers registered for tool {tool_call.function}",
        )
        # record and return the rejection
        record_approval("policy", reject, tool_call, print, log)
        return reject

    return approve


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


def approval_policies_from_config(
    policy_config: str | ApprovalPolicyConfig,
) -> list[ApprovalPolicy]:
    # map config -> policy
    def policy_from_config(config: ApproverPolicyConfig) -> ApprovalPolicy:
        approver = cast(
            Approver, registry_create("approver", config.name, **config.params)
        )
        return ApprovalPolicy(approver=approver, tools=config.tools)

    # resolve config if its a file
    if isinstance(policy_config, str):
        policy_config = read_policy_config(policy_config)

    # resolve into approval policies
    return [policy_from_config(config) for config in policy_config.approvers]


def config_from_approval_policies(
    policies: list[ApprovalPolicy],
) -> ApprovalPolicyConfig:
    from inspect_ai._util.registry import (
        registry_log_name,
        registry_params,
    )

    approvers: list[ApproverPolicyConfig] = []
    for policy in policies:
        name = registry_log_name(policy.approver)
        params = registry_params(policy.approver)
        approvers.append(
            ApproverPolicyConfig(name=name, tools=policy.tools, params=params)
        )

    return ApprovalPolicyConfig(approvers=approvers)


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
