import os

from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from inspect_ai.model._providers.util import model_base_url

from .._model import GenerateConfig
from .openai import OpenAIAPI


class TogetherAIAPI(OpenAIAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        api_key = os.environ.get("TOGETHER_API_KEY", None)
        if not api_key:
            raise RuntimeError("TOGETHER_API_KEY environment variable not set")
        base_url = model_base_url(base_url, "TOGETHER_BASE_URL")
        base_url = base_url if base_url else "https://api.together.xyz/v1"
        super().__init__(
            model_name=model_name, base_url=base_url, config=config, api_key=api_key
        )

    # Together uses a default of 512 so we bump it up
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS
