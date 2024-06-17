from typing import Any, cast

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import ModelOutput
from .._tool import ToolChoice, ToolInfo


class MockLLM(ModelAPI):
    """A mock implementation of the ModelAPI class for testing purposes.

    Always returns default_output, unles you pass in a model_args
    key "custom_output" with a value of a ModelOutput
    """

    default_output = "Default output from mockllm/model"
    output = ModelOutput.from_content(model="mockllm", content=default_output)

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: dict[str, Any],
    ) -> None:
        super().__init__(model_name, base_url, config)
        self.model_args = model_args
        if model_name != "model":
            raise ValueError(f"Invalid model name: {model_name}")
        if "custom_output" in model_args:
            self.output = cast(ModelOutput, model_args["custom_output"])
            if not isinstance(self.output, ModelOutput):
                raise ValueError("custom_output must be an instance of ModelOutput")

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        return self.output
