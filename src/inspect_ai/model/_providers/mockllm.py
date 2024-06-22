from typing import Any, Iterable, Iterator

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import (
    ModelOutput,
)
from .._tool import ToolChoice, ToolInfo


class MockLLM(ModelAPI):
    """A mock implementation of the ModelAPI class for testing purposes.

    Always returns default_output, unless you pass in a model_args
    key "custom_outputs" with a value of an Iterable[ModelOutput]
    """

    default_output = "Default output from mockllm/model"

    outputs: Iterator[ModelOutput]

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        custom_outputs: Iterable[ModelOutput] = [],
        **model_args: dict[str, Any],
    ) -> None:
        super().__init__(model_name, base_url, config)
        self.model_args = model_args
        if model_name != "model":
            raise ValueError(f"Invalid model name: {model_name}")
        if custom_outputs:
            # We cannot rely on the user of this model giving custom_outputs the correct type since they do not call this constructor
            # Hence this type check and the one in generate.
            if not isinstance(custom_outputs, Iterable):
                raise ValueError(
                    f"model_args['custom_outputs'] must be an Iterable, got {custom_outputs}"
                )
            self.outputs = iter(custom_outputs)
        else:
            self.outputs = iter(
                (
                    ModelOutput.from_content(
                        model="mockllm", content=self.default_output
                    )
                    for _ in iter(int, 1)  # produce an infinite iterator
                )
            )

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        try:
            output = next(self.outputs)
        except StopIteration:
            raise ValueError("custom_outputs ran out of values")

        if not isinstance(output, ModelOutput):
            raise ValueError("output must be an instance of ModelOutput")
        return output
