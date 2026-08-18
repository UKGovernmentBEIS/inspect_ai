from logging import getLogger
from typing import TYPE_CHECKING, Any, Callable, Literal

if TYPE_CHECKING:
    from inspect_ai.model._model import RetryDecision

import httpx
from tenacity import (
    RetryCallState,
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from inspect_ai._util.httpx import (
    httpx_classify_retry,
    httpx_should_retry,
    log_httpx_retry_attempt,
)
from inspect_ai._util.retry import report_http_retry
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
from inspect_ai.tool._tool_info import ToolInfo

from ..._chat_message import ChatMessage, ChatMessageUser

logger = getLogger(__name__)

ChatAPIMessage = dict[Literal["role", "content"], str]


class ChatAPIHandler:
    def __init__(self, model: str) -> None:
        self.model = model

    def input_with_tools(
        self, input: list[ChatMessage], tools: list[ToolInfo]
    ) -> list[ChatMessage]:
        return input

    def parse_assistant_response(
        self, response: str, tools: list[ToolInfo]
    ) -> ChatMessageAssistant:
        return ChatMessageAssistant(
            content=response, model=self.model, source="generate"
        )

    def assistant_message(self, message: ChatMessageAssistant) -> ChatAPIMessage:
        return {"role": "assistant", "content": message.text}

    def tool_message(self, message: ChatMessageTool) -> ChatAPIMessage:
        return {
            "role": "tool",
            "content": f"Error: {message.error.message}"
            if message.error
            else message.text,
        }


def chat_api_input(
    input: list[ChatMessage],
    tools: list[ToolInfo],
    handler: ChatAPIHandler,
) -> list[ChatAPIMessage]:
    # add tools to input
    if len(tools) > 0:
        input = handler.input_with_tools(input, tools)

    # resolve other messages
    return [chat_api_message(message, handler) for message in input]


def chat_api_message(message: ChatMessage, handler: ChatAPIHandler) -> ChatAPIMessage:
    if message.role == "assistant":
        return handler.assistant_message(message)
    elif message.role == "tool":
        return handler.tool_message(message)
    else:
        return dict(role=message.role, content=message.text)


def chat_api_messages_for_handler(
    input: list[ChatMessage],
    tools: list[ToolInfo],
    handler: ChatAPIHandler,
) -> list[ChatMessage]:
    # add tools to input
    if len(tools) > 0:
        input = handler.input_with_tools(input, tools)

    # resolve other messages
    return [chat_api_handler_message(message, handler) for message in input]


def chat_api_handler_message(
    message: ChatMessage, handler: ChatAPIHandler
) -> ChatMessage:
    if message.role == "assistant":
        return ChatMessageAssistant(
            content=handler.assistant_message(message)["content"]
        )
    elif message.role == "tool":
        tool_message = handler.tool_message(message)
        if tool_message["role"] == "tool":
            return ChatMessageTool(content=tool_message["content"])
        elif tool_message["role"] == "user":
            return ChatMessageUser(content=tool_message["content"])
        else:
            return message
    else:
        return message


def _log_and_report_before_sleep(
    model_name: str,
) -> Callable[[RetryCallState], None]:
    """Build a tenacity `before_sleep` that logs AND reports the retry.

    Reporting from `before_sleep` (rather than the retry predicate) ensures
    we fire `report_http_retry` exactly once per actual retry: the predicate
    is called even on the final stopped attempt, but `before_sleep` only fires
    when tenacity will actually wait and try again. This matters because the
    chatapi-internal retry's logical 429 episode would otherwise inflate the
    global `_http_retries_count` (predicate runs on every attempt) plus the
    outer `Model.should_retry` adds its own report when the wrapping
    `RetryError` bubbles up.

    A chatapi-internal retry that succeeds on attempt 2 still reports here,
    so the controller and stats see the rate-limit signal even when the
    eventual call returns success.
    """
    log = log_httpx_retry_attempt(model_name)

    def cb(retry_state: RetryCallState) -> None:
        log(retry_state)
        if retry_state.outcome is None:
            return
        ex = retry_state.outcome.exception()
        if ex is None:
            return
        decision = httpx_classify_retry(ex)
        if decision is not None and decision.retry:
            report_http_retry(kind=decision.kind, retry_after=decision.retry_after)

    return cb


async def chat_api_request(
    client: httpx.AsyncClient,
    model_name: str,
    url: str,
    headers: dict[str, Any],
    json: Any,
) -> Any:
    # define call w/ retry policy
    @retry(
        wait=wait_exponential_jitter(),
        stop=(stop_after_attempt(2)),
        retry=retry_if_exception(httpx_should_retry),
        before_sleep=_log_and_report_before_sleep(model_name),
    )
    async def call_api() -> Any:
        response = await client.post(url=url, headers=headers, json=json)
        response.raise_for_status()
        return response.json()

    # make the call
    return await call_api()


# When calling chat_api_request() we use tenacity as the retry wrapper, so
# checking for rate limit errors needs to punch through the RetryError and
# look at its `__cause__`. we've observed Cloudflare giving transient 500
# status as well as a ReadTimeout, so we count these as rate limit errors
def should_retry_chat_api_error(ex: BaseException) -> bool:
    return classify_chat_api_error(ex) is not None


def classify_chat_api_error(ex: BaseException) -> "RetryDecision | None":
    """Classify a chat-API exception (wrapped in tenacity RetryError) for adaptive concurrency.

    The chatapi helper retries httpx errors at a layer below this one, so by
    the time we see the exception it's been wrapped in `tenacity.RetryError`
    and the actual cause lives in `__cause__`.
    """
    if not isinstance(ex, RetryError):
        return None

    cause = ex.__cause__
    if cause is None:
        raise RuntimeError(f"Tenacity RetryError with no __cause__: {ex}")

    return httpx_classify_retry(cause)
