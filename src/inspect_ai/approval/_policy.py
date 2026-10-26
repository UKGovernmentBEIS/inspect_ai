import fnmatch
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Generator, NamedTuple, cast

from pydantic import BaseModel, Field, model_validator
from pydantic_core import to_jsonable_python

from inspect_ai._util.config import read_config_object
from inspect_ai._util.file import exists, local_path
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
    """Tools to use this approver for: function names or globs (a name with no glob characters also matches longer names it begins)."""

    arguments: dict[str, str] | None = None
    """Arguments the call must have: each argument name maps to a glob matched against the argument's value (a string as is, any other value as JSON)."""

    def __post_init__(self) -> None:
        tool_call_matcher(self.tools, self.arguments)


# the legacy form `name(arg='value'`, optionally closed with `)`
_LEGACY_TOOL_PATTERN = re.compile(r"([^\s(),'*?\[\]]+)\((\w+)='([^']*)'(\))?")

# characters that make a function name a glob rather than a prefix
_GLOB_CHARS = re.compile(r"[*?\[]")


class _ToolPattern(NamedTuple):
    function: str
    """Glob for the function name."""

    arguments: dict[str, str]
    """Globs for argument values, by argument name."""

    legacy: bool
    """Whether this is the legacy form, which matches string values only."""

    only_arguments: bool
    """Whether the call may have no other arguments."""


def tool_call_matcher(
    tools: str | list[str], arguments: dict[str, str] | None = None
) -> Callable[[ToolCall], bool]:
    """Compile the `tools` and `arguments` of a policy into a tool call predicate.

    `tools` takes function names or globs, as one string, a comma-separated
    string, or a list. A name with no glob characters (`*`, `?`, `[`) is
    prefix matched; a glob must match the whole name. A call
    matches when its function matches one of them and every entry of
    `arguments` names an argument of the call whose value matches its glob.

    The legacy form `name(arg='value'` (optionally closed with `)`) has these
    limitations: the function name must match exactly and cannot contain glob
    characters; only string values match; `value` is a glob over the whole
    value; matching is case-sensitive on every platform; path separators are
    literal (on Windows a slash and a backslash differ); and with `)` the call
    may have no other arguments. Any other `tools` entry containing `(`,
    including an unclosed value, is refused.

    Other function names are matched with `fnmatch.fnmatch`, so they ignore
    case on Windows. Argument values are always case-sensitive.

    Raises:
        ValueError: If `tools` or `arguments` cannot be compiled.
    """
    if arguments is not None and not all(
        isinstance(name, str) and isinstance(glob, str)
        for name, glob in arguments.items()
    ):
        raise ValueError(
            f"Invalid policy arguments {arguments!r}: each argument name must map to a string glob."
        )
    specs = [tools] if isinstance(tools, str) else tools
    patterns: list[_ToolPattern] = []
    for spec in specs:
        if "(" in spec:
            legacy = _LEGACY_TOOL_PATTERN.fullmatch(spec.strip())
            if legacy is None:
                raise ValueError(
                    f"Invalid tool pattern {spec!r}: 'tools' takes function names or globs. "
                    + "Match arguments with the policy's 'arguments' field, for example "
                    + "tools='computer', arguments={'action': 'key*'}."
                )
            if arguments:
                raise ValueError(
                    f"Invalid tool pattern {spec!r}: the form name(arg='value' cannot be "
                    + "combined with 'arguments'. Put the argument in 'arguments' instead."
                )
            function, name, glob, closed = legacy.groups()
            patterns.append(
                _ToolPattern(
                    function=function,
                    arguments={name: glob},
                    legacy=True,
                    only_arguments=closed is not None,
                )
            )
        else:
            for function in spec.split(","):
                function = function.strip()
                if function:
                    glob = function if _GLOB_CHARS.search(function) else f"{function}*"
                    patterns.append(
                        _ToolPattern(
                            function=glob,
                            arguments=arguments or {},
                            legacy=False,
                            only_arguments=False,
                        )
                    )

    def matches(call: ToolCall) -> bool:
        return any(
            (
                call.function == pattern.function
                if pattern.legacy
                else fnmatch.fnmatch(call.function, pattern.function)
            )
            and all(
                name in call.arguments
                and (not pattern.legacy or isinstance(call.arguments[name], str))
                and fnmatch.fnmatchcase(_argument_text(call.arguments[name]), glob)
                for name, glob in pattern.arguments.items()
            )
            and (
                not pattern.only_arguments
                or call.arguments.keys() == pattern.arguments.keys()
            )
            for pattern in patterns
        )

    return matches


def _argument_text(value: Any) -> str:
    """Text an argument glob is matched against: a string as is, else its JSON.

    Values the tool call parser can produce beyond JSON (dates, bytes, sets) are
    converted as Pydantic serializes them; any other type raises.
    """
    if isinstance(value, str):
        return value
    return json.dumps(_jsonable(value), ensure_ascii=False)


def _jsonable(value: Any) -> Any:
    """Convert only the non-JSON parts of `value` with Pydantic.

    JSON values are left to `json.dumps`, since Pydantic rejects some it
    accepts (e.g. a lone surrogate in an object key). Raises `ValueError` if
    a converted object key equals another key, since one entry would be lost.
    """
    if value is None or isinstance(value, str | int | float):
        return value
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        converted: dict[Any, Any] = {}
        for key, item in value.items():
            if not (key is None or isinstance(key, str | int | float)):
                key = to_jsonable_python(key)
            if key in converted:
                raise ValueError(
                    f"Tool call argument has two object keys that both convert to {key!r}."
                )
            converted[key] = _jsonable(item)
        return converted
    return to_jsonable_python(value)


def policy_approver(policies: str | list[ApprovalPolicy]) -> Approver:
    # if policies is a str, it is a config file or an approver
    if isinstance(policies, str):
        policies = approval_policies_from_config(policies)

    # compile policy into approvers and matchers
    policy_matchers = [
        (tool_call_matcher(policy.tools, policy.arguments), policy.approver)
        for policy in policies
    ]

    # generator for policies that match a tool_call
    def tool_approvers(tool_call: ToolCall) -> Generator[Approver, None, None]:
        for matches, approver in policy_matchers:
            if matches(tool_call):
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


class ApproverPolicyConfig(BaseModel):
    """
    Configuration format for approver policies.

    For example, here is a configuration in YAML:

    ```yaml
    approvers:
      - name: human
        tools: web_browser*, bash, pyhton
        choices: [approve, reject]

      - name: human
        tools: computer
        arguments: {action: key}

      - name: auto
        tools: *
        decision: approve
    ```
    """

    name: str
    tools: str | list[str]
    arguments: dict[str, str] | None = Field(default=None)
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "extra": "allow",
    }

    @model_validator(mode="before")
    @classmethod
    def collect_unknown_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        known_fields = set(["name", "tools", "arguments", "params"])
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
        name: str,
        tools: str | list[str],
        arguments: dict[str, str] | None,
        params: dict[str, Any] = {},
    ) -> ApprovalPolicy:
        approver = cast(Approver, create_registry_object("approver", name, params))
        return ApprovalPolicy(approver, tools, arguments)

    # map config -> policy
    def policy_from_config(config: ApproverPolicyConfig) -> ApprovalPolicy:
        return create_approval_policy(
            config.name, config.tools, config.arguments, config.params
        )

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
                name=name, tools=policy.tools, arguments=policy.arguments, params=params
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
