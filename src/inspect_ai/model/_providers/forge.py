from typing_extensions import override

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI
from .util import model_base_url

FORGE_API_BASE = "FORGE_API_BASE"
FORGE_BASE_URL = "FORGE_BASE_URL"


class ForgeAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        emulate_tools: bool = False,
    ) -> None:
        resolved_base_url = model_base_url(base_url, [FORGE_API_BASE, FORGE_BASE_URL])
        super().__init__(
            model_name=model_name,
            base_url=resolved_base_url,
            api_key=api_key,
            config=config,
            service="Forge",
            service_base_url="https://api.forge.tensorblock.co/v1",
            emulate_tools=emulate_tools,
        )

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        Forge uses a Provider/model-name format. We preserve the provider prefix
        to match model info entries when available.
        """
        return self.service_model_name()
