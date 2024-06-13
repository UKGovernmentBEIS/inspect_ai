import os
import ssl
from copy import deepcopy
from typing import Any

import httpx
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .._tool import ToolChoice, ToolInfo
from .._util import (
    chat_api_input,
    chat_api_request,
    is_chat_api_rate_limit,
)
from .util import as_stop_reason, model_base_url

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
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(model_name=model_name, base_url=base_url, config=config)

        # required for some deployments
        if (
            os.getenv(AZURE_SELF_SIGNED, os.getenv(AZUREAI_SELF_SIGNED, None))
            is not None
        ):
            allowSelfSignedHttps(True)

        # resolve api_key
        api_key = os.environ.get(AZURE_API_KEY, os.environ.get(AZUREAI_API_KEY, ""))
        if not api_key:
            raise ValueError(f"{AZURE_API_KEY} environment variable not found.")
        self.api_key = api_key

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
            raise ValueError("{AZUREAI_BASE_URL} environment variable not found.")
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
    ) -> ModelOutput:
        # There are two different model APIs on Azure AI. The first is associated
        # with 'realtime' deployments of llama-2 (and maps closely to other llama-2
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

        # JSON payload and endpoint for Llama 2 realtime API
        if self.is_llama2_score_api():
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
                    input_string=chat_api_input(input),
                    parameters=parameters,
                )
            )

            # endpoint
            endpoint_url = self.endpoint_url

        # standard chat completions JSON payload (Mistral or Llama2 not at '/score')
        else:
            # additional parameters
            if config.max_tokens is not None:
                parameters["max_tokens"] = config.max_tokens
            if config.num_choices:
                parameters["n"] = config.num_choices

            # request payload
            json = dict(messages=chat_api_input(input)) | parameters

            # endpoint
            endpoint_url = f"{self.endpoint_url}/v1/chat/completions"

        # call model
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

        # return result
        if self.is_llama2_score_api():
            return ModelOutput.from_content(
                model=self.model_name, content=response["output"]
            )
        else:
            model = response.get("model", "")
            choices = chat_completion_choices(response["choices"])
            model_usage = response.get("usage", None)
            if model_usage:
                usage = ModelUsage(
                    input_tokens=model_usage.get("prompt_tokens", 0),
                    output_tokens=model_usage.get("completion_tokens", 0),
                    total_tokens=model_usage.get("total_tokens", 0),
                )
            else:
                usage = None
            return ModelOutput(model=model, choices=choices, usage=usage)

    @override
    def max_tokens(self) -> int | None:
        # llama2 models have a default max_tokens of 256 (context window is 4096)
        # https://ai.azure.com/explore/models/Llama-2-70b-chat/version/17/registry/azureml-meta
        if self.is_llama2():
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

    def is_llama2(self) -> bool:
        return "llama-2" in self.model_name.lower()

    def is_llama2_score_api(self) -> bool:
        return self.endpoint_url.endswith("/score") and self.is_llama2()

    def is_mistral(self) -> bool:
        return "mistral" in self.model_name.lower()


def chat_completion_choices(
    choices: list[dict[str, Any]],
) -> list[ChatCompletionChoice]:
    return [chat_completion_choice(choice) for choice in choices]


def chat_completion_choice(choice: dict[str, Any]) -> ChatCompletionChoice:
    return ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=choice["message"]["content"], source="generate"
        ),
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
