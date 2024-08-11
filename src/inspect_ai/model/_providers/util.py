import json
import os
import re
from logging import getLogger
from typing import Any

import httpx
import yaml
import yaml.parser
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from inspect_ai._util.constants import DEFAULT_MAX_RETRIES
from inspect_ai._util.retry import httpx_should_retry, log_retry_attempt
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
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


async def chat_api_request(
    client: httpx.AsyncClient,
    model_name: str,
    url: str,
    headers: dict[str, Any],
    json: Any,
    config: GenerateConfig,
) -> Any:
    # provide default max_retries
    max_retries = config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES

    # define call w/ retry policy
    @retry(
        wait=wait_exponential_jitter(),
        stop=(
            (stop_after_attempt(max_retries) | stop_after_delay(config.timeout))
            if config.timeout
            else stop_after_attempt(max_retries)
        ),
        retry=retry_if_exception(httpx_should_retry),
        before_sleep=log_retry_attempt(model_name),
    )
    async def call_api() -> Any:
        response = await client.post(url=url, headers=headers, json=json)
        response.raise_for_status()
        return response.json()

    # make the call
    return await call_api()


def chat_api_input(input: list[ChatMessage]) -> list[dict[str, str]]:
    """Prepare chat prompt data for sending in an HTTP POST request.

    Many chat APIs (e.g. Mistral and Cloudflare) take the OpenAI
    role/content data structure. This is a convenience function that
    takes the `input` to `generate()` and converts it into a JSON
    serializable object that conforms to this structure.

    Args:
        input (list[ChatMessage]): Input to generate from

    Returns:
       Dict that conforms to OpenAI role/content data structure.
    """
    return [dict(role=message.role, content=message.text) for message in input]


def llama31_chat_api_input(
    input: list[ChatMessage], tools: list[ToolInfo]
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if len(tools) > 0:
        messages.append(llama31_tools_message(tools))
    return messages + [
        dict(role=message.role, content=message.text) for message in input
    ]


# see https://docs.together.ai/docs/llama-3-function-calling
def llama31_tools_message(tools: list[ToolInfo]) -> dict[str, str]:
    tool_descriptions = "\n\n".join(
        [
            f"Use the '{tool.name}' tool to '{tool.description}':\n{tool.parameters.model_dump_json(exclude_none=True)}"
            for tool in tools
        ]
    )

    toolPrompt = f"""
You have access to the following functions:

{tool_descriptions}

If you choose to call a function ONLY reply in the following format with no prefix or suffix:

<function=example_function_name>{{\"example_name\": \"example_value\"}}</function>

Reminder:
- Function calls MUST follow the specified format, start with <function= and end with </function>
- Required parameters MUST be specified
- Only call one function at a time
- Put the entire function call reply on one line
- If there is no function call available, answer the question like normal with your current knowledge and do not tell the user about function calls
"""

    return {"role": "system", "content": toolPrompt}


def llama31_parse_tool_call(response: str, tools: list[ToolInfo]) -> ToolCall | None:
    function_regex = r"<function=(\w+)>(.*?)</function>"
    match = re.search(function_regex, response)
    if match:
        function_name, args_string = match.groups()
        return parse_tool_call(function_name, function_name, args_string, tools)
    else:
        return None


# When calling chat_api_request() we use tenacity as the retry wrapper, so
# checking for rate limit errors needs to punch through the RetryError and
# look at its `__cause__`. we've observed Cloudflare giving transient 500
# status as well as a ReadTimeout, so we count these as rate limit errors
def is_chat_api_rate_limit(ex: BaseException) -> bool:
    return isinstance(ex, RetryError) and (
        (
            isinstance(ex.__cause__, httpx.HTTPStatusError)
            and (
                ex.__cause__.response.status_code == 429
                or ex.__cause__.response.status_code == 500
            )
        )
        or isinstance(ex.__cause__, httpx.ReadTimeout)
    )
