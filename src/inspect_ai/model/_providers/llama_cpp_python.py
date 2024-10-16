from inspect_ai.model._providers.util import model_base_url

from .._generate_config import GenerateConfig
from .openai import OpenAIAPI


class LlamaCppPythonAPI(OpenAIAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        base_url = model_base_url(base_url, "LLAMA_CPP_PYTHON_BASE_URL")
        base_url = base_url if base_url else "http://localhost:8000/v1"
        if not api_key:
            api_key = "llama-cpp-python"
        super().__init__(
            model_name=model_name, base_url=base_url, api_key=api_key, config=config
        )
