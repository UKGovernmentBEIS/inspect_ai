import json
import re
from logging import getLogger

from typing_extensions import override

from inspect_ai.tool._tool_info import ToolInfo

from ..._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
)
from .chatapi import ChatAPIHandler, ChatApiMessage
from .util import parse_tool_call

logger = getLogger(__name__)


class Llama31Handler(ChatAPIHandler):
    # see https://docs.together.ai/docs/llama-3-function-calling
    @override
    def input_with_tools(
        self, input: list[ChatMessage], tools: list[ToolInfo]
    ) -> list[ChatMessage]:
        if len(tools) == 0:
            return input

        tool_descriptions = "\n\n".join(
            [
                f"Use the '{tool.name}' tool to '{tool.description}':\n{tool.parameters.model_dump_json(exclude_none=True)}"
                for tool in tools
            ]
        )

        toolPrompt = f"""
You have access to the following functions:

{tool_descriptions}

If you choose to call a function ONLY reply in the following format with no prefix or suffix:

<function=example_function_name>{{\"example_name\": \"example_value\"}}</function>

Reminder:
- Function calls MUST follow the specified format, start with <function= and end with </function>
- Required parameters MUST be specified
- Only call one function at a time
- Put the entire function call reply on one line
- If there is no function call available, answer the question like normal with your current knowledge and do not tell the user about function calls
"""

        return [ChatMessageSystem(content=toolPrompt)] + input

    @override
    def parse_assistent_response(
        self, response: str, tools: list[ToolInfo]
    ) -> ChatMessageAssistant:
        function_regex = r"<function=(\w+)>(.*?)</function>"

        match = re.search(function_regex, response)
        if match:
            function_name, args_string = match.groups()
            tool_call = parse_tool_call(
                function_name, function_name, args_string, tools
            )
            return ChatMessageAssistant(
                content="", tool_calls=[tool_call], source="generate"
            )
        else:
            return ChatMessageAssistant(content=response, source="generate")

    def assistant_message(self, message: ChatMessageAssistant) -> ChatApiMessage:
        if message.tool_calls:
            content = "\n\n".join(
                [
                    f"<function={tool.function}>{json.dumps(tool.arguments)}</function>"
                    for tool in message.tool_calls
                ]
            )
        else:
            content = message.text

        return {"role": "assistant", "content": content}

    def tool_message(self, message: ChatMessageTool) -> ChatApiMessage:
        return {
            "role": "tool",
            "content": f"Error: {message.error.message}"
            if message.error
            else message.text,
        }
