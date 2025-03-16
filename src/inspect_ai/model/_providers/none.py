from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import ModelOutput


class NoModel(ModelAPI):
    """A sentinel model type indicating there is no model specified."""

    def __init__(
        self,
        model_name: str = "none",
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        super().__init__(model_name, base_url, api_key, [], config)

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        raise PrerequisiteError(
            "No model specified (and no INSPECT_EVAL_MODEL defined)"
        )
