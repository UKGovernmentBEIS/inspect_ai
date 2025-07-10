from typing import Any

from transformer_lens import HookedTransformer

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
        assert isinstance(model_args["model"], HookedTransformer), "model must be a transformer_lens.HookedTransformer"

        self.model = model_args["model"]



    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        choice = ChatCompletionChoice(
            message=ChatMessageAssistant(
                content="",
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
