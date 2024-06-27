from inspect_ai.model._providers.util import model_base_url

from .._generate_config import GenerateConfig
from .openai import OpenAIAPI


class OllamaAPI(OpenAIAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        base_url = model_base_url(base_url, "OLLAMA_BASE_URL")
        base_url = base_url if base_url else "http://localhost:11434/v1"
        if not api_key:
            api_key = "ollama"
        super().__init__(
            model_name=model_name, base_url=base_url, api_key=api_key, config=config
        )
