import json
import os
from logging import getLogger
from typing import Any

import yaml

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo

from ..._model_output import StopReason

logger = getLogger(__name__)


def as_stop_reason(reason: str | None) -> StopReason:
    """Encode common reason strings into standard StopReason."""
    match reason:
        case "stop" | "eos":
            return "stop"
        case "length":
            return "max_tokens"
        case "tool_calls" | "function_call":
            return "tool_calls"
        case "content_filter" | "model_length" | "max_tokens":
            return reason
        case _:
            return "unknown"


def model_base_url(base_url: str | None, env_vars: str | list[str]) -> str | None:
    if base_url:
        return base_url

    if isinstance(env_vars, str):
        env_vars = [env_vars]

    for env_var in env_vars:
        base_url = os.getenv(env_var, None)
        if base_url:
            return base_url

    return os.getenv("INSPECT_EVAL_MODEL_BASE_URL", None)


def tool_parse_error_message(arguments: str, ex: Exception) -> str:
    return f"Error parsing the following tool call arguments:\n\n{arguments}\n\nError details: {ex}"


def parse_tool_call(
    id: str, function: str, arguments: str, tools: list[ToolInfo]
) -> ToolCall:
    error: str | None = None
    arguments_dict: dict[str, Any] = {}

    def report_parse_error(ex: Exception) -> None:
        nonlocal error
        error = tool_parse_error_message(arguments, ex)
        logger.info(error)

    # if the arguments is a dict, then handle it with a plain json.loads
    arguments = arguments.strip()
    if arguments.startswith("{"):
        try:
            arguments_dict = json.loads(arguments)
        except json.JSONDecodeError as ex:
            report_parse_error(ex)

    # otherwise parse it as yaml (which will pickup unquoted strings, numbers, and true/false)
    # and then create a dict that maps it to the first function argument
    else:
        tool_info = next(
            (
                tool
                for tool in tools
                if tool.name == function and len(tool.parameters.properties) > 0
            ),
            None,
        )
        if tool_info:
            param_names = list(tool_info.parameters.properties.keys())
            try:
                value = yaml.safe_load(arguments)
                arguments_dict[param_names[0]] = value
            except yaml.error.YAMLError:
                # If the yaml parser fails, we treat it as a string argument.
                arguments_dict[param_names[0]] = arguments

    # return ToolCall with error payload
    return ToolCall(
        id=id,
        function=function,
        arguments=arguments_dict,
        type="function",
        parse_error=error,
    )


def environment_prerequisite_error(
    client: str, env_vars: str | list[str]
) -> PrerequisiteError:
    def fmt(key: str) -> str:
        return f"[bold][blue]{key}[/blue][/bold]"

    env_vars = [env_vars] if isinstance(env_vars, str) else env_vars
    if len(env_vars) == 1:
        env_vars_list = fmt(env_vars[0])
    else:
        env_vars_list = (
            ", ".join([fmt(env_bar) for env_bar in env_vars[:-1]])
            + ("," if len(env_vars) > 2 else "")
            + " or "
            + fmt(env_vars[-1])
        )

    return PrerequisiteError(
        f"ERROR: Unable to initialise {client} client\n\nNo {env_vars_list} defined in the environment."
    )
