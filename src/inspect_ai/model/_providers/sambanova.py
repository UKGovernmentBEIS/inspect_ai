from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI


class SambaNovaAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        emulate_tools: bool = False,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="SambaNova",
            service_base_url="https://api.sambanova.ai/v1",
            emulate_tools=emulate_tools,
        )
