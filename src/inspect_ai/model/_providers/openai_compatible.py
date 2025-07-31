import os
from logging import getLogger
from typing import Any, cast

from openai import (
    APIStatusError,
    AsyncOpenAI,
    BadRequestError,
    PermissionDeniedError,
    UnprocessableEntityError,
)
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion
from typing_extensions import override

from inspect_ai.model._openai import chat_choices_from_openai
from inspect_ai.model._providers.util.chatapi import (
    ChatAPIHandler,
    ChatAPIMessage,
    chat_api_messages_for_handler,
)
from inspect_ai.model._providers.util.hooks import HttpxHooks
from inspect_ai.model._providers.util.llama31 import Llama31Handler
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage, ChatMessageTool
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import ChatCompletionChoice, ModelOutput
from .._openai import (
    OpenAIAsyncHttpxClient,
    model_output_from_openai,
    openai_chat_messages,
    openai_chat_tool_choice,
    openai_chat_tools,
    openai_completion_params,
    openai_handle_bad_request,
    openai_media_filter,
    openai_should_retry,
)
from .util import environment_prerequisite_error, model_base_url

logger = getLogger(__name__)


class OpenAICompatibleAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        service: str | None = None,
        service_base_url: str | None = None,
        emulate_tools: bool = False,
        **model_args: Any,
    ) -> None:
        # extract service prefix from model name if not specified
        if service is None:
            parts = model_name.split("/")
            if len(parts) == 1:
                raise ValueError(
                    "openai-api model names must include a service prefix (e.g. 'openai-api/service/model')"
                )
            self.service = parts[0]
        else:
            self.service = service

        # compute api key
        service_env_name = self.service.upper().replace("-", "_")
        api_key_var = f"{service_env_name}_API_KEY"

        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[api_key_var],
            config=config,
        )

        # use service prefix to lookup api_key
        if not self.api_key:
            self.api_key = os.environ.get(api_key_var, None)
            if not self.api_key:
                raise environment_prerequisite_error(
                    self.service,
                    [api_key_var],
                )

        # use service prefix to lookup base_url
        if not self.base_url:
            base_url_var = f"{service_env_name}_BASE_URL"
            self.base_url = model_base_url(base_url, [base_url_var]) or service_base_url
            if not self.base_url:
                raise environment_prerequisite_error(
                    self.service,
                    [base_url_var],
                )

        # grab emulate_tools argument
        self.emulate_tools = emulate_tools

        # create async http client
        http_client = model_args.pop("http_client", OpenAIAsyncHttpxClient())
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            http_client=http_client,
            **model_args,
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
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # tool emulation if requested
        if self.emulate_tools:
            handler: ChatAPIHandler | None = OpenAICompatibleHandler(self.model_name)
        else:
            handler = None

        # resolve input
        if handler:
            input = chat_api_messages_for_handler(input, tools, handler)

        # allocate request_id (so we can see it from ModelCall)
        request_id = self._http_hooks.start_request()

        # setup request and response for ModelCall
        request: dict[str, Any] = {}
        response: dict[str, Any] = {}

        def model_call() -> ModelCall:
            return ModelCall.create(
                request=request,
                response=response,
                filter=openai_media_filter,
                time=self._http_hooks.end_request(request_id),
            )

        tools, tool_choice, config = self.resolve_tools(tools, tool_choice, config)

        # get completion params (slice off service from model name)
        completion_params = self.completion_params(
            config=config,
            tools=len(tools) > 0,
        )

        # prepare request (we do this so we can log the ModelCall)
        have_tools = (len(tools) > 0) and not self.emulate_tools
        request = dict(
            messages=await openai_chat_messages(input),
            tools=openai_chat_tools(tools) if have_tools else NOT_GIVEN,
            tool_choice=openai_chat_tool_choice(tool_choice)
            if have_tools
            else NOT_GIVEN,
            extra_headers={HttpxHooks.REQUEST_ID_HEADER: request_id},
            **completion_params,
        )

        try:
            # generate completion and save response for model call
            completion = await self._generate_completion(request, config)
            response = completion.model_dump()
            self.on_response(response)

            # get choices
            choices = self.chat_choices_from_completion(completion, tools)

            # if we have a handler, see if there are embedded tool calls we need to resolve
            if handler:
                choices = [
                    _resolve_chat_choice(choice, tools, handler) for choice in choices
                ]

            # return output
            return model_output_from_openai(completion, choices), model_call()

        except (BadRequestError, UnprocessableEntityError, PermissionDeniedError) as ex:
            return self.handle_bad_request(ex), model_call()

    def resolve_tools(
        self, tools: list[ToolInfo], tool_choice: ToolChoice, config: GenerateConfig
    ) -> tuple[list[ToolInfo], ToolChoice, GenerateConfig]:
        """Provides an opportunity for concrete classes to customize tool resolution."""
        return tools, tool_choice, config

    async def _generate_completion(
        self, request: dict[str, Any], config: GenerateConfig
    ) -> ChatCompletion:
        return cast(
            ChatCompletion, await self.client.chat.completions.create(**request)
        )

    def service_model_name(self) -> str:
        """Model name without any service prefix."""
        return self.model_name.replace(f"{self.service}/", "", 1)

    @override
    def should_retry(self, ex: BaseException) -> bool:
        return openai_should_retry(ex)

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections (could also use endpoint)."""
        return str(self.api_key)

    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        return openai_completion_params(
            model=self.service_model_name(),
            config=config,
            tools=tools,
        )

    def on_response(self, response: dict[str, Any]) -> None:
        """Hook for subclasses to do custom response handling."""
        pass

    def chat_choices_from_completion(
        self, completion: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        """Hook for subclasses to do custom chat choice processing."""
        return chat_choices_from_openai(completion, tools)

    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        """Hook for subclasses to do bad request handling"""
        return openai_handle_bad_request(self.service_model_name(), ex)


class OpenAICompatibleHandler(Llama31Handler):
    @override
    def tool_message(self, message: ChatMessageTool) -> ChatAPIMessage:
        """Construct a chat REST API message from a tool message."""
        # might be an error in which case we prepend 'Error'
        results = f"Error: {message.error.message}" if message.error else message.text

        # try to clearly spell out that this 'user' message is the response to a function call
        content = f"The '{message.function}' function was called. The results are:\n\n{results}"

        # return user message
        return {"role": "user", "content": content}


def _resolve_chat_choice(
    choice: ChatCompletionChoice, tools: list[ToolInfo], handler: ChatAPIHandler
) -> ChatCompletionChoice:
    if choice.message.tool_calls is None or len(choice.message.tool_calls) == 0:
        # see if we can resolve tool calls in the message body
        message = handler.parse_assistant_response(choice.message.text, tools)
        if message.tool_calls:
            return ChatCompletionChoice(
                message=message,
                stop_reason=choice.stop_reason,
                logprobs=choice.logprobs,
            )
        else:
            return choice
    else:
        return choice
