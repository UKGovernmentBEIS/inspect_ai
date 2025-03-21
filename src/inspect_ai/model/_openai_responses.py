from openai.types.responses import Response, ResponseInputItemParam, ToolParam
from openai.types.responses.response_create_params import (
    ToolChoice as ResponsesToolChoice,
)

from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from ._chat_message import ChatMessage


async def openai_responses_inputs(
    messages: list[ChatMessage], model: str
) -> list[ResponseInputItemParam]:
    return []


def openai_responses_tool_choice(tool_choice: ToolChoice) -> ResponsesToolChoice:
    return "auto"


def openai_responses_tools(tools: list[ToolInfo]) -> list[ToolParam]:
    return []


def openai_responses_chat_choices(
    response: Response, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    return []
