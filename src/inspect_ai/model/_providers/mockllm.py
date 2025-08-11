from typing import Any, Callable, Generator, Iterable, Iterator

from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import (
    ModelOutput,
)


class MockLLM(ModelAPI):
    """A mock implementation of the ModelAPI class for testing purposes.

    Always returns default_output, unless you pass in a model_args
    key "custom_outputs" with a value of an Iterable[ModelOutput],
    Generator[ModelOutput, None, None], or a Callable that takes
    (input, tools, tool_choice, config) and returns a single ModelOutput.
    The callable acts like a generator with access to generate parameters.
    """

    default_output = "Default output from mockllm/model"

    outputs: (
        Iterator[ModelOutput]
        | Callable[
            [list[ChatMessage], list[ToolInfo], ToolChoice, GenerateConfig], ModelOutput
        ]
    )

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        custom_outputs: Iterable[ModelOutput]
        | Generator[ModelOutput, None, None]
        | Callable[
            [list[ChatMessage], list[ToolInfo], ToolChoice, GenerateConfig], ModelOutput
        ]
        | None = None,
        **model_args: dict[str, Any],
    ) -> None:
        super().__init__(model_name, base_url, api_key, [], config)
        self.model_args = model_args
        if custom_outputs is not None:
            # Check if it's a callable function
            if isinstance(custom_outputs, Generator) or callable(custom_outputs):
                self.outputs = custom_outputs
            elif isinstance(custom_outputs, Iterable):
                self.outputs = iter(custom_outputs)
            else:
                # We cannot rely on the user of this model giving custom_outputs the correct type since they do not call this constructor
                # Hence this type check and the one in generate.
                raise ValueError(
                    f"model_args['custom_outputs'] must be an Iterable, Generator, or Callable, got {custom_outputs}"
                )
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
        # If we have a custom function, call it with the generate arguments each time
        if callable(self.outputs):
            return self.outputs(input, tools, tool_choice, config)

        try:
            output = next(self.outputs)
        except StopIteration:
            raise ValueError("custom_outputs ran out of values")

        if not isinstance(output, ModelOutput):
            raise ValueError(
                f"output must be an instance of ModelOutput; got {type(output)}; content: {repr(output)}"
            )
        return output
