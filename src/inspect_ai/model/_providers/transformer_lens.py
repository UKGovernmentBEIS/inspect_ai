from typing import Any

from transformer_lens import HookedTransformer  # type: ignore

from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.tool import (
    ToolChoice,
    ToolInfo,
)


class TransformerLensAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            config=config,
        )

        # Get the model from extenral code that initialized it
        assert "model" in model_args, "model is required"
        assert isinstance(model_args["model"], HookedTransformer), (
            "model must be a transformer_lens.HookedTransformer"
        )

        self.model = model_args["model"]

        assert "tl_generate_args" in model_args, "tl_generate_args is required"
        self.tl_generate_args = model_args["tl_generate_args"]

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # TODO: Implement the generate method

        # convert input to a list of strings

        response = self.model.generate(
            input=input,
            **self.tl_generate_args,
        )



        choice = ChatCompletionChoice(
            message=ChatMessageAssistant(
                content=response.output,
                model=self.model_name,
                source="generate",
            ),
        )

        return ModelOutput(
            model=self.model_name,
            choices=[choice],
            usage=ModelUsage(
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
            ),
            time=0,
        )
