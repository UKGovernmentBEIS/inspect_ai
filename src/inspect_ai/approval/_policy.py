import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from re import Pattern
from typing import Any, Generator, cast

from pydantic import BaseModel, Field, model_validator

from inspect_ai._util.config import read_config_object
from inspect_ai._util.registry import registry_create, registry_lookup
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._resource import resource

from ._approval import Approval
from ._approver import Approver
from ._call import call_approver, record_approval


@dataclass
class ApprovalPolicy:
    approver: Approver
    tools: str | list[str]


def policy_approver(policies: str | list[ApprovalPolicy]) -> Approver:
    # if policies is a str, it is a config file or an approver
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
        message: str,
        call: ToolCall,
        view: ToolCallView,
        state: TaskState | None = None,
    ) -> Approval:
        # process approvers for this tool call (continue loop on "escalate")
        has_approver = False
        for approver in tool_approvers(call):
            has_approver = True
            approval = await call_approver(approver, message, call, view, state)
            if approval.decision != "escalate":
                return approval

        # if there are no approvers then we reject
        reject = Approval(
            decision="reject",
            explanation=f"No {'approval granted' if has_approver else 'approvers registered'} for tool {call.function}",
        )
        # record and return the rejection
        record_approval("policy", message, call, view, reject)
        return reject

    return approve


class ApproverPolicyConfig(BaseModel):
    """
    Configuration format for approver policies.

    For example, here is a configuration in YAML:

    ```yaml
    approvers:
      - name: human
        tools: web_browser*, bash, pyhton
        choices: [approve, reject]

      - name: auto
        tools: *
        decision: approve
    ```
    """

    name: str
    tools: str | list[str]
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "extra": "allow",
    }

    @model_validator(mode="before")
    @classmethod
    def collect_unknown_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        known_fields = set(cls.model_fields.keys())
        unknown_fields = {k: v for k, v in data.items() if k not in known_fields}

        if unknown_fields:
            data["params"] = data.get("params", {}) | unknown_fields
            for k in unknown_fields:
                data.pop(k, None)

        return data


class ApprovalPolicyConfig(BaseModel):
    approvers: list[ApproverPolicyConfig]


def approver_from_config(policy_config: str) -> Approver:
    policies = approval_policies_from_config(policy_config)
    return policy_approver(policies)


def approval_policies_from_config(
    policy_config: str | ApprovalPolicyConfig,
) -> list[ApprovalPolicy]:
    # create approver policy
    def create_approval_policy(
        name: str, tools: str | list[str], params: dict[str, Any] = {}
    ) -> ApprovalPolicy:
        approver = cast(Approver, registry_create("approver", name, **params))
        return ApprovalPolicy(approver, tools)

    # map config -> policy
    def policy_from_config(config: ApproverPolicyConfig) -> ApprovalPolicy:
        return create_approval_policy(config.name, config.tools, config.params)

    # resolve config if its a string
    if isinstance(policy_config, str):
        if Path(policy_config).exists():
            policy_config = read_policy_config(policy_config)
        elif registry_lookup("approver", policy_config):
            policy_config = ApprovalPolicyConfig(
                approvers=[ApproverPolicyConfig(name=policy_config, tools="*")]
            )
        else:
            raise ValueError(f"Invalid approval policy: {policy_config}")

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

    # read config file
    policy_config = resource(policy_config, type="file")

    # detect json vs. yaml
    policy_config_dict = read_config_object(policy_config)
    if not isinstance(policy_config_dict, dict):
        raise ValueError(f"Invalid approval policy: {specified_policy_config}")

    # parse and validate config
    return ApprovalPolicyConfig(**policy_config_dict)
