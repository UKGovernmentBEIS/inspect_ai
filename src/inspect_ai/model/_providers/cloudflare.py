import os
from typing import Any

from openai import APIStatusError
from openai.types.chat import ChatCompletionMessageParam
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai._util.http import parse_retry_after_from_exception, status_code_of
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI

from ...model import ChatMessage, GenerateConfig
from .._model import RetryDecision
from .._openai import fill_empty_assistant_content
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
        # report the variable that the key actually came from to override hooks
        api_key_var = CLOUDFLARE_API_KEY
        # migrate formerly used CLOUDFLARE_API_TOKEN if no other key is specified
        if api_key is None and CLOUDFLARE_API_KEY not in os.environ:
            api_key = os.environ.get(CLOUDFLARE_API_TOKEN, None)
            if api_key is not None:
                api_key_var = CLOUDFLARE_API_TOKEN

        # account id used for limits and forming base url
        self.account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", None)
        if not self.account_id:
            raise environment_prerequisite_error("CloudFlare", "CLOUDFLARE_ACCOUNT_ID")

        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_var=api_key_var,
            config=config,
            service="CloudFlare",
            service_base_url=f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/v1",
            **model_args,
        )

    # gateway-hosted models (e.g. moonshotai/kimi-k3) reject assistant
    # messages with empty content
    @override
    async def messages_to_openai(
        self, input: list[ChatMessage]
    ) -> list[ChatCompletionMessageParam]:
        return fill_empty_assistant_content(await super().messages_to_openai(input))

    @override
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        # cloudflare signals context window overflow via 403 or 413
        if ex.status_code in (403, 413):
            content = str(ex)
            if "context window limit" in content:
                return ModelOutput.from_content(
                    self.model_name, content=content, stop_reason="model_length"
                )
        return ex

    # the service returns 503 when overloaded -- classify as a rate limit so
    # the adaptive concurrency controller scales down (checked before the
    # base classifier, which would treat an SDK-shaped 503 as transient,
    # pausing scale-up without backing off)
    @override
    def should_retry(self, ex: BaseException) -> bool | RetryDecision:
        if status_code_of(ex) == 503:
            return RetryDecision.rate_limit(
                retry_after=parse_retry_after_from_exception(ex)
            )
        return super().should_retry(ex)

    # cloudflare enforces rate limits by model for each account
    @override
    def connection_key(self) -> str:
        return f"{self.account_id}{self.model_name}"

    # cloudflare defaults to 256 max tokens, not enough for evals
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        Model names are passed verbatim as they appear in CloudFlare's
        catalog: Workers AI models carry an @cf/ prefix (stripped here for
        database lookup) while gateway models (e.g. moonshotai/kimi-k3)
        have no prefix and are returned unchanged.
        """
        name = self.service_model_name()
        # Strip @cf/ prefix if present
        if name.startswith("@cf/"):
            name = name[4:]
        return name
