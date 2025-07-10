from typing import Any

from transformer_lens import HookedTransformer  # type: ignore

from inspect_ai._util.content import (
    ContentAudio,
    ContentImage,
    ContentVideo,
)
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
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

        # Get the model from external code that initialized it
        # Using 'tl_model' to avoid conflict with get_model's 'model' parameter
        assert "tl_model" in model_args, "tl_model is required in model_args"
        assert isinstance(model_args["tl_model"], HookedTransformer), (
            "tl_model must be a transformer_lens.HookedTransformer"
        )

        self.model = model_args["tl_model"]

        assert "tl_generate_args" in model_args, (
            "tl_generate_args is required in model_args"
        )
        self.tl_generate_args = model_args["tl_generate_args"]

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # convert input to a list of strings
        input_str = message_content_to_string(input)

        input_and_response = self.model.generate(
            input=input_str,
            **self.tl_generate_args,
        )
        assert isinstance(input_and_response, str), (
            "List[str] and Tensor are not supported yet"
        )

        # crop off the input
        response = input_and_response[len(input_str) :]

        choice = ChatCompletionChoice(
            message=ChatMessageAssistant(
                content=response,
                model=self.model_name,
                source="generate",
            ),
        )

        return ModelOutput(model=self.model_name, choices=[choice])


def message_content_to_string(messages: list[ChatMessage]) -> str:
    """Convert list of content in `ChatMessageAssistant`, `ChatMessageUser` or `ChatMessageSystem` to a string.

    Modified from the HuggingFace provider.
    """
    out = ""
    for message in messages:
        if isinstance(message.content, list):
            is_multimodal = any(
                isinstance(item, ContentAudio | ContentImage | ContentVideo)
                for item in message.content
            )
            if is_multimodal:
                raise NotImplementedError(
                    "TransformerLens provider does not support multimodal content, please provide text inputs only."
                )
            message.content = message.text
        out += f"{message.role}: {message.content}\n"

    return out
