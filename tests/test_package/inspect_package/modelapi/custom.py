from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ToolChoice,
    ToolInfo,
)


class CustomModelAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        super().__init__(model_name, base_url, config)

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        return ModelOutput.from_content(
            self.model_name, f"Hello from {self.model_name}"
        )
