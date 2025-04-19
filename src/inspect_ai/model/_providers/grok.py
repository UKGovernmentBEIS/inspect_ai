from openai import APIStatusError

from inspect_ai.model._model_output import ModelOutput

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI


class GrokAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="Grok",
            service_base_url="https://api.x.ai/v1",
        )

    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        if ex.status_code == 400:
            # extract message
            if isinstance(ex.body, dict) and "message" in ex.body.keys():
                content = str(ex.body.get("message"))
            else:
                content = ex.message

            if "prompt length" in content:
                return ModelOutput.from_content(
                    model=self.model_name, content=content, stop_reason="model_length"
                )
            else:
                return ex
        else:
            return ex
