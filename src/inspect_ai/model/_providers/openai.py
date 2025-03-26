import os
import socket
from logging import getLogger
from typing import Any

import httpx
from openai import (
    DEFAULT_CONNECTION_LIMITS,
    DEFAULT_TIMEOUT,
    APIStatusError,
    APITimeoutError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    BadRequestError,
    RateLimitError,
)
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion
from typing_extensions import override

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.http import is_retryable_http_status
from inspect_ai._util.logger import warn_once
from inspect_ai.model._openai import chat_choices_from_openai
from inspect_ai.model._providers.openai_responses import generate_responses
from inspect_ai.model._providers.util.hooks import HttpxHooks
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import ChatCompletionChoice, ModelOutput, ModelUsage
from .._openai import (
    OpenAIResponseError,
    is_gpt,
    is_o1_mini,
    is_o1_preview,
    is_o1_pro,
    is_o_series,
    openai_chat_messages,
    openai_chat_tool_choice,
    openai_chat_tools,
    openai_handle_bad_request,
    openai_media_filter,
)
from .openai_o1 import generate_o1
from .util import (
    environment_prerequisite_error,
    model_base_url,
)

logger = getLogger(__name__)

OPENAI_API_KEY = "OPENAI_API_KEY"
AZURE_OPENAI_API_KEY = "AZURE_OPENAI_API_KEY"
AZUREAI_OPENAI_API_KEY = "AZUREAI_OPENAI_API_KEY"


class OpenAIAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        responses_api: bool | None = None,
        **model_args: Any,
    ) -> None:
        # extract azure service prefix from model name (other providers
        # that subclass from us like together expect to have the qualifier
        # in the model name e.g. google/gemma-2b-it)
        parts = model_name.split("/")
        if parts[0] == "azure" and len(parts) > 1:
            self.service: str | None = parts[0]
            model_name = "/".join(parts[1:])
        else:
            self.service = None

        # note whether we are forcing the responses_api
        self.responses_api = True if responses_api else False

        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[OPENAI_API_KEY, AZURE_OPENAI_API_KEY, AZUREAI_OPENAI_API_KEY],
            config=config,
        )

        # resolve api_key
        if not self.api_key:
            if self.service == "azure":
                self.api_key = os.environ.get(
                    AZUREAI_OPENAI_API_KEY, os.environ.get(AZURE_OPENAI_API_KEY, None)
                )
            else:
                self.api_key = os.environ.get(OPENAI_API_KEY, None)

            if not self.api_key:
                raise environment_prerequisite_error(
                    "OpenAI",
                    [
                        OPENAI_API_KEY,
                        AZUREAI_OPENAI_API_KEY,
                    ],
                )

        # create async http client
        http_client = OpenAIAsyncHttpxClient()

        # azure client
        if self.is_azure():
            # resolve base_url
            base_url = model_base_url(
                base_url,
                [
                    "AZUREAI_OPENAI_BASE_URL",
                    "AZURE_OPENAI_BASE_URL",
                    "AZURE_OPENAI_ENDPOINT",
                ],
            )
            if not base_url:
                raise PrerequisiteError(
                    "ERROR: You must provide a base URL when using OpenAI on Azure. Use the AZUREAI_OPENAI_BASE_URL "
                    + "environment variable or the --model-base-url CLI flag to set the base URL."
                )

            # resolve version
            api_version = os.environ.get(
                "AZUREAI_OPENAI_API_VERSION",
                os.environ.get("OPENAI_API_VERSION", "2025-02-01-preview"),
            )

            self.client: AsyncAzureOpenAI | AsyncOpenAI = AsyncAzureOpenAI(
                api_key=self.api_key,
                api_version=api_version,
                azure_endpoint=base_url,
                http_client=http_client,
                **model_args,
            )
        else:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=model_base_url(base_url, "OPENAI_BASE_URL"),
                http_client=http_client,
                **model_args,
            )

        # create time tracker
        self._http_hooks = HttpxHooks(self.client._client)

    def is_azure(self) -> bool:
        return self.service == "azure"

    def is_o_series(self) -> bool:
        return is_o_series(self.model_name)

    def is_o1_pro(self) -> bool:
        return is_o1_pro(self.model_name)

    def is_o1_mini(self) -> bool:
        return is_o1_mini(self.model_name)

    def is_o1_preview(self) -> bool:
        return is_o1_preview(self.model_name)

    def is_gpt(self) -> bool:
        return is_gpt(self.model_name)

    @override
    async def close(self) -> None:
        await self.client.close()

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # short-circuit to call o1- models that are text only
        if self.is_o1_preview() or self.is_o1_mini():
            return await generate_o1(
                client=self.client,
                input=input,
                tools=tools,
                **self.completion_params(config, False),
            )
        elif self.is_o1_pro() or self.responses_api:
            return await generate_responses(
                client=self.client,
                http_hooks=self._http_hooks,
                model_name=self.model_name,
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
            )

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

        # unlike text models, vision models require a max_tokens (and set it to a very low
        # default, see https://community.openai.com/t/gpt-4-vision-preview-finish-details/475911/10)
        OPENAI_IMAGE_DEFAULT_TOKENS = 4096
        if "vision" in self.model_name:
            if isinstance(config.max_tokens, int):
                config.max_tokens = max(config.max_tokens, OPENAI_IMAGE_DEFAULT_TOKENS)
            else:
                config.max_tokens = OPENAI_IMAGE_DEFAULT_TOKENS

        # prepare request (we do this so we can log the ModelCall)
        request = dict(
            messages=await openai_chat_messages(input, self.model_name),
            tools=openai_chat_tools(tools) if len(tools) > 0 else NOT_GIVEN,
            tool_choice=openai_chat_tool_choice(tool_choice)
            if len(tools) > 0
            else NOT_GIVEN,
            extra_headers={HttpxHooks.REQUEST_ID_HEADER: request_id},
            **self.completion_params(config, len(tools) > 0),
        )

        try:
            # generate completion
            completion: ChatCompletion = await self.client.chat.completions.create(
                **request
            )

            # save response for model_call
            response = completion.model_dump()
            self.on_response(response)

            # parse out choices
            choices = self._chat_choices_from_response(completion, tools)

            # return output and call
            return ModelOutput(
                model=completion.model,
                choices=choices,
                usage=(
                    ModelUsage(
                        input_tokens=completion.usage.prompt_tokens,
                        output_tokens=completion.usage.completion_tokens,
                        input_tokens_cache_read=(
                            completion.usage.prompt_tokens_details.cached_tokens
                            if completion.usage.prompt_tokens_details is not None
                            else None  # openai only have cache read stats/pricing.
                        ),
                        reasoning_tokens=(
                            completion.usage.completion_tokens_details.reasoning_tokens
                            if completion.usage.completion_tokens_details is not None
                            else None
                        ),
                        total_tokens=completion.usage.total_tokens,
                    )
                    if completion.usage
                    else None
                ),
            ), model_call()
        except BadRequestError as e:
            return self.handle_bad_request(e), model_call()

    def on_response(self, response: dict[str, Any]) -> None:
        pass

    def handle_bad_request(self, ex: BadRequestError) -> ModelOutput | Exception:
        return openai_handle_bad_request(self.model_name, ex)

    def _chat_choices_from_response(
        self, response: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        # adding this as a method so we can override from other classes (e.g together)
        return chat_choices_from_openai(response, tools)

    @override
    def should_retry(self, ex: Exception) -> bool:
        if isinstance(ex, RateLimitError):
            # Do not retry on these rate limit errors
            # The quota exceeded one is related to monthly account quotas.
            if "You exceeded your current quota" in ex.message:
                warn_once(logger, f"OpenAI quota exceeded, not retrying: {ex.message}")
                return False
            else:
                return True
        elif isinstance(ex, APIStatusError):
            return is_retryable_http_status(ex.status_code)
        elif isinstance(ex, OpenAIResponseError):
            return ex.code in ["rate_limit_exceeded", "server_error"]
        elif isinstance(ex, APITimeoutError):
            return True
        else:
            return False

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections (could also use endpoint)."""
        return str(self.api_key)

    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params: dict[str, Any] = dict(
            model=self.model_name,
        )
        if config.max_tokens is not None:
            if self.is_o_series():
                params["max_completion_tokens"] = config.max_tokens
            else:
                params["max_tokens"] = config.max_tokens
        if config.frequency_penalty is not None:
            params["frequency_penalty"] = config.frequency_penalty
        if config.stop_seqs is not None:
            params["stop"] = config.stop_seqs
        if config.presence_penalty is not None:
            params["presence_penalty"] = config.presence_penalty
        if config.logit_bias is not None:
            params["logit_bias"] = config.logit_bias
        if config.seed is not None:
            params["seed"] = config.seed
        if config.temperature is not None:
            if self.is_o_series():
                warn_once(
                    logger,
                    "o series models do not support the 'temperature' parameter (temperature is always 1).",
                )
            else:
                params["temperature"] = config.temperature
        # TogetherAPI requires temperature w/ num_choices
        elif config.num_choices is not None:
            params["temperature"] = 1
        if config.top_p is not None:
            params["top_p"] = config.top_p
        if config.num_choices is not None:
            params["n"] = config.num_choices
        if config.logprobs is not None:
            params["logprobs"] = config.logprobs
        if config.top_logprobs is not None:
            params["top_logprobs"] = config.top_logprobs
        if tools and config.parallel_tool_calls is not None and not self.is_o_series():
            params["parallel_tool_calls"] = config.parallel_tool_calls
        if (
            config.reasoning_effort is not None
            and not self.is_gpt()
            and not self.is_o1_mini()
            and not self.is_o1_preview()
        ):
            params["reasoning_effort"] = config.reasoning_effort
        if config.response_schema is not None:
            params["response_format"] = dict(
                type="json_schema",
                json_schema=dict(
                    name=config.response_schema.name,
                    schema=config.response_schema.json_schema.model_dump(
                        exclude_none=True
                    ),
                    description=config.response_schema.description,
                    strict=config.response_schema.strict,
                ),
            )

        return params


class OpenAIAsyncHttpxClient(httpx.AsyncClient):
    """Custom async client that deals better with long running Async requests.

    Based on Anthropic DefaultAsyncHttpClient implementation that they
    released along with Claude 3.7 as well as the OpenAI DefaultAsyncHttpxClient

    """

    def __init__(self, **kwargs: Any) -> None:
        # This is based on the openai DefaultAsyncHttpxClient:
        # https://github.com/openai/openai-python/commit/347363ed67a6a1611346427bb9ebe4becce53f7e
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        kwargs.setdefault("limits", DEFAULT_CONNECTION_LIMITS)
        kwargs.setdefault("follow_redirects", True)

        # This is based on the anthrpopic changes for claude 3.7:
        # https://github.com/anthropics/anthropic-sdk-python/commit/c5387e69e799f14e44006ea4e54fdf32f2f74393#diff-3acba71f89118b06b03f2ba9f782c49ceed5bb9f68d62727d929f1841b61d12bR1387-R1403

        # set socket options to deal with long running reasoning requests
        socket_options = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True),
            (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60),
            (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5),
        ]
        TCP_KEEPIDLE = getattr(socket, "TCP_KEEPIDLE", None)
        if TCP_KEEPIDLE is not None:
            socket_options.append((socket.IPPROTO_TCP, TCP_KEEPIDLE, 60))

        kwargs["transport"] = httpx.AsyncHTTPTransport(
            limits=DEFAULT_CONNECTION_LIMITS,
            socket_options=socket_options,
        )

        super().__init__(**kwargs)
