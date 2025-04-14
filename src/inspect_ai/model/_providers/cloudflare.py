import os
from typing import Any

from openai import APIStatusError
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI

from ...model import GenerateConfig
from .util import environment_prerequisite_error

# https://developers.cloudflare.com/workers-ai/models/#text-generation
# https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/

CLOUDFLARE_API_KEY = "CLOUDFLARE_API_KEY"
CLOUDFLARE_API_TOKEN = "CLOUDFLARE_API_TOKEN"


class CloudFlareAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        # migrate formerly used CLOUDFLARE_API_TOKEN if no other key is specified
        if api_key is None and CLOUDFLARE_API_KEY not in os.environ:
            api_key = os.environ.get(CLOUDFLARE_API_TOKEN, None)

        # account id used for limits and forming base url
        self.account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", None)
        if not self.account_id:
            raise environment_prerequisite_error("CloudFlare", "CLOUDFLARE_ACCOUNT_ID")

        super().__init__(
            model_name=f"@cf/{model_name}",
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="CloudFlare",
            service_base_url=f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/v1",
            **model_args,
        )

    @override
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        if ex.status_code == 403:
            content = str(ex)
            if "context window limit" in content:
                return ModelOutput.from_content(
                    self.model_name, content=content, stop_reason="model_length"
                )
        return ex

    # cloudflare enforces rate limits by model for each account
    @override
    def connection_key(self) -> str:
        return f"{self.account_id}{self.model_name}"

    # cloudflare defaults to 256 max tokens, not enough for evals
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS
