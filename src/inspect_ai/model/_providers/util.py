import json
import os
from logging import getLogger
from typing import Any

import yaml
import yaml.parser

from inspect_ai.tool import ToolCall, ToolInfo

from .._model_output import StopReason

logger = getLogger(__name__)


def as_stop_reason(reason: str | None) -> StopReason:
    """Encode common reason strings into standard StopReason."""
    match reason:
        case "stop" | "eos":
            return "stop"
        case "length" | "content_filter":
            return reason
        case "model_length":
            return "length"
        case "tool_calls" | "function_call":
            return "tool_calls"
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


def parse_tool_call(
    id: str, function: str, arguments: str, tools: list[ToolInfo]
) -> ToolCall:
    error: str | None = None
    arguments_dict: dict[str, Any] = {}

    def report_parse_error(ex: Exception) -> None:
        nonlocal error
        error = f"Error parsing the following tool call arguments:\n\n{arguments}\n\nError details: {ex}"
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
            (tool for tool in tools if tool.name == function and len(tool.params) > 0),
            None,
        )
        if tool_info:
            try:
                value = yaml.safe_load(arguments)
                arguments_dict[tool_info.params[0].name] = value
            except yaml.parser.ParserError as ex:
                report_parse_error(ex)

    # return ToolCall with error payload
    return ToolCall(
        id=id,
        function=function,
        arguments=arguments_dict,
        type="function",
        parse_error=error,
    )
