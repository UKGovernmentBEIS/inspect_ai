import json
import os
from copy import copy
from typing import Any, Dict, Iterable, List, Optional

import httpx
from groq import (
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
)
from groq.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai._util.constants import (
    BASE_64_DATA_REMOVED,
    DEFAULT_MAX_TOKENS,
)
from inspect_ai._util.content import Content, ContentReasoning, ContentText
from inspect_ai._util.http import is_retryable_http_status
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.url import is_http_url
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo

from .._call_tools import parse_tool_call
from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    as_stop_reason,
)
from .util import (
    environment_prerequisite_error,
    model_base_url,
)
from .util.hooks import HttpxHooks

GROQ_API_KEY = "GROQ_API_KEY"


class GroqAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[GROQ_API_KEY],
            config=config,
        )

        if not self.api_key:
            self.api_key = os.environ.get(GROQ_API_KEY)
        if not self.api_key:
            raise environment_prerequisite_error("Groq", GROQ_API_KEY)

        self.client = AsyncGroq(
            api_key=self.api_key,
            base_url=model_base_url(base_url, "GROQ_BASE_URL"),
            **model_args,
            http_client=httpx.AsyncClient(limits=httpx.Limits(max_connections=None)),
        )

        # create time tracker
        self._http_hooks = HttpxHooks(self.client._client)

    @override
    async def aclose(self) -> None:
        await self.client.close()

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput | Exception, ModelCall]:
        # allocate request_id (so we can see it from ModelCall)
        request_id = self._http_hooks.start_request()

        # setup request and response for ModelCall
        request: dict[str, Any] = {}
        response: dict[str, Any] = {}

        def model_call() -> ModelCall:
            return ModelCall.create(
                request=request,
                response=response,
                filter=model_call_filter,
                time=self._http_hooks.end_request(request_id),
            )

        messages = await as_groq_chat_messages(input)

        params = self.completion_params(config)
        if tools:
            params["tools"] = chat_tools(tools)
            params["tool_choice"] = (
                chat_tool_choice(tool_choice) if tool_choice else "auto"
            )
            if config.parallel_tool_calls is not None:
                params["parallel_tool_calls"] = config.parallel_tool_calls

        request = dict(
            messages=messages,
            model=self.model_name,
            extra_headers={HttpxHooks.REQUEST_ID_HEADER: request_id},
            **params,
        )

        try:
            completion: ChatCompletion = await self.client.chat.completions.create(
                **request,
            )

            response = completion.model_dump()

            # extract metadata
            metadata: dict[str, Any] = {
                "id": completion.id,
                "system_fingerprint": completion.system_fingerprint,
                "created": completion.created,
            }
            if completion.usage:
                metadata = metadata | {
                    "queue_time": completion.usage.queue_time,
                    "prompt_time": completion.usage.prompt_time,
                    "completion_time": completion.usage.completion_time,
                    "total_time": completion.usage.total_time,
                }
            if completion.choices[0].message.executed_tools:
                metadata["executed_tools"] = [
                    tool.model_dump()
                    for tool in completion.choices[0].message.executed_tools
                ]

            # extract output
            choices = self._chat_choices_from_response(completion, tools)
            output = ModelOutput(
                model=completion.model,
                choices=choices,
                usage=(
                    ModelUsage(
                        input_tokens=completion.usage.prompt_tokens,
                        output_tokens=completion.usage.completion_tokens,
                        total_tokens=completion.usage.total_tokens,
                    )
                    if completion.usage
                    else None
                ),
                metadata=metadata,
            )

            # return
            return output, model_call()
        except APIStatusError as ex:
            return self.handle_bad_request(ex), model_call()

    def completion_params(self, config: GenerateConfig) -> Dict[str, Any]:
        params: dict[str, Any] = {}
        if config.temperature is not None:
            params["temperature"] = config.temperature
        if config.max_tokens is not None:
            params["max_tokens"] = config.max_tokens
        if config.top_p is not None:
            params["top_p"] = config.top_p
        if config.stop_seqs:
            params["stop"] = config.stop_seqs
        if config.presence_penalty is not None:
            params["presence_penalty"] = config.presence_penalty
        if config.frequency_penalty is not None:
            params["frequency_penalty"] = config.frequency_penalty
        if config.seed is not None:
            params["seed"] = config.seed
        if config.num_choices is not None:
            params["n"] = config.num_choices
        return params

    def _chat_choices_from_response(
        self, response: Any, tools: list[ToolInfo]
    ) -> List[ChatCompletionChoice]:
        choices = list(response.choices)
        choices.sort(key=lambda c: c.index)
        return [
            ChatCompletionChoice(
                message=chat_message_assistant(self.model_name, choice.message, tools),
                stop_reason=as_stop_reason(choice.finish_reason),
            )
            for choice in choices
        ]

    @override
    def should_retry(self, ex: Exception) -> bool:
        if isinstance(ex, APIStatusError):
            return is_retryable_http_status(ex.status_code)
        elif isinstance(ex, APITimeoutError):
            return True
        else:
            return False

    @override
    def connection_key(self) -> str:
        return str(self.api_key)

    @override
    def collapse_user_messages(self) -> bool:
        return False

    @override
    def collapse_assistant_messages(self) -> bool:
        return False

    @override
    def max_tokens(self) -> Optional[int]:
        return DEFAULT_MAX_TOKENS

    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        if ex.status_code == 400:
            # extract code and message
            content = ex.message
            code = ""
            if isinstance(ex.body, dict) and isinstance(
                ex.body.get("error", None), dict
            ):
                error = ex.body.get("error", {})
                content = str(error.get("message", content))
                code = error.get("code", code)

            if code == "context_length_exceeded":
                return ModelOutput.from_content(
                    model=self.model_name,
                    content=content,
                    stop_reason="model_length",
                )

        return ex


