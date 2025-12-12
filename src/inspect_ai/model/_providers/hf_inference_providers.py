import os
from typing import Any

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI
from .util import environment_prerequisite_error

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
        # Handle API key before calling super() to avoid the automatic key generation
        if not api_key:
            api_key = os.environ.get(HF_TOKEN, None)
            if not api_key:
                raise environment_prerequisite_error(
                    "HF Inference Providers",
                    [HF_TOKEN],
                )

        super().__init__(
            model_name=model_name,
            base_url=base_url or "https://router.huggingface.co/v1",
            api_key=api_key,
            config=config,
            service="HF Inference Providers",
            service_base_url="https://router.huggingface.co/v1",
            stream=stream is not False,
            **model_args,
        )
