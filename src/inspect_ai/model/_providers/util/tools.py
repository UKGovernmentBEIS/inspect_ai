import json
import re
from logging import getLogger
from typing import Any, Literal

import yaml
import yaml.parser
from typing_extensions import override

from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo

from ..._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
)
from ..._model import ModelName

logger = getLogger(__name__)


ChatApiMessage = dict[Literal["role", "content"], str]


class ChatAPIToolsHandler:
    def input_with_tools(
        self, input: list[ChatMessage], tools: list[ToolInfo]
    ) -> list[ChatMessage]:
        return input

    def parse_assistant_message(
        self, response: str, tools: list[ToolInfo]
    ) -> ChatMessageAssistant:
        return ChatMessageAssistant(content=response)

    def chat_api_assistant_message(
        self, message: ChatMessageAssistant
    ) -> ChatApiMessage:
        return {"role": "assistant", "content": message.text}

    def chat_api_tool_message(self, message: ChatMessageTool) -> ChatApiMessage:
        return {
            "role": "tool",
            "content": f"Error: {message.error.message}"
            if message.error
            else message.text,
        }


def chat_api_tools_handler(model: str) -> ChatAPIToolsHandler:
    match ModelName(model):
        case "llama":
            return Llama31ToolsHandler()
        case _:
            return ChatAPIToolsHandler()


class Llama31ToolsHandler(ChatAPIToolsHandler):
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
    def parse_assistant_message(
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

    def chat_api_assistant_message(
        self, message: ChatMessageAssistant
    ) -> ChatApiMessage:
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

    def chat_api_tool_message(self, message: ChatMessageTool) -> ChatApiMessage:
        return {
            "role": "tool",
            "content": f"Error: {message.error.message}"
            if message.error
            else message.text,
        }


def parse_tool_call(
    id: str, function: str, arguments: str, tools: list[ToolInfo]
) -> ToolCall:
    error: str | None = None
    arguments_dict: dict[str, Any] = {}

    def report_parse_error(ex: Exception) -> None:
        nonlocal error
        error = f"Error parsing the following tool call arguments:\n\n{arguments}\n\nError details: {ex}"
        logger.info(error)

    # if the arguments is a dict, then handle it with a plain json.loads
    arguments = arguments.strip()
    if arguments.startswith("{"):
        try:
            arguments_dict = json.loads(arguments)
        except json.JSONDecodeError as ex:
            report_parse_error(ex)

    # otherwise parse it as yaml (which will pickup unquoted strings, numbers, and true/false)
    # and then create a dict that maps it to the first function argument
    else:
        tool_info = next(
            (
                tool
                for tool in tools
                if tool.name == function and len(tool.parameters.properties) > 0
            ),
            None,
        )
        if tool_info:
            param_names = list(tool_info.parameters.properties.keys())
            try:
                value = yaml.safe_load(arguments)
                arguments_dict[param_names[0]] = value
            except yaml.error.YAMLError:
                # If the yaml parser fails, we treat it as a string argument.
                arguments_dict[param_names[0]] = arguments

    # return ToolCall with error payload
    return ToolCall(
        id=id,
        function=function,
        arguments=arguments_dict,
        type="function",
        parse_error=error,
    )