async def as_groq_chat_messages(
    messages: list[ChatMessage],
) -> list[ChatCompletionMessageParam]:
    return [await groq_chat_message(message) for message in messages]


async def groq_chat_message(message: ChatMessage) -> ChatCompletionMessageParam:
    if isinstance(message, ChatMessageSystem):
        return ChatCompletionSystemMessageParam(role="system", content=message.text)

    elif isinstance(message, ChatMessageUser):
        content: str | Iterable[ChatCompletionContentPartParam] = (
            message.content
            if isinstance(message.content, str)
            else [await as_chat_completion_part(content) for content in message.content]
        )
        return ChatCompletionUserMessageParam(role="user", content=content)

    elif isinstance(message, ChatMessageAssistant):
        return ChatCompletionAssistantMessageParam(
            role="assistant",
            content=message.text,
            tool_calls=[
                ChatCompletionMessageToolCallParam(
                    id=call.id,
                    type="function",
                    function={
                        "name": call.function,
                        "arguments": json.dumps(call.arguments),
                    },
                )
                for call in (message.tool_calls or [])
            ],
        )
    elif isinstance(message, ChatMessageTool):
        return ChatCompletionToolMessageParam(
            role="tool",
            content=message.text,
            tool_call_id=str(message.tool_call_id),
        )


async def as_chat_completion_part(
    content: Content,
) -> ChatCompletionContentPartParam:
    if content.type == "text":
        return ChatCompletionContentPartTextParam(type="text", text=content.text)
    elif content.type == "image":
        # API takes URL or base64 encoded file. If it's a remote file or data URL leave it alone, otherwise encode it
        image_url = content.image
        detail = content.detail

        if not is_http_url(image_url):
            image_url = await file_as_data_uri(image_url)

        return ChatCompletionContentPartImageParam(
            type="image_url",
            image_url=dict(url=image_url, detail=detail),
        )
    else:
        raise RuntimeError("Groq models do not support audio or video inputs.")


def chat_tools(tools: List[ToolInfo]) -> List[Dict[str, Any]]:
    return [
        {"type": "function", "function": tool.model_dump(exclude_none=True)}
        for tool in tools
    ]


def chat_tool_choice(tool_choice: ToolChoice) -> str | Dict[str, Any]:
    if isinstance(tool_choice, ToolFunction):
        return {"type": "function", "function": {"name": tool_choice.name}}
    elif tool_choice == "any":
        return "auto"
    else:
        return tool_choice


def chat_tool_calls(message: Any, tools: list[ToolInfo]) -> Optional[List[ToolCall]]:
    if hasattr(message, "tool_calls") and message.tool_calls:
        return [
            parse_tool_call(call.id, call.function.name, call.function.arguments, tools)
            for call in message.tool_calls
        ]
    return None


def chat_message_assistant(
    model: str, message: Any, tools: list[ToolInfo]
) -> ChatMessageAssistant:
    reasoning = getattr(message, "reasoning", None)
    if reasoning is not None:
        content: str | list[Content] = [
            ContentReasoning(reasoning=str(reasoning)),
            ContentText(text=message.content or ""),
        ]
    else:
        content = message.content or ""

    return ChatMessageAssistant(
        content=content,
        model=model,
        source="generate",
        tool_calls=chat_tool_calls(message, tools),
    )


def model_call_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    # remove base64 encoded images
    if key == "image_url" and isinstance(value, dict):
        value = copy(value)
        value.update(url=BASE_64_DATA_REMOVED)
    return value
