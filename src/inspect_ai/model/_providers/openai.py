import os
from logging import getLogger
from typing import Any, Literal

from openai import (
    AsyncAzureOpenAI,
    AsyncOpenAI,
    BadRequestError,
    RateLimitError,
    UnprocessableEntityError,
)
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion
from typing_extensions import override

from inspect_ai._util.deprecation import deprecation_warning
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai.model._openai import chat_choices_from_openai
from inspect_ai.model._providers.openai_responses import generate_responses
from inspect_ai.model._providers.util.hooks import HttpxHooks
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import ModelOutput
from .._openai import (
    OpenAIAsyncHttpxClient,
    is_codex,
    is_computer_use_preview,
    is_gpt,
    is_o1,
    is_o1_early,
    is_o3_mini,
    is_o_series,
    model_output_from_openai,
    openai_chat_messages,
    openai_chat_tool_choice,
    openai_chat_tools,
    openai_completion_params,
    openai_handle_bad_request,
    openai_media_filter,
    openai_should_retry,
)
from .._openai_responses import is_native_tool_configured
from .openai_o1 import generate_o1
from .util import environment_prerequisite_error, model_base_url

logger = getLogger(__name__)

OPENAI_API_KEY = "OPENAI_API_KEY"
AZURE_OPENAI_API_KEY = "AZURE_OPENAI_API_KEY"
AZUREAI_OPENAI_API_KEY = "AZUREAI_OPENAI_API_KEY"

# NOTE: If you are creating a new provider that is OpenAI compatible you should inherit from OpenAICompatibleAPI rather than OpenAPAPI.


class OpenAIAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        responses_api: bool | None = None,
        # Can't use the XxxDeprecatedArgs approach since this already has a **param
        # but responses_store is deprecated and should not be used.
        responses_store: Literal["auto"] | bool = "auto",
        service_tier: str | None = None,
        client_timeout: float | None = None,
        **model_args: Any,
    ) -> None:
        # extract azure service prefix from model name (other providers
        # that subclass from us like together expect to have the qualifier
        # in the model name e.g. google/gemma-2b-it)
        parts = model_name.split("/")
        if parts[0] == "azure" and len(parts) > 1:
            self.service: str | None = parts[0]
        else:
            self.service = None

        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[OPENAI_API_KEY, AZURE_OPENAI_API_KEY, AZUREAI_OPENAI_API_KEY],
            config=config,
        )

        # is this a model we use responses api by default for?
        responses_preferred = (
            self.is_o_series() and not self.is_o1_early()
        ) or self.is_codex()

        # resolve whether we are forcing the responses api
        self.responses_api = self.is_computer_use_preview() or (
            responses_api if responses_api is not None else responses_preferred
        )

        # resolve whether we are using the responses store
        if isinstance(responses_store, bool):
            deprecation_warning("`responses_store` is no longer supported.")

        # set service tier if specified
        self.service_tier = service_tier

        # bump up default client timeout to 15 minutes for service_tier=="flex"
        self.client_timeout = client_timeout or (
            900.0 if self.service_tier == "flex" else None
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
            if model_args.get("api_version") is not None:
                # use slightly complicated logic to allow for "api_version" to be removed
                api_version = model_args.pop("api_version")
            else:
                api_version = os.environ.get(
                    "AZUREAI_OPENAI_API_VERSION",
                    os.environ.get("OPENAI_API_VERSION", "2025-03-01-preview"),
                )

            self.client: AsyncAzureOpenAI | AsyncOpenAI = AsyncAzureOpenAI(
                api_key=self.api_key,
                api_version=api_version,
                azure_endpoint=base_url,
                http_client=http_client,
                timeout=client_timeout if client_timeout is not None else NOT_GIVEN,
                **model_args,
            )
        else:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=model_base_url(base_url, "OPENAI_BASE_URL"),
                http_client=http_client,
                timeout=client_timeout if client_timeout is not None else NOT_GIVEN,
                **model_args,
            )

        # create time tracker
        self._http_hooks = HttpxHooks(self.client._client)

    def is_azure(self) -> bool:
        return self.service == "azure"

    def is_o_series(self) -> bool:
        return is_o_series(self.service_model_name())

    def is_o1(self) -> bool:
        return is_o1(self.service_model_name())

    def is_o1_early(self) -> bool:
        return is_o1_early(self.service_model_name())

    def is_o3_mini(self) -> bool:
        return is_o3_mini(self.service_model_name())

    def is_computer_use_preview(self) -> bool:
        return is_computer_use_preview(self.service_model_name())

    def is_codex(self) -> bool:
        return is_codex(self.service_model_name())

    def is_gpt(self) -> bool:
        return is_gpt(self.service_model_name())

    @override
    async def aclose(self) -> None:
        await self.client.close()

    @override
    def emulate_reasoning_history(self) -> bool:
        return not self.responses_api

    @override
    def tool_result_images(self) -> bool:
        # o1-pro, o1, and computer_use_preview support image inputs
        if self.is_computer_use_preview():
            return True
        elif self.is_o_series():
            if self.is_o1_early():
                return False
            elif self.is_o3_mini():
                return False
            else:
                return True
        else:
            return False

    @override
    def disable_computer_screenshot_truncation(self) -> bool:
        # Because ComputerCallOutput has a required output field of type
        # ResponseComputerToolCallOutputScreenshot, we must have an image in
        # order to provide a valid tool call response. Therefore, we cannot
        # support image truncation.
        return True

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # short-circuit to call o1- models that are text only
        if self.is_o1_early():
            return await generate_o1(
                client=self.client,
                input=input,
                tools=tools,
                **self.completion_params(config, False),
            )
        elif self.responses_api or is_native_tool_configured(
            tools, self.model_name, config
        ):
            return await generate_responses(
                client=self.client,
                http_hooks=self._http_hooks,
                model_name=self.service_model_name(),
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                config=config,
                service_tier=self.service_tier,
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
        if "vision" in self.service_model_name():
            if isinstance(config.max_tokens, int):
                config.max_tokens = max(config.max_tokens, OPENAI_IMAGE_DEFAULT_TOKENS)
            else:
                config.max_tokens = OPENAI_IMAGE_DEFAULT_TOKENS

        # determine system role
        # o1-mini does not support developer or system messages
        # (see Dec 17, 2024 changelog: https://platform.openai.com/docs/changelog)
        if self.is_o1_early():
            system_role: Literal["user", "system", "developer"] = "user"
        # other o-series models use 'developer' rather than 'system' messages
        # https://platform.openai.com/docs/guides/reasoning#advice-on-prompting
        elif self.is_o_series():
            system_role = "developer"
        else:
            system_role = "system"

        # prepare request (we do this so we can log the ModelCall)
        request = dict(
            messages=await openai_chat_messages(input, system_role),
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

            # return output and call
            choices = chat_choices_from_openai(completion, tools)
            return model_output_from_openai(completion, choices), model_call()
        except (BadRequestError, UnprocessableEntityError) as e:
            return openai_handle_bad_request(self.service_model_name(), e), model_call()

    def service_model_name(self) -> str:
        """Model name without any service prefix."""
        return self.model_name.replace(f"{self.service}/", "", 1)

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
        else:
            return openai_should_retry(ex)

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections (could also use endpoint)."""
        return str(self.api_key)

    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        # first call the default processing
        params = openai_completion_params(self.service_model_name(), config, tools)

        # add service_tier if specified
        if self.service_tier is not None:
            params["service_tier"] = self.service_tier

        # now tailor to current model
        if config.max_tokens is not None:
            if self.is_o_series():
                params["max_completion_tokens"] = config.max_tokens
                del params["max_tokens"]

        if config.temperature is not None:
            if self.is_o_series():
                warn_once(
                    logger,
                    "o series models do not support the 'temperature' parameter (temperature is always 1).",
                )
                del params["temperature"]

        # remove parallel_tool_calls if not supported
        if "parallel_tool_calls" in params.keys() and self.is_o_series():
            del params["parallel_tool_calls"]

        # remove reasoning_effort if not supported
        if "reasoning_effort" in params.keys() and (
            self.is_gpt() or self.is_o1_early()
        ):
            del params["reasoning_effort"]

        return params
