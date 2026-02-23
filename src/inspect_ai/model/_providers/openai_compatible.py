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
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from typing_extensions import override

from inspect_ai.log._samples import set_active_model_event_call
from inspect_ai.model._openai import chat_choices_from_openai
from inspect_ai.model._openai_responses import ResponsesModelInfo
from inspect_ai.model._providers.openai_responses import generate_responses
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
from .._model_call import ModelCall, as_error_response
from .._model_output import ChatCompletionChoice, ModelOutput
from .._openai import (
    OpenAIAsyncHttpxClient,
    messages_to_openai,
    model_output_from_openai,
    needs_max_completion_tokens,
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
        responses_api: bool | None = None,
        responses_store: bool | None = None,
        stream: bool | None = None,
        strict_tools: bool = True,
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

        # grab arguments
        self.emulate_tools = emulate_tools
        self.responses_api = responses_api
        self.responses_store = responses_store
        if self.emulate_tools and self.responses_api:
            raise ValueError(
                "emulate_tools is not compatible with using the responses_api"
            )
        self.stream = False if stream is None else stream
        self.strict_tools = strict_tools

        # store http_client and model_args for reinitialization
        self.http_client = model_args.pop("http_client", OpenAIAsyncHttpxClient())
        self.model_args = model_args

        # create client
        self.initialize()

    def _create_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            http_client=self.http_client,
            **self.model_args,
        )

    def initialize(self) -> None:
        super().initialize()
        self.client = self._create_client()
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
        tools, tool_choice, config = self.resolve_tools(tools, tool_choice, config)

        if self.responses_api:
            return await generate_responses(
                client=self.client,
                http_hooks=self._http_hooks,
                model_name=self.service_model_name(),
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
                background=None,
                service_tier=None,
                prompt_cache_key=NOT_GIVEN,
                prompt_cache_retention=NOT_GIVEN,
                safety_identifier=NOT_GIVEN,
                responses_store=self.responses_store,
                model_info=ModelInfo(),
                batcher=None,
                handle_bad_request=self.handle_bad_request,
            )

        else:
            # tool emulation if requested
            if self.emulate_tools:
                handler: ChatAPIHandler | None = OpenAICompatibleHandler(
                    self.model_name
                )
            else:
                handler = None

            # resolve input
            if handler:
                input = chat_api_messages_for_handler(input, tools, handler)

            # allocate request_id (so we can see it from ModelCall)
            request_id = self._http_hooks.start_request()

            # get completion params (slice off service from model name)
            completion_params = self.completion_params(
                config=config,
                tools=len(tools) > 0,
            )

            # prepare request (we do this so we can log the ModelCall)
            have_tools = (len(tools) > 0) and not self.emulate_tools
            request = dict(
                messages=await self.messages_to_openai(input),
                tools=self.tools_to_openai(tools) if have_tools else NOT_GIVEN,
                tool_choice=openai_chat_tool_choice(tool_choice)
                if have_tools
                else NOT_GIVEN,
                extra_headers={HttpxHooks.REQUEST_ID_HEADER: request_id}
                | (config.extra_headers or {}),
                **completion_params,
            )

            model_call = set_active_model_event_call(request, openai_media_filter)

            try:
                # generate completion and save response for model call
                completion = await self._generate_completion(request, config)
                response = completion.model_dump()
                model_call.set_response(
                    response, self._http_hooks.end_request(request_id)
                )
                self.on_response(response)

                # get choices
                choices = self.chat_choices_from_completion(completion, tools)

                # if we have a handler, see if there are embedded tool calls we need to resolve
                if handler:
                    choices = [
                        _resolve_chat_choice(choice, tools, handler)
                        for choice in choices
                    ]

                # return output
                return model_output_from_openai(completion, choices), model_call

            except (
                BadRequestError,
                UnprocessableEntityError,
                PermissionDeniedError,
            ) as ex:
                model_call.set_response(
                    as_error_response(ex.body), self._http_hooks.end_request(request_id)
                )
                return self.handle_bad_request(ex), model_call

    def resolve_tools(
        self, tools: list[ToolInfo], tool_choice: ToolChoice, config: GenerateConfig
    ) -> tuple[list[ToolInfo], ToolChoice, GenerateConfig]:
        """Provides an opportunity for concrete classes to customize tool resolution."""
        return tools, tool_choice, config

    async def _generate_completion(
        self, request: dict[str, Any], config: GenerateConfig
    ) -> ChatCompletion:
        if self.stream or self.should_stream(config):
            async with self.client.chat.completions.stream(**request) as stream:
                return await stream.get_final_completion()
        else:
            return cast(
                ChatCompletion, await self.client.chat.completions.create(**request)
            )

    def service_model_name(self) -> str:
        """Model name without any service prefix."""
        return self.model_name.replace(f"{self.service}/", "", 1)

    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        Returns a normalized model name suitable for looking up model info
        (context window, etc.) in the model database. Subclasses may override
        to normalize provider-specific model names to a common format
        (e.g. HuggingFace-style names for open models).
        """
        return self.service_model_name()

    @override
    def should_retry(self, ex: BaseException) -> bool:
        return openai_should_retry(ex)

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections (could also use endpoint)."""
        return str(self.api_key)

    @override
    def is_auth_failure(self, ex: Exception) -> bool:
        if isinstance(ex, APIStatusError):
            return ex.status_code == 401
        return False

    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params = openai_completion_params(
            model=self.service_model_name(),
            config=config,
            tools=tools,
        )

        if (
            needs_max_completion_tokens(self.service_model_name())
            and "max_tokens" in params
        ):
            params["max_completion_tokens"] = params.pop("max_tokens")

        return params

    def on_response(self, response: dict[str, Any]) -> None:
        """Hook for subclasses to do custom response handling."""
        pass

    def should_stream(self, config: GenerateConfig) -> bool:
        return False

    def tools_to_openai(self, tools: list[ToolInfo]) -> list[ChatCompletionToolParam]:
        # some inference platforms (e.g. hf-inference) require strict=True
        openai_tools = openai_chat_tools(tools)
        for tool in openai_tools:
            tool["function"]["strict"] = self.strict_tools
        return openai_tools

    async def messages_to_openai(
        self, input: list[ChatMessage]
    ) -> list[ChatCompletionMessageParam]:
        return await messages_to_openai(input)

    def chat_choices_from_completion(
        self, completion: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        """Hook for subclasses to do custom chat choice processing."""
        return chat_choices_from_openai(completion, tools)

    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        """Hook for subclasses to do bad request handling"""
        # Handle DeepInfra input length errors
        if ex.status_code == 400:
            content = str(ex)
            if "input length" in content:
                return ModelOutput.from_content(
                    self.model_name, content=content, stop_reason="model_length"
                )

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


class ModelInfo(ResponsesModelInfo):
    def has_reasoning_options(self) -> bool:
        return True

    def is_gpt(self) -> bool:
        return False

    def is_gpt_5_plus(self) -> bool:
        return False

    def is_gpt_5(self) -> bool:
        return False

    def is_gpt_5_pro(self) -> bool:
        return False

    def is_gpt_5_chat(self) -> bool:
        return False

    def is_o_series(self) -> bool:
        return False

    def is_o1(self) -> bool:
        return False

    def is_o1_early(self) -> bool:
        return False

    def is_o3_mini(self) -> bool:
        return False

    def is_deep_research(self) -> bool:
        return False

    def is_computer_use_preview(self) -> bool:
        return False

    def is_codex(self) -> bool:
        return False
