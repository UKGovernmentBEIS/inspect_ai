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
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._resource import resource

from ._approval import Approval
from ._approver import Approver
from ._call import call_approver, record_approval
from ._chains import chain_label, run_chains, with_escalation_context


@dataclass
class ApprovalPolicy:
    """Policy mapping approvers to tools."""

    approver: Approver
    """Approver for policy."""

    tools: str | list[str]
    """Tools to use this approver for (can be full tool names or globs)."""

    chain: str | None = None
    """Chain this policy belongs to.

    Policies sharing a chain name form one chain (asked in order, first
    non-escalate decision wins). Every chain matching a call runs, and the
    call proceeds only if every chain approves. `None` is the default chain.
    """


def policy_approver(policies: str | list[ApprovalPolicy]) -> Approver:
    # if policies is a str, it is a config file or an approver
    if isinstance(policies, str):
        policies = approval_policies_from_config(policies)

    # compile policies into chains of (globs, approver), in order of first appearance
    chains: dict[str | None, list[tuple[list[str], Approver]]] = {}
    for policy in policies:
        tool_specs = [policy.tools] if isinstance(policy.tools, str) else policy.tools
        tools: list[str] = []
        for spec in tool_specs:
            tools.extend([t.strip() for t in spec.split(",") if t.strip()])
        globs = [tool if tool.endswith("*") else f"{tool}*" for tool in tools]
        chains.setdefault(policy.chain, []).append((globs, policy.approver))

    # approvers in a chain that match a tool call
    def tool_approvers(
        chain: list[tuple[list[str], Approver]], tool_call: ToolCall
    ) -> list[Approver]:
        function_call = format_function_call(
            tool_call.function, tool_call.arguments, width=sys.maxsize
        )
        return [
            approver
            for globs, approver in chain
            if any(fnmatch.fnmatch(function_call, pattern) for pattern in globs)
        ]

    async def run_chain(
        chain: str | None,
        approvers: list[Approver],
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        # process approvers for this tool call (continue loop on "escalate",
        # telling the next approver who escalated and why)
        chain_view = view
        has_approver = False
        for approver in approvers:
            has_approver = True
            approval = await call_approver(
                approver, message, call, chain_view, history, chain
            )
            if approval.decision != "escalate":
                return approval
            chain_view = with_escalation_context(
                chain_view, registry_log_name(approver), chain, approval.explanation
            )

        # no approver covers the call, or an escalation nobody took: reject
        reject = Approval(
            decision="reject",
            explanation=f"No {'approval granted' if has_approver else 'approvers registered'} for tool {call.function}"
            + (f' in chain "{chain}"' if chain is not None else ""),
        )
        record_approval("policy", message, call, view, reject, chain)
        return reject

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        # every chain runs, each exactly as a lone policy list does today
        participating = [
            (chain, tool_approvers(members, call)) for chain, members in chains.items()
        ]

        # no policies at all: reject as today
        if not participating:
            reject = Approval(
                decision="reject",
                explanation=f"No approvers registered for tool {call.function}",
            )
            record_approval("policy", message, call, view, reject)
            return reject

        # a single chain decides on its own (today's behaviour)
        if len(participating) == 1:
            chain, approvers = participating[0]
            return await run_chain(chain, approvers, message, call, view, history)

        # several chains: all run to their decision (a reject does not stop a
        # chain that might terminate or ask a human); only a terminate, which
        # nothing outranks, cancels the rest. The most severe decision wins.
        results = await run_chains(
            [
                (
                    chain,
                    functools.partial(
                        run_chain, chain, approvers, message, call, view, history
                    ),
                )
                for chain, approvers in participating
            ],
            decisive=lambda approval: approval.decision == "terminate",
        )
        combined = combine_chain_approvals(
            call, [chain for chain, _ in participating], results
        )
        record_approval("policy", message, call, view, combined)
        return combined

    return approve


def combine_chain_approvals(
    call: ToolCall,
    chains: list[str | None],
    results: dict[str | None, Approval],
) -> Approval:
    """The decision several chains reach together: the most severe of theirs.

    `modify` is honoured only from a lone chain; across chains it is a
    rejection, since the other chains approved the original arguments.
    """
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
    decisions = {approval.decision for approval in results.values()}
    if "terminate" in decisions:
        return Approval(decision="terminate", explanation=summary, metadata=metadata)
    if "reject" in decisions:
        return Approval(decision="reject", explanation=summary, metadata=metadata)
    modifiers = [
        chain_label(chain)
        for chain in chains
        if chain in results and results[chain].decision == "modify"
    ]
    if modifiers:
        return Approval(
            decision="reject",
            explanation=(
                f"Chain {', '.join(repr(m) for m in modifiers)} modified the call to "
                f"{call.function}, but a modification is only honoured when a single "
                f"chain applies. {summary}"
            ),
            metadata=metadata,
        )
    return Approval(decision="approve", explanation=summary, metadata=metadata)


def _summarise(outcomes: dict[str, dict[str, str | None]]) -> str:
    """One line per chain with its decision and reason, e.g. `x: reject (no network)`.

    This is the text the model (and a human) sees when the call is rejected or
    the sample terminated, so the deciding chain's own reason must be in it.
    """
    return "; ".join(
        f"{label}: {outcome['decision']}"
        + (f" ({outcome['explanation']})" if outcome["explanation"] else "")
        for label, outcome in outcomes.items()
    )


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
    chain: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "extra": "allow",
    }

    @model_validator(mode="before")
    @classmethod
    def collect_unknown_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        known_fields = set(["name", "tools", "chain", "params"])
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


def read_approval_policies(file: str) -> list[ApprovalPolicy]:
    """Read approval policies from a JSON or YAML config file.

    Args:
        file: JSON or YAML config file with approval policies.
    """
    file = local_path(file)
    if not exists(file):
        raise FileNotFoundError(f"Approval policy file not found: {file}")
    return approval_policies_from_config(file)


def approval_policies_from_config(
    policy_config: str | ApprovalPolicyConfig,
) -> list[ApprovalPolicy]:
    # create approver policy
    def policy_from_config(config: ApproverPolicyConfig) -> ApprovalPolicy:
        approver = cast(
            Approver, create_registry_object("approver", config.name, config.params)
        )
        return ApprovalPolicy(approver, config.tools, config.chain)

    # resolve config if its a string
    if isinstance(policy_config, str):
        # decode file:// URIs; fsspec's exists() does not percent-decode
        policy_path = local_path(policy_config)
        if exists(policy_path):
            policy_config = read_policy_config(policy_path)
        elif registry_lookup("approver", policy_path):
            policy_config = ApprovalPolicyConfig(
                approvers=[ApproverPolicyConfig(name=policy_path, tools="*")]
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
            ApproverPolicyConfig(
                name=name, tools=policy.tools, chain=policy.chain, params=params
            )
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
