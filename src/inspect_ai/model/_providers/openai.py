import os
from logging import getLogger
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
from openai._types import NOT_GIVEN
from openai.types.chat import (
    ChatCompletion,
)
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_RETRIES
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai.model._openai import chat_choices_from_openai
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._image import image_url_filter
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .._openai import (
    is_gpt,
    is_o1_full,
    is_o1_mini,
    is_o1_preview,
    is_o3,
    is_o_series,
    openai_chat_messages,
    openai_chat_tool_choice,
    openai_chat_tools,
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
        **model_args: Any,
    ) -> None:
        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[OPENAI_API_KEY, AZURE_OPENAI_API_KEY, AZUREAI_OPENAI_API_KEY],
            config=config,
        )

        # extract any service prefix from model name
        parts = model_name.split("/")
        if len(parts) > 1:
            self.service: str | None = parts[0]
            model_name = "/".join(parts[1:])
        else:
            self.service = None

        # resolve api_key
        if not self.api_key:
            self.api_key = os.environ.get(
                AZUREAI_OPENAI_API_KEY, os.environ.get(AZURE_OPENAI_API_KEY, None)
            )
            # backward compatibility for when env vars determined service
            if self.api_key and (os.environ.get(OPENAI_API_KEY, None) is None):
                self.service = "azure"
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

            self.client: AsyncAzureOpenAI | AsyncOpenAI = AsyncAzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=base_url,
                azure_deployment=model_name,
                max_retries=(
                    config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES
                ),
                **model_args,
            )
        else:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=model_base_url(base_url, "OPENAI_BASE_URL"),
                max_retries=(
                    config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES
                ),
                **model_args,
            )

    def is_azure(self) -> bool:
        return self.service == "azure"

    def is_o_series(self) -> bool:
        return is_o_series(self.model_name)

    def is_o1_full(self) -> bool:
        return is_o1_full(self.model_name)

    def is_o1_mini(self) -> bool:
        return is_o1_mini(self.model_name)

    def is_o3(self) -> bool:
        return is_o3(self.model_name)

    def is_o1_preview(self) -> bool:
        return is_o1_preview(self.model_name)

    def is_gpt(self) -> bool:
        return is_gpt(self.model_name)

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

        # setup request and response for ModelCall
        request: dict[str, Any] = {}
        response: dict[str, Any] = {}

        def model_call() -> ModelCall:
            return ModelCall.create(
                request=request,
                response=response,
                filter=image_url_filter,
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
            **self.completion_params(config, len(tools) > 0),
        )

        try:
            # generate completion
            completion: ChatCompletion = await self.client.chat.completions.create(
                **request
            )

            # save response for model_call
            response = completion.model_dump()

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
                        total_tokens=completion.usage.total_tokens,
                    )
                    if completion.usage
                    else None
                ),
            ), model_call()
        except BadRequestError as e:
            return self.handle_bad_request(e), model_call()

    def _chat_choices_from_response(
        self, response: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        # adding this as a method so we can override from other classes (e.g together)
        return chat_choices_from_openai(response, tools)

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        if isinstance(ex, RateLimitError):
            # Do not retry on these rate limit errors
            if (
                "Request too large" not in ex.message
                and "You exceeded your current quota" not in ex.message
            ):
                return True
        elif isinstance(
            ex, (APIConnectionError | APITimeoutError | InternalServerError)
        ):
            return True
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
        if config.timeout is not None:
            params["timeout"] = float(config.timeout)
        if config.num_choices is not None:
            params["n"] = config.num_choices
        if config.logprobs is not None:
            params["logprobs"] = config.logprobs
        if config.top_logprobs is not None:
            params["top_logprobs"] = config.top_logprobs
        if tools and config.parallel_tool_calls is not None and not self.is_o_series():
            params["parallel_tool_calls"] = config.parallel_tool_calls
        if config.reasoning_effort is not None and not self.is_gpt():
            params["reasoning_effort"] = config.reasoning_effort

        return params

    # convert some well known bad request errors into ModelOutput
    def handle_bad_request(self, e: BadRequestError) -> ModelOutput | Exception:
        # extract message
        if isinstance(e.body, dict) and "message" in e.body.keys():
            content = str(e.body.get("message"))
        else:
            content = e.message

        # narrow stop_reason
        stop_reason: StopReason | None = None
        if e.code == "context_length_exceeded":
            stop_reason = "model_length"
        elif (
            e.code == "invalid_prompt"  # seems to happen for o1/o3
            or e.code == "content_policy_violation"  # seems to happen for vision
            or e.code == "content_filter"  # seems to happen on azure
        ):
            stop_reason = "content_filter"

        if stop_reason:
            return ModelOutput.from_content(
                model=self.model_name, content=content, stop_reason=stop_reason
            )
        else:
            return e
