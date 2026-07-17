from typing import Any

from typing_extensions import override

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI

# Sampling parameters that Moonshot says to omit for Kimi K3 (the model uses
# fixed sampling and the API rejects attempts to override it).
# https://platform.kimi.ai/docs/guide/use-thinking-effort
K3_FIXED_SAMPLING_PARAMS = (
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
)


class MoonshotAPI(OpenAICompatibleAPI):
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
            service="Moonshot",
            service_base_url="https://api.moonshot.ai/v1",
            emulate_tools=emulate_tools,
        )

    def is_kimi_k3(self) -> bool:
        return self.service_model_name().lower().startswith("kimi-k3")

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        Kimi models are keyed under the `moonshotai` organization in the
        model info database (matching OpenRouter/HuggingFace naming).
        """
        return f"moonshotai/{self.service_model_name()}"

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params = super().completion_params(config, tools)
        if self.is_kimi_k3():
            for param in K3_FIXED_SAMPLING_PARAMS:
                params.pop(param, None)
        return params
