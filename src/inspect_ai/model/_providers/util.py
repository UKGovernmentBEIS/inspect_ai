import json
import os
from logging import getLogger
from typing import Any

from .._model_output import StopReason
from .._tool import ToolCall

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


def parse_tool_call(id: str, function: str, arguments: str) -> ToolCall:
    error: str | None = None
    arguments_dict: dict[str, Any] = {}
    try:
        arguments_dict = json.loads(arguments)
    except json.JSONDecodeError as ex:
        # define and log error
        error = f"Error parsing the following tool call arguments:\n{arguments}\nError details: {ex}"
        logger.info(error)

    # return ToolCall with error payload
    return ToolCall(
        id=id,
        function=function,
        arguments=arguments_dict,
        type="function",
        parse_error=error,
    )
