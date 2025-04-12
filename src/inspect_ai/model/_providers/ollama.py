from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI


class OllamaAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key or "ollama",
            config=config,
            service="Ollama",
            service_base_url="http://localhost:11434/v1",
        )
