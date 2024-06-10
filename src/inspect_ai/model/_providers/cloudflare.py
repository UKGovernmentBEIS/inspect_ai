import os
from typing import Any

import httpx
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai.model import ChatMessage, GenerateConfig, ModelAPI, ModelOutput

from .._tool import ToolChoice, ToolInfo
from .._util import (
    chat_api_input,
    chat_api_request,
    is_chat_api_rate_limit,
)
from .util import model_base_url

# Cloudflare supported models:
# https://developers.cloudflare.com/workers-ai/models/#text-generation


class CloudFlareAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(model_name=model_name, base_url=base_url, config=config)
        self.account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        if not self.account_id:
            raise RuntimeError("CLOUDFLARE_ACCOUNT_ID environment variable not set")
        self.api_token = os.getenv("CLOUDFLARE_API_TOKEN")
        if not self.api_token:
            raise RuntimeError("CLOUDFLARE_API_TOKEN environment variable not set")
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
    ) -> ModelOutput:
        # chat url
        chat_url = f"{self.base_url}/{self.account_id}/ai/run/@cf"

        # chat api input
        json: dict[str, Any] = dict(**self.model_args)
        if config.max_tokens is not None:
            json["max_tokens"] = config.max_tokens
        json["messages"] = chat_api_input(input)

        # make the call
        response = await chat_api_request(
            self.client,
            model_name=self.model_name,
            url=f"{chat_url}/{self.model_name}",
            headers={"Authorization": f"Bearer {self.api_token}"},
            json=json,
            config=config,
        )

        # handle response
        if response["success"]:
            return ModelOutput.from_content(
                model=self.model_name, content=response["result"]["response"]
            )
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
