from typing import Any

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI

ABLIT_KEY = "ABLIT_KEY"


class AbliterationAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        emulate_tools: bool = False,
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="Abliteration",
            service_base_url="https://api.abliteration.ai/v1",
            api_key_var=ABLIT_KEY,
            emulate_tools=emulate_tools,
            **model_args,
        )
