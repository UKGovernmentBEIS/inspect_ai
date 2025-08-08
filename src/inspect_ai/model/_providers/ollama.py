from typing import Any

from typing_extensions import override

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI


class OllamaAPI(OpenAICompatibleAPI):
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
            api_key=api_key or "ollama",
            config=config,
            service="Ollama",
            service_base_url="http://localhost:11434/v1",
            emulate_tools=emulate_tools,
        )

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params = super().completion_params(config, tools)

        # Ollama uses `"reasoning": { "effort": _ }`
        # instead of `"reasoning_effort": _`
        # https://github.com/ollama/ollama/blob/f2e9c9aff5f59b21a5d9a9668408732b3de01e20/openai/openai.go#L105
        if "reasoning_effort" in params:
            del params["reasoning_effort"]
        if config.reasoning_effort is not None:
            params.setdefault("extra_body", {})["reasoning"] = {
                "effort": config.reasoning_effort,
            }

        return params
