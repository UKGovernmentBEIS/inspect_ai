import os
from typing import Any

import httpx
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai.tool import ToolChoice, ToolInfo

from ...model import ChatMessage, GenerateConfig, ModelAPI, ModelOutput
from .._model_call import ModelCall
from .._model_output import ChatCompletionChoice
from .util import (
    ChatAPIHandler,
    Llama31Handler,
    chat_api_input,
    chat_api_request,
    environment_prerequisite_error,
    is_chat_api_rate_limit,
    model_base_url,
)

# https://developers.cloudflare.com/workers-ai/models/#text-generation


CLOUDFLARE_API_TOKEN = "CLOUDFLARE_API_TOKEN"


class CloudFlareAPI(ModelAPI):
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
            api_key_vars=[CLOUDFLARE_API_TOKEN],
            config=config,
        )
        self.account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        if not self.account_id:
            raise environment_prerequisite_error("CloudFlare", "CLOUDFLARE_ACCOUNT_ID")
        if not self.api_key:
            self.api_key = os.getenv(CLOUDFLARE_API_TOKEN)
            if not self.api_key:
                raise environment_prerequisite_error("CloudFlare", CLOUDFLARE_API_TOKEN)
        self.client = httpx.AsyncClient()
        base_url = model_base_url(base_url, "CLOUDFLARE_BASE_URL")
        self.base_url = (
            base_url if base_url else "https://api.cloudflare.com/client/v4/accounts"
        )
        self.model_args = model_args

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput, ModelCall]:
        # chat url
        chat_url = f"{self.base_url}/{self.account_id}/ai/run/@cf"

        # chat api input
        json: dict[str, Any] = dict(**self.model_args)
        if config.max_tokens is not None:
            json["max_tokens"] = config.max_tokens
        json["messages"] = chat_api_input(input, tools, self.chat_api_handler())

        # make the call
        response = await chat_api_request(
            self.client,
            model_name=self.model_name,
            url=f"{chat_url}/{self.model_name}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=json,
            config=config,
        )

        # handle response
        if response["success"]:
            # extract output
            content = response["result"]["response"]
            output = ModelOutput(
                model=self.model_name,
                choices=[
                    ChatCompletionChoice(
                        message=self.chat_api_handler().parse_assistant_response(
                            content, tools
                        ),
                        stop_reason="stop",
                    )
                ],
            )

            # record call
            call = ModelCall.create(
                request=dict(model_name=self.model_name, **json), response=response
            )

            # return
            return output, call
        else:
            error = str(response.get("errors", "Unknown"))
            raise RuntimeError(f"Error calling {self.model_name}: {error}")

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        return is_chat_api_rate_limit(ex)

    # cloudflare enforces rate limits by model for each account
    @override
    def connection_key(self) -> str:
        return f"{self.account_id}{self.model_name}"

    # cloudflare defaults to 256 max tokens, not enough for evals
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS

    def chat_api_handler(self) -> ChatAPIHandler:
        if "llama" in self.model_name.lower():
            return Llama31Handler()
        else:
            return ChatAPIHandler()
