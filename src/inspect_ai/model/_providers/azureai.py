import os
import ssl
from copy import deepcopy
from typing import Any

import httpx
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .util import (
    Llama31Handler,
    as_stop_reason,
    chat_api_input,
    chat_api_request,
    environment_prerequisite_error,
    is_chat_api_rate_limit,
    model_base_url,
)
from .util.chatapi import ChatAPIHandler

AZUREAI_API_KEY = "AZUREAI_API_KEY"
AZUREAI_BASE_URL = "AZUREAI_BASE_URL"
AZUREAI_ENDPOINT_URL = "AZUREAI_ENDPOINT_URL"
AZUREAI_SELF_SIGNED = "AZUREAI_SELF_SIGNED"

# legacy vars for migration
AZURE_API_KEY = "AZURE_API_KEY"
AZURE_ENDPOINT_URL = "AZURE_ENDPOINT_URL"
AZURE_SELF_SIGNED = "AZURE_SELF_SIGNED"


class AzureAIAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[AZURE_API_KEY],
            config=config,
        )

        # required for some deployments
        if (
            os.getenv(AZURE_SELF_SIGNED, os.getenv(AZUREAI_SELF_SIGNED, None))
            is not None
        ):
            allowSelfSignedHttps(True)

        # resolve api_key
        if not self.api_key:
            self.api_key = os.environ.get(
                AZURE_API_KEY, os.environ.get(AZUREAI_API_KEY, "")
            )
            if not self.api_key:
                raise environment_prerequisite_error("AzureAI", AZURE_API_KEY)

        # resolve base url
        endpoint_url = model_base_url(
            base_url,
            [
                AZURE_ENDPOINT_URL,
                AZUREAI_ENDPOINT_URL,
                AZUREAI_BASE_URL,
            ],
        )
        if not endpoint_url:
            raise environment_prerequisite_error("AzureAI", AZUREAI_BASE_URL)
        self.endpoint_url = endpoint_url

        # create client
        self.client = httpx.AsyncClient()
        self.model_args = model_args

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        # There are two different model APIs on Azure AI. The first is associated
        # with 'realtime' deployments of llama (and maps closely to other llama
        # inference apis):
        # https://ai.azure.com/explore/models/Llama-2-70b-chat/version/17/registry/azureml-meta
        # other models use a more standard chat completions API:
        # https://learn.microsoft.com/en-us/azure/ai-studio/how-to/deploy-models-mistral#request-schema

        # base parameters shared by both endpoints
        parameters = deepcopy(self.model_args)
        if config.temperature is not None:
            parameters["temperature"] = config.temperature
        if config.top_p is not None:
            parameters["top_p"] = config.top_p

        # JSON payload and endpoint for Llama realtime API
        if self.is_llama_score_api():
            # additional parameters
            if config.top_k is not None:
                parameters["top_k"] = config.top_k
            if (
                config.temperature is not None
                or config.top_p is not None
                or config.top_k is not None
            ):
                parameters["do_sample"] = True

            # API docs say its 'max_new_tokens' and that seems to work
            # 'max_tokens' also seems to work but stick w/ api docs
            if config.max_tokens is not None:
                parameters["max_new_tokens"] = config.max_tokens

            # build payload
            json = dict(
                input_data=dict(
                    input_string=chat_api_input(input, tools, self.chat_api_handler()),
                    parameters=parameters,
                )
            )

            # endpoint
            endpoint_url = self.endpoint_url

        # standard chat completions JSON payload (Mistral or Llama not at '/score')
        else:
            # additional parameters
            if config.max_tokens is not None:
                parameters["max_tokens"] = config.max_tokens
            if config.num_choices:
                parameters["n"] = config.num_choices

            # request payload
            json = (
                dict(messages=chat_api_input(input, tools, self.chat_api_handler()))
                | parameters
            )

            # endpoint
            endpoint_url = f"{self.endpoint_url}/v1/chat/completions"

        # call model
        try:
            response = await chat_api_request(
                self.client,
                model_name=self.model_name,
                url=endpoint_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "azureml-model-deployment": self.model_name,
                },
                json=json,
                config=config,
            )
        except httpx.HTTPStatusError as ex:
            if ex.response.status_code == 400:
                return self.handle_bad_request(ex)
            else:
                raise ex

        # record call
        call = ModelCall.create(
            request=dict(model_name=self.model_name, **json), response=response
        )

        # return result
        if self.is_llama_score_api():
            return ModelOutput.from_content(
                model=self.model_name, content=response["output"]
            ), call
        else:
            model = response.get("model", "")
            choices = chat_completion_choices(
                response["choices"], tools, self.chat_api_handler()
            )
            model_usage = response.get("usage", None)
            if model_usage:
                usage = ModelUsage(
                    input_tokens=model_usage.get("prompt_tokens", 0),
                    output_tokens=model_usage.get("completion_tokens", 0),
                    total_tokens=model_usage.get("total_tokens", 0),
                )
            else:
                usage = None
            return ModelOutput(model=model, choices=choices, usage=usage), call

    @override
    def max_tokens(self) -> int | None:
        # llama2 models have a default max_tokens of 256 (context window is 4096)
        # https://ai.azure.com/explore/models/Llama-2-70b-chat/version/17/registry/azureml-meta
        if self.is_llama():
            return DEFAULT_MAX_TOKENS

        # Mistral uses a default of 8192 which is fine, so we don't mess with it
        # see: https://learn.microsoft.com/en-us/azure/ai-studio/how-to/deploy-models-mistral#request-schema
        elif self.is_mistral():
            return None

        # Not sure what do to about other model types... (there aren't currently any others)
        else:
            return DEFAULT_MAX_TOKENS

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        return is_chat_api_rate_limit(ex)

    @override
    def collapse_user_messages(self) -> bool:
        return True

    @override
    def connection_key(self) -> str:
        return f"{self.api_key}{self.model_name}"

    def is_llama(self) -> bool:
        return "llama" in self.model_name.lower()

    def is_llama_score_api(self) -> bool:
        return self.endpoint_url.endswith("/score") and self.is_llama()

    def is_mistral(self) -> bool:
        return "mistral" in self.model_name.lower()

    def chat_api_handler(self) -> ChatAPIHandler:
        if "llama" in self.model_name.lower():
            return Llama31Handler()
        else:
            return ChatAPIHandler()

    def handle_bad_request(self, ex: httpx.HTTPStatusError) -> ModelOutput:
        if "maximum context length" in ex.response.text.lower():
            return ModelOutput.from_content(
                model=self.model_name,
                content=ex.response.text,
                stop_reason="model_length",
            )
        else:
            raise ex


def chat_completion_choices(
    choices: list[dict[str, Any]], tools: list[ToolInfo], handler: ChatAPIHandler
) -> list[ChatCompletionChoice]:
    return [chat_completion_choice(choice, tools, handler) for choice in choices]


def chat_completion_choice(
    choice: dict[str, Any], tools: list[ToolInfo], handler: ChatAPIHandler
) -> ChatCompletionChoice:
    content = choice["message"]["content"]
    return ChatCompletionChoice(
        message=handler.parse_assistant_response(content, tools),
        stop_reason=choice_stop_reason(choice),
    )


def choice_stop_reason(choice: dict[str, Any]) -> StopReason:
    return as_stop_reason(choice.get("finish_reason", None))


def allowSelfSignedHttps(allowed: bool) -> None:
    # bypass the server certificate verification on client side
    if (
        allowed
        and not os.environ.get("PYTHONHTTPSVERIFY", "")
        and getattr(ssl, "_create_unverified_context", None)
    ):
        ssl._create_default_https_context = ssl._create_unverified_context
