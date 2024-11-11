import os

from inspect_ai.model._providers.util import model_base_url
from inspect_ai.model._providers.util.util import environment_prerequisite_error

from .._generate_config import GenerateConfig
from .openai import OpenAIAPI

GROK_API_KEY = "GROK_API_KEY"


class GrokAPI(OpenAIAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        # resolve base url
        base_url = model_base_url(base_url, "GROK_BASE_URL")
        base_url = base_url or "https://api.x.ai/v1"

        # resolve api key
        api_key = api_key or os.environ.get(GROK_API_KEY, None)
        if api_key is None:
            raise environment_prerequisite_error("Grok", GROK_API_KEY)

        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
        )
