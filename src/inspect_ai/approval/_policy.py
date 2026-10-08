import fnmatch
import sys
from dataclasses import dataclass
from typing import Any, Generator, Literal, NamedTuple, cast, overload

from pydantic import BaseModel, Field, model_validator

from inspect_ai._util.config import read_config_object
from inspect_ai._util.file import exists, local_path
from inspect_ai._util.format import format_value
from inspect_ai._util.registry import create_registry_object, registry_lookup
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._resource import resource

from ._approval import Approval
from ._approver import Approver
from ._call import call_approver, record_approval


@dataclass
class ApprovalPolicy:
    """Policy mapping approvers to tools."""

    approver: Approver
    """Approver for policy."""

    tools: str | list[str]
    """Tools to use this approver for (can be full tool names or globs)."""


def policy_approver(policies: str | list[ApprovalPolicy]) -> Approver:
    # if policies is a str, it is a config file or an approver
    if isinstance(policies, str):
        policies = approval_policies_from_config(policies)

    # compile policy into approvers and patterns for matching
    policy_matchers: list[tuple[list[ToolPattern], Approver]] = []
    for policy in policies:
        tool_specs = [policy.tools] if isinstance(policy.tools, str) else policy.tools
        patterns: list[ToolPattern] = []
        for spec in tool_specs:
            patterns.extend(
                tool_pattern(t.strip()) for t in _split_top_level(spec) if t.strip()
            )
        policy_matchers.append((patterns, policy.approver))

    # generator for policies that match a tool_call
    def tool_approvers(tool_call: ToolCall) -> Generator[Approver, None, None]:
        for patterns, approver in policy_matchers:
            if any(pattern.matches(tool_call) for pattern in patterns):
                yield approver

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        # process approvers for this tool call (continue loop on "escalate")
        has_approver = False
        for approver in tool_approvers(call):
            has_approver = True
            approval = await call_approver(approver, message, call, view, history)
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


@dataclass(frozen=True)
class ArgumentPattern:
    """One `name=value` item of a tool pattern's argument list."""

    name: str
    """Glob for the argument name."""

    value: str
    """Glob for the argument value, rendered by `_render_argument()`."""

    def matches(self, arguments: dict[str, Any]) -> bool:
        return any(
            fnmatch.fnmatch(name, self.name)
            and fnmatch.fnmatch(_render_argument(value), self.value)
            for name, value in arguments.items()
        )


@dataclass(frozen=True)
class ToolPattern:
    """A pattern in `ApprovalPolicy.tools`, matched against a tool call.

    The function name and the arguments are matched separately, so argument
    text cannot make a call match a pattern written for another function or
    argument.
    """

    function: str
    """Glob for the function name."""

    arguments: list[ArgumentPattern] | None
    """Argument patterns, each matching one argument in any position (None for a
    name-only pattern)."""

    closed: bool
    """The pattern ended with `)` and has no `*` item: arguments it does not
    name are not allowed."""

    def matches(self, call: ToolCall) -> bool:
        if self.arguments is None:
            return fnmatch.fnmatch(call.function, self.function)
        if not fnmatch.fnmatch(call.function, self.function):
            return False
        if not all(pattern.matches(call.arguments) for pattern in self.arguments):
            return False
        return not self.closed or all(
            any(fnmatch.fnmatch(name, pattern.name) for pattern in self.arguments)
            for name in call.arguments
        )


def tool_pattern(pattern: str) -> ToolPattern:
    """Parse a tool pattern.

    A name-only pattern (`bash`, `web_browser*`) is a prefix glob on the
    function name. A pattern with arguments (`computer(action='key'`) is a glob
    on the function name, then `name=value` items, each matched against the
    argument of that name wherever it appears in the call. String values are
    rendered in single quotes, with a backslash before each `'` and backslash
    they contain; other values as in `format_function_call()`. The last value
    is a prefix glob unless the pattern ends with `)`, which also rules out
    arguments the pattern does not name. A `*` item stands for any other
    arguments.

    Raises:
        ValueError: An argument item is not `name=value` or `*`.
    """
    if "(" not in pattern:
        glob = pattern if pattern.endswith("*") else f"{pattern}*"
        return ToolPattern(function=glob, arguments=None, closed=False)

    function, argument_text = pattern.split("(", 1)
    items = _split_top_level(argument_text, closing=True)
    stripped = [item.strip() for item in items.items]
    any_others = "*" in stripped
    arguments: list[ArgumentPattern] = []
    for item in stripped:
        if item == "" or item == "*":
            continue
        name, equals, value = item.partition("=")
        if not equals or not name.strip():
            raise ValueError(
                f"Invalid approval policy tool pattern '{pattern}': expected "
                f"name=value or * in the argument list, got '{item}'."
            )
        arguments.append(ArgumentPattern(name=name.strip(), value=value.strip()))
    if arguments and not items.closed and stripped[-1] != "*":
        last = arguments[-1]
        if not last.value.endswith("*"):
            arguments[-1] = ArgumentPattern(name=last.name, value=f"{last.value}*")
    return ToolPattern(
        function=function.strip(),
        arguments=arguments,
        closed=items.closed and not any_others,
    )


class _SplitPattern(NamedTuple):
    items: list[str]
    closed: bool


@overload
def _split_top_level(text: str) -> list[str]: ...


@overload
def _split_top_level(text: str, closing: Literal[True]) -> _SplitPattern: ...


def _split_top_level(text: str, closing: bool = False) -> list[str] | _SplitPattern:
    """Split `text` on commas outside quotes and parentheses.

    With `closing`, `text` is an argument list that may end with the `)` that
    closes it (optionally followed by `*`).
    """
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    closed = False
    for index, char in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            if depth == 0 and closing:
                if text[index + 1 :].strip() not in ("", "*"):
                    raise ValueError(
                        f"Invalid approval policy tool pattern: unexpected text "
                        f"after ')' in '{text}'."
                    )
                closed = True
                break
            depth = max(depth - 1, 0)
        elif char == "," and depth == 0:
            items.append("".join(current))
            current = []
            continue
        current.append(char)
    items.append("".join(current))
    return _SplitPattern(items, closed) if closing else items


def _render_argument(value: Any) -> str:
    """Render an argument value for matching against an argument pattern."""
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    return format_value(value, width=sys.maxsize)


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
        known_fields = set(["name", "tools", "params"])
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
    def create_approval_policy(
        name: str, tools: str | list[str], params: dict[str, Any] = {}
    ) -> ApprovalPolicy:
        approver = cast(Approver, create_registry_object("approver", name, params))
        return ApprovalPolicy(approver, tools)

    # map config -> policy
    def policy_from_config(config: ApproverPolicyConfig) -> ApprovalPolicy:
        return create_approval_policy(config.name, config.tools, config.params)

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
