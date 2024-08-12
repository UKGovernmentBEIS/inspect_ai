import json
import re
from logging import getLogger

from typing_extensions import override

from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo

from ..._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
)
from .chatapi import ChatAPIHandler, ChatAPIMessage
from .util import parse_tool_call, tool_parse_error_message

logger = getLogger(__name__)


# Llama 3.1 handler is based primarily on the tool calling conventions used by Ollama:
# (https://github.com/ollama/ollama/blob/main/server/testdata/tools/llama3-groq-tool-use.out)
#
# We initially tried the conventions promoted in the Llama 3.1 model card but
# this had severe problems with not formatting the function calls correctly
# (https://llama.meta.com/docs/model-cards-and-prompt-formats/llama3_1/#user-defined-custom-tool-calling)


class Llama31Handler(ChatAPIHandler):
    @override
    def input_with_tools(
        self, input: list[ChatMessage], tools: list[ToolInfo]
    ) -> list[ChatMessage]:
        available_tools = "\n\n".join(
            [tool.model_dump_json(exclude_none=True, indent=2) for tool in tools]
        )

        tool_prompt = f"""
You are a knowledgable assistant. You can answer questions and perform tasks. You are provided with function signatures within <tools></tools> XML tags. You may call one or more functions to assist with the user query. Don't make assumptions about what values to plug into functions. For each function call return a json object with function name and arguments within <tool_call></tool_call> XML tags as follows:

<tool_call>
{{"name": <function-name>,"arguments": <args-dict>}}
</tool_call>

Here are the available tools:

<tools>
{available_tools}
</tools>

Reminder:
- Function calls MUST follow the specified format, start with <tool_call> and end with </tool_call>
- Required parameters MUST be specified
- Only call one function at a time
- Put the entire function call reply on one line
- If there is no function call available, answer the question like normal with your current knowledge and do not tell the user about function calls
"""

        return [ChatMessageSystem(content=tool_prompt)] + input

    @override
    def parse_assistent_response(
        self, response: str, tools: list[ToolInfo]
    ) -> ChatMessageAssistant:
        tool_call_regex = "<tool_call>(.*?)</tool_call>"
        match = re.search(tool_call_regex, response)
        if match:
            # attempt to parse the json (report parseerror to model)
            (tool_call_content,) = match.groups()
            try:
                tool_call = json.loads(tool_call_content)
            except json.JSONDecodeError as ex:
                error_tool_call = ToolCall(
                    id="unknown",
                    function="unknown",
                    arguments={},
                    type="function",
                    parse_error=tool_parse_error_message(str(tool_call_content), ex),
                )
                return ChatMessageAssistant(
                    content="", tool_calls=[error_tool_call], source="generate"
                )

            # if we got the right payload then extract the tool calls
            if isinstance(tool_call, dict):
                name = tool_call.get("name", None)
                arguments = tool_call.get("arguments", None)
                if name and arguments:
                    return ChatMessageAssistant(
                        content="",
                        tool_calls=[
                            parse_tool_call(name, name, json.dumps(arguments), tools)
                        ],
                        source="generate",
                    )
                else:
                    logger.info(
                        f"Required 'name' and 'arguments' fields not in tool call: {tool_call}"
                    )
                    return ChatMessageAssistant(content=response)
            else:
                logger.info(f"Tool call was not a dictionary: {tool_call}")
                return ChatMessageAssistant(content=response)
        else:
            return ChatMessageAssistant(content=response)

    @override
    def assistant_message(self, message: ChatMessageAssistant) -> ChatAPIMessage:
        if message.tool_calls:
            content = "\n\n".join(
                [
                    f'<tool_call>{{"name": "{tool.function}", "arguments": {json.dumps(tool.arguments)} }}</tool_call>'
                    for tool in message.tool_calls
                ]
            )
        else:
            content = message.text

        return {"role": "assistant", "content": content}

    @override
    def tool_message(self, message: ChatMessageTool) -> ChatAPIMessage:
        return {
            "role": "tool",
            "content": f"Error: {message.error.message}"
            if message.error
            else message.text,
        }
