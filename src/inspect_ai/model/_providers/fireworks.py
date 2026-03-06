from typing_extensions import override

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI


class FireworksAIAPI(OpenAICompatibleAPI):
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
            service="Fireworks",
            service_base_url="https://api.fireworks.ai/inference/v1",
            emulate_tools=emulate_tools,
        )

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        Fireworks model names may include the accounts/fireworks/models/ prefix.
        This method strips that prefix if present.
        """
        name = self.service_model_name()
        # Strip accounts/fireworks/models/ prefix if present
        prefix = "accounts/fireworks/models/"
        if name.startswith(prefix):
            name = name[len(prefix) :]
        return name

    @override
    def should_stream(self, config: GenerateConfig) -> bool:
        return config.max_tokens is not None and config.max_tokens > 16000
