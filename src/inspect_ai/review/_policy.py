import fnmatch
import functools
import sys
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, Field, model_validator

from inspect_ai._util.config import read_config_object
from inspect_ai._util.file import exists, local_path
from inspect_ai._util.format import format_function_call
from inspect_ai._util.registry import (
    create_registry_object,
    registry_log_name,
    registry_lookup,
)
from inspect_ai.approval._chains import chain_label, run_chains, with_escalation_context
from inspect_ai.approval._policy import _summarise
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._resource import resource

from ._call import call_reviewer, record_review
from ._review import Review, ReviewDecision
from ._reviewer import Reviewer


@dataclass
class ReviewPolicy:
    """Policy mapping reviewers to tools."""

    reviewer: Reviewer
    """Reviewer for policy."""

    tools: str | list[str]
    """Tools to use this reviewer for (can be full tool names or globs)."""


ReviewPolicies = list[ReviewPolicy] | dict[str, list[ReviewPolicy]]
"""Review policies for an eval, task or agent.

A list is one chain: reviewers are asked in order and the first decision
that is not `escalate` is final. A dict names independent chains: every
chain reviews every result, each as a lone list would, and the sample
continues only if every chain continues.
"""


def policy_reviewer(policies: str | ReviewPolicies) -> Reviewer:
    """Compile review policies into a single reviewer.

    Reviewers whose tool pattern matches the call are asked in order until one
    does not escalate. A result no policy covers, or that every covering
    reviewer escalates, continues: review is opt-in per tool.
    """
    if isinstance(policies, str):
        policies = review_policies_from_config(policies)

    # compile each chain into (globs, reviewer) pairs; a list is the one
    # unnamed chain
    chains: dict[str | None, list[tuple[list[str], Reviewer]]] = (
        {None: _compile_chain(policies)}
        if isinstance(policies, list)
        else {name: _compile_chain(members) for name, members in policies.items()}
    )

    def tool_reviewers(
        chain: list[tuple[list[str], Reviewer]], tool_call: ToolCall
    ) -> list[Reviewer]:
        function_call = format_function_call(
            tool_call.function, tool_call.arguments, width=sys.maxsize
        )
        return [
            reviewer
            for globs, reviewer in chain
            if any(fnmatch.fnmatch(function_call, pattern) for pattern in globs)
        ]

    async def run_chain(
        chain: str | None,
        reviewers: list[Reviewer],
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        chain_view = view
        escalated = False
        for reviewer in reviewers:
            reviewed = await call_reviewer(
                reviewer, message, call, result, output, chain_view, history, chain
            )
            if reviewed.decision != "escalate":
                return reviewed
            escalated = True
            chain_view = with_escalation_context(
                chain_view, registry_log_name(reviewer), chain, reviewed.explanation
            )
        if escalated:
            # an escalation nobody took: recorded, so the log shows it went unheard
            unheard = Review(
                decision="continue",
                explanation=f"No reviewer took the escalation for tool {call.function}"
                + (f' in chain "{chain}"' if chain is not None else ""),
            )
            record_review("policy", message, call, unheard, chain)
            return unheard
        return Review(decision="continue")

    async def review(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        # every chain runs, each exactly as a lone policy list does today (a
        # result none of a chain's policies cover continues: review is opt-in)
        participating = [
            (chain, tool_reviewers(members, call)) for chain, members in chains.items()
        ]
        if not participating:
            return Review(decision="continue")
        if len(participating) == 1:
            chain, reviewers = participating[0]
            return await run_chain(
                chain, reviewers, message, call, result, output, view, history
            )
        # several chains: all run; only a terminate, which nothing outranks,
        # cancels the rest
        results = await run_chains(
            [
                (
                    chain,
                    functools.partial(
                        run_chain,
                        chain,
                        reviewers,
                        message,
                        call,
                        result,
                        output,
                        view,
                        history,
                    ),
                )
                for chain, reviewers in participating
            ],
            decisive=lambda reviewed: reviewed.decision == "terminate",
        )
        combined = combine_chain_reviews([chain for chain, _ in participating], results)
        record_review("policy", message, call, combined)
        return combined

    return review


def _compile_chain(
    policies: list[ReviewPolicy],
) -> list[tuple[list[str], Reviewer]]:
    compiled: list[tuple[list[str], Reviewer]] = []
    for policy in policies:
        tool_specs = [policy.tools] if isinstance(policy.tools, str) else policy.tools
        tools: list[str] = []
        for spec in tool_specs:
            tools.extend([t.strip() for t in spec.split(",") if t.strip()])
        globs = [tool if tool.endswith("*") else f"{tool}*" for tool in tools]
        compiled.append((globs, policy.reviewer))
    return compiled


def combine_chain_reviews(
    chains: list[str | None], results: dict[str | None, Review]
) -> Review:
    """The decision several chains reach together: terminate if any did."""
    outcomes = {
        chain_label(chain): (
            {
                "decision": results[chain].decision,
                "explanation": results[chain].explanation,
            }
            if chain in results
            else {"decision": "cancelled", "explanation": None}
        )
        for chain in chains
    }
    metadata = {"chains": outcomes}
    summary = _summarise(outcomes)
    decision: ReviewDecision = (
        "terminate"
        if any(reviewed.decision == "terminate" for reviewed in results.values())
        else "continue"
    )
    return Review(decision=decision, explanation=summary, metadata=metadata)


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
    """
    Review policy configuration: a list of reviewers, or named chains of them.

    A list is one chain. A mapping names independent chains that all review
    every result:

    ```yaml
    reviewers:
      output:
        - name: output_monitor
          tools: "*"
        - name: human
          tools: "*"
      exfil:
        - name: exfiltration_monitor
          tools: "*"
    ```
    """

    reviewers: list[ReviewerPolicyConfig] | dict[str, list[ReviewerPolicyConfig]]


def read_review_policies(file: str) -> ReviewPolicies:
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
) -> ReviewPolicies:
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

    reviewers = policy_config.reviewers
    if isinstance(reviewers, list):
        return [policy_from_config(config) for config in reviewers]
    return {
        chain: [policy_from_config(config) for config in members]
        for chain, members in reviewers.items()
    }


def config_from_review_policies(
    policies: ReviewPolicies,
) -> ReviewPolicyConfig:
    from inspect_ai._util.registry import registry_log_name, registry_params

    def config_from_policy(policy: ReviewPolicy) -> ReviewerPolicyConfig:
        return ReviewerPolicyConfig(
            name=registry_log_name(policy.reviewer),
            tools=policy.tools,
            params=registry_params(policy.reviewer),
        )

    if isinstance(policies, list):
        return ReviewPolicyConfig(
            reviewers=[config_from_policy(policy) for policy in policies]
        )
    return ReviewPolicyConfig(
        reviewers={
            chain: [config_from_policy(policy) for policy in members]
            for chain, members in policies.items()
        }
    )


def read_policy_config(policy_config: str) -> ReviewPolicyConfig:
    specified_policy_config = policy_config
    policy_config = resource(policy_config, type="file")
    policy_config_dict = read_config_object(policy_config)
    if not isinstance(policy_config_dict, dict):
        raise ValueError(f"Invalid review policy: {specified_policy_config}")
    return ReviewPolicyConfig(**policy_config_dict)
