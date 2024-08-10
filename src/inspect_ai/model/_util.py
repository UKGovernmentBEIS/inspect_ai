import re
from typing import Any

import httpx
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

from ._chat_message import ChatMessage
from ._generate_config import GenerateConfig
from ._providers.util import parse_tool_call


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
