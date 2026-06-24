from typing import Any

from typing_extensions import override

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI

HF_TOKEN = "HF_TOKEN"


class HFInferenceProvidersAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        stream: bool | None = None,
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url or "https://router.huggingface.co/v1",
            api_key=api_key,
            api_key_var=HF_TOKEN,
            config=config,
            service="HF Inference Providers",
            service_base_url="https://router.huggingface.co/v1",
            stream=stream is not False,
            **model_args,
        )

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        HF Inference uses HuggingFace-style names directly (e.g., meta-llama/Llama-3.1-8B).
        Provider selection suffixes like :fastest, :cheapest, or :provider-name
        are stripped for database lookup.
        """
        name = self.service_model_name()

        # Strip provider selection suffixes (:fastest, :cheapest, :provider-name)
        if ":" in name:
            name = name.split(":")[0]

        return name
