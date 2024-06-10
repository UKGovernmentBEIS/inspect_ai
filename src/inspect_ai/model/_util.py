from typing import Any, Literal, TypedDict

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

from ._chat_message import ChatMessage
from ._generate_config import GenerateConfig
from ._tool import ToolInfo


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


class ChatApiFunction(TypedDict, total=False):
    name: str
    """The name of the function to be called.

    Must be a-z, A-Z, 0-9, or contain underscores and dashes, with a maximum length
    of 64.
    """

    description: str
    """
    A description of what the function does, used by the model to choose when and
    how to call the function.
    """

    parameters: dict[str, object]
    """The parameters the functions accepts, described as a JSON Schema object.

    See the
    [guide](https://platform.openai.com/docs/guides/text-generation/function-calling)
    for examples, and the
    [JSON Schema reference](https://json-schema.org/understanding-json-schema/) for
    documentation about the format.

    Omitting `parameters` defines a function with an empty parameter list.
    """


class ChatApiTool(TypedDict, total=False):
    """Tool for use the model during generation."""

    type: Literal["function"]
    """Tool type (currently only function is supported)"""

    function: ChatApiFunction
    """Type information for function to be called"""


def chat_api_tool(tool: ToolInfo) -> ChatApiTool:
    """JSON schema definition for a tool to be called by the model.

    Both OpenAI and Mistral use JSON schema for their tool definition
    (others will likely follow suit).

    Args:
       tool (ToolInfo): Tool definition

    Returns:
       Name and JSON schema for tool parameters and return value.
    """
    # build params
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in tool.params:
        properties[param.name] = dict(
            type=param.type,
            description=param.description,
        )
        if not param.optional:
            required.append(param.name)

    # define tool
    return ChatApiTool(
        type="function",
        function=ChatApiFunction(
            name=tool.name,
            description=tool.description,
            parameters=dict(
                type="object",
                properties=properties,
                required=required,
            ),
        ),
    )


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
