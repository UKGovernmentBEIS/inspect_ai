import fnmatch
import sys
from dataclasses import dataclass
from typing import Any, Generator, cast

from pydantic import BaseModel, Field, model_validator

from inspect_ai._util.config import read_config_object
from inspect_ai._util.file import exists, local_path
from inspect_ai._util.format import format_function_call
from inspect_ai._util.registry import create_registry_object, registry_lookup
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._resource import resource

from ._call import call_reviewer, record_review
from ._review import Review
from ._reviewer import Reviewer


@dataclass
class ReviewPolicy:
    """Policy mapping reviewers to tools."""

    reviewer: Reviewer
    """Reviewer for policy."""

    tools: str | list[str]
    """Tools to use this reviewer for (can be full tool names or globs)."""


def policy_reviewer(policies: str | list[ReviewPolicy]) -> Reviewer:
    """Compile review policies into a single reviewer.

    Reviewers whose tool pattern matches the call are asked in order until one
    does not escalate. A result no policy covers, or that every covering
    reviewer escalates, continues: review is opt-in per tool.
    """
    if isinstance(policies, str):
        policies = review_policies_from_config(policies)

    policy_matchers: list[tuple[list[str], Reviewer]] = []
    for policy in policies:
        tool_specs = [policy.tools] if isinstance(policy.tools, str) else policy.tools
        tools: list[str] = []
        for spec in tool_specs:
            tools.extend([t.strip() for t in spec.split(",") if t.strip()])
        globs = [tool if tool.endswith("*") else f"{tool}*" for tool in tools]
        policy_matchers.append((globs, policy.reviewer))

    def tool_reviewers(tool_call: ToolCall) -> Generator[Reviewer, None, None]:
        function_call = format_function_call(
            tool_call.function, tool_call.arguments, width=sys.maxsize
        )
        for globs, reviewer in policy_matchers:
            if any(fnmatch.fnmatch(function_call, pattern) for pattern in globs):
                yield reviewer

    async def review(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        escalated = False
        for reviewer in tool_reviewers(call):
            reviewed = await call_reviewer(
                reviewer, message, call, result, output, view, history
            )
            if reviewed.decision != "escalate":
                return reviewed
            escalated = True
        if escalated:
            # an escalation nobody took: recorded, so the log shows it went unheard
            unheard = Review(
                decision="continue",
                explanation=f"No reviewer took the escalation for tool {call.function}",
            )
            record_review("policy", message, call, unheard)
            return unheard
        return Review(decision="continue")

    return review


class ReviewerPolicyConfig(BaseModel):
    """
    Configuration format for reviewer policies.

    For example, here is a configuration in YAML:

    ```yaml
    reviewers:
      - name: mypackage/output_monitor
        tools: bash, python

      - name: human
        tools: "*"
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
        known_fields = set(["name", "tools", "params"])
        unknown_fields = {k: v for k, v in data.items() if k not in known_fields}

        if unknown_fields:
            data["params"] = data.get("params", {}) | unknown_fields
            for k in unknown_fields:
                data.pop(k, None)

        return data


class ReviewPolicyConfig(BaseModel):
    reviewers: list[ReviewerPolicyConfig]


def read_review_policies(file: str) -> list[ReviewPolicy]:
    """Read review policies from a JSON or YAML config file.

    Args:
        file: JSON or YAML config file with review policies.
    """
    file = local_path(file)
    if not exists(file):
        raise FileNotFoundError(f"Review policy file not found: {file}")
    return review_policies_from_config(file)


def review_policies_from_config(
    policy_config: str | ReviewPolicyConfig,
) -> list[ReviewPolicy]:
    def policy_from_config(config: ReviewerPolicyConfig) -> ReviewPolicy:
        reviewer = cast(
            Reviewer, create_registry_object("reviewer", config.name, config.params)
        )
        return ReviewPolicy(reviewer, config.tools)

    if isinstance(policy_config, str):
        policy_path = local_path(policy_config)
        if exists(policy_path):
            policy_config = read_policy_config(policy_path)
        elif registry_lookup("reviewer", policy_path):
            policy_config = ReviewPolicyConfig(
                reviewers=[ReviewerPolicyConfig(name=policy_path, tools="*")]
            )
        else:
            raise ValueError(f"Invalid review policy: {policy_config}")

    return [policy_from_config(config) for config in policy_config.reviewers]


def config_from_review_policies(
    policies: list[ReviewPolicy],
) -> ReviewPolicyConfig:
    from inspect_ai._util.registry import registry_log_name, registry_params

    reviewers: list[ReviewerPolicyConfig] = []
    for policy in policies:
        name = registry_log_name(policy.reviewer)
        params = registry_params(policy.reviewer)
        reviewers.append(
            ReviewerPolicyConfig(name=name, tools=policy.tools, params=params)
        )

    return ReviewPolicyConfig(reviewers=reviewers)


def read_policy_config(policy_config: str) -> ReviewPolicyConfig:
    specified_policy_config = policy_config
    policy_config = resource(policy_config, type="file")
    policy_config_dict = read_config_object(policy_config)
    if not isinstance(policy_config_dict, dict):
        raise ValueError(f"Invalid review policy: {specified_policy_config}")
    return ReviewPolicyConfig(**policy_config_dict)
