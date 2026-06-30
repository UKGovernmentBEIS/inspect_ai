from typing import Any

from typing_extensions import override

from .._generate_config import GenerateConfig
from .._reasoning import clamp_reasoning_effort_to_low_medium_high
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
    def connection_key(self) -> str:
        """Scope max_connections per Ollama endpoint.

        Override the OpenAI-compatible default (which keys by api_key) since
        Ollama is a local server: the rate-limit boundary is the endpoint URL,
        not the credential (which defaults to the literal `"ollama"` for all
        instances). Without this override two Ollama servers on different
        hosts/ports would collapse to one concurrency slot.
        """
        return self.base_url or "ollama"

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params = super().completion_params(config, tools)

        # Ollama uses `"reasoning": { "effort": _ }`
        # instead of `"reasoning_effort": _`
        # https://github.com/ollama/ollama/blob/f2e9c9aff5f59b21a5d9a9668408732b3de01e20/openai/openai.go#L105
        if "reasoning_effort" in params:
            del params["reasoning_effort"]
        if config.reasoning_effort is not None:
            # Ollama's API accepts low/medium/high; clamp the extended effort
            # values (minimal/xhigh/max) so requests aren't rejected.
            clamped = clamp_reasoning_effort_to_low_medium_high(config.reasoning_effort)
            if clamped is not None:
                params.setdefault("extra_body", {})["reasoning"] = {
                    "effort": clamped,
                }

        return params
