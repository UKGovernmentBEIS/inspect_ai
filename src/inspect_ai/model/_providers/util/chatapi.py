from logging import getLogger
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
from inspect_ai.tool._tool_info import ToolInfo

from ..._chat_message import ChatMessage
from ..._generate_config import GenerateConfig
from .tools import ChatApiMessage, ChatAPIToolsHandler, chat_api_tools_handler

logger = getLogger(__name__)


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


def chat_api_input(
    input: list[ChatMessage], tools: list[ToolInfo], model: str
) -> list[ChatApiMessage]:
    # get tools handler
    tools_handler = chat_api_tools_handler(model)

    # add tools to input
    input = tools_handler.input_with_tools(input, tools)

    # resolve other messages
    return [chat_api_message(message, tools_handler) for message in input]


def chat_api_message(
    message: ChatMessage, tools_handler: ChatAPIToolsHandler
) -> ChatApiMessage:
    if message.role == "assistant":
        return tools_handler.chat_api_assistant_message(message)
    elif message.role == "tool":
        return tools_handler.chat_api_tool_message(message)
    else:
        return dict(role=message.role, content=message.text)


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
