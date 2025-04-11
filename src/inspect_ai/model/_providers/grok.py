from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI


class GrokAPI(OpenAICompatibleAPI):
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
            api_key=api_key,
            config=config,
            service="Grok",
            service_base_url="https://api.x.ai/v1",
        )
