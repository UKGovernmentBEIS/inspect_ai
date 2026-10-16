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
    policy_matchers = [
        (tool_patterns(policy.tools), policy.approver) for policy in policies
    ]

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
    """The argument name (not a glob)."""

    value: str
    """Glob for the argument value, rendered by `_render_argument()`."""

    def matches(self, arguments: dict[str, Any]) -> bool:
        return self.name in arguments and fnmatch.fnmatch(
            _render_argument(arguments[self.name]), self.value
        )


@dataclass(frozen=True)
class ToolPattern:
    """A pattern in an approval or review policy's `tools`.

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
        names = {pattern.name for pattern in self.arguments}
        return not self.closed or all(name in names for name in call.arguments)


def tool_patterns(tools: str | list[str]) -> list[ToolPattern]:
    """Parse the `tools` of an approval or review policy.

    Each string is a comma-separated list of patterns. Commas inside quotes or
    an argument list do not split it, so a pattern with arguments that does
    not end with `)` takes the rest of the string.
    """
    specs = [tools] if isinstance(tools, str) else tools
    return [
        tool_pattern(item.strip())
        for spec in specs
        for item in _split_top_level(spec)
        if item.strip()
    ]


def tool_pattern(pattern: str) -> ToolPattern:
    """Parse a tool pattern.

    A name-only pattern (`bash`, `web_browser*`) is a prefix glob on the
    function name. A pattern with arguments (`computer(action='key'`) is a glob
    on the function name, then `name=value` items, each matched against the
    argument of that name wherever it appears in the call. Argument names are
    literal, not globs. String values are
    rendered in single quotes, with a backslash before each `'` and backslash
    they contain; other values as in `format_function_call()`. The last value
    is a prefix glob unless the pattern ends with `)`, which also rules out
    arguments the pattern does not name. A `*` item stands for any other
    arguments.

    Raises:
        ValueError: An argument item is not `name=value` or `*`, its name
            contains a glob character, or it runs into what may be the next
            pattern in a comma-separated string.
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
        name, value = name.strip(), value.strip()
        if (
            not equals
            or not name
            or any(char in name for char in "()'\"")
            or len(name.split()) > 1
        ):
            raise ValueError(
                f"Invalid tool pattern '{pattern}': expected name=value or * "
                f"in the argument list, got '{item}'. {_NEXT_TOOL_HINT}"
            )
        if any(char in name for char in "*?[]"):
            raise ValueError(
                f"Invalid tool pattern '{pattern}': argument names must be "
                f"literal, got '{name}'."
            )
        run_on = _value_runs_on(value)
        if run_on == "unclosed":
            raise ValueError(
                f"Invalid tool pattern '{pattern}': the value of '{name}' may "
                f"run into the next pattern. {_NEXT_TOOL_HINT} A value that "
                f"contains a comma must be closed with a quote, as in "
                f"{name}='a, b*'."
            )
        elif run_on == "trailing":
            raise ValueError(
                f"Invalid tool pattern '{pattern}': the value of '{name}' has "
                f"text after its closing quote. Put a backslash before a quote "
                f"inside a value, as in {name}='it\\'s'. {_NEXT_TOOL_HINT}"
            )
        arguments.append(ArgumentPattern(name=name, value=value))
    if arguments and not items.closed and stripped[-1] != "*":
        last = arguments[-1]
        if not last.value.endswith("*"):
            arguments[-1] = ArgumentPattern(name=last.name, value=f"{last.value}*")
    return ToolPattern(
        function=function.strip(),
        arguments=arguments,
        closed=items.closed and not any_others,
    )


_NEXT_TOOL_HINT = (
    "To list another tool after this pattern, end the pattern with ', *)' or "
    "give the tool as a separate list item."
)


def _value_runs_on(value: str) -> Literal["unclosed", "trailing"] | None:
    """Whether a quoted value may have taken in the next pattern of a string.

    `"unclosed"` when the quote is never closed and a comma follows it,
    `"trailing"` when text other than a glob follows the closing quote (an
    unescaped quote inside the value, or a comma that should have ended this
    pattern read as part of the value).
    """
    start = len(value) - len(value.lstrip("*?"))
    if start == len(value) or value[start] not in "'\"":
        return None
    escaped = False
    for index in range(start + 1, len(value)):
        char = value[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == value[start]:
            return "trailing" if value[index + 1 :].strip("*?") else None
    return "unclosed" if "," in value[start:] else None


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
                        f"Invalid tool pattern: unexpected text after ')' in '{text}'."
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
