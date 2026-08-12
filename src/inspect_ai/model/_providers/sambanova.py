from typing import Any

from typing_extensions import override

from .._generate_config import GenerateConfig
from .._reasoning import clamp_reasoning_effort_to_low_medium_high
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

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params = super().completion_params(config, tools)

        # SambaNova's API accepts only `low`/`medium`/`high`; clamp the extended
        # effort values (`minimal`/`xhigh`/`max`) so requests aren't rejected.
        # `none` isn't supported and is omitted, so the provider/model default
        # applies -- reasoning is not disabled (always-on models keep reasoning).
        if "reasoning_effort" in params:
            clamped = clamp_reasoning_effort_to_low_medium_high(
                params["reasoning_effort"]
            )
            if clamped is not None:
                params["reasoning_effort"] = clamped
            else:
                del params["reasoning_effort"]

        return params
