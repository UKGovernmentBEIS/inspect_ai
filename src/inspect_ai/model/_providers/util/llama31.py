import json
import re
import textwrap
from logging import getLogger

from shortuuid import uuid
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

TOOL_CALL = "tool_call"


class Llama31Handler(ChatAPIHandler):
    @override
    def input_with_tools(
        self, input: list[ChatMessage], tools: list[ToolInfo]
    ) -> list[ChatMessage]:
        # JSON schema for available tools
        available_tools = "\n\n".join(
            [tool.model_dump_json(exclude_none=True, indent=2) for tool in tools]
        )

        # tool prompt
        tool_prompt = textwrap.dedent(
            f"""
            You are a knowledgable assistant. You can answer questions and perform tasks. You are provided with function signatures within <tools></tools> XML tags. You may call one or more functions to assist with the user query. Don't make assumptions about what values to plug into functions. For each function call return a json object with function name and arguments within <{TOOL_CALL}></{TOOL_CALL}> XML tags as follows:

            <{TOOL_CALL}>
            {{"name": <function-name>,"arguments": <args-dict>}}
            </{TOOL_CALL}>

            Here are the available tools defined in JSON Schema:

            <tools>
            {available_tools}
            </tools>

            Reminder:
            - Function calls MUST follow the specified format, start with <{TOOL_CALL}> and end with </{TOOL_CALL}>.
            - Please call only one function at a time.
            - It's fine to include some reasoning about which function to call and why.
            - Please ensure that </{TOOL_CALL}> is the last content in the message (there should be no text after it).
            - Please be absolutely sure that the function name you have specified matches one of the functions described in <tools>.
            - All function parameters MUST be specified.
            - If there is no function call available, answer the question like normal with your current knowledge and do not tell the user about function calls
            """
        )

        return [ChatMessageSystem(content=tool_prompt)] + input

    @override
    def parse_assistant_response(
        self, response: str, tools: list[ToolInfo]
    ) -> ChatMessageAssistant:
        """Parse content and tool calls from a model response.

        This method has an interdependency with `input_with_tools()` (as that is the
        prompt that asks the model to use the <tool_call>...</tool_call> syntax)
        """
        # extract tool calls
        tool_call_regex = rf"<{TOOL_CALL}>((?:.|\n)*?)</{TOOL_CALL}>"
        tool_calls_content: list[str] = re.findall(tool_call_regex, response)

        # if there are tool calls proceed with parsing
        if len(tool_calls_content) > 0:
            # parse each tool call (if there are parsing error that occur
            # this will be reported in the `parse_error` field of the ToolCall
            # and ultimately reported back to the model)
            tool_calls = [
                parse_tool_call_content(content, tools)
                for content in tool_calls_content
            ]

            # find other content that exists outside tool calls
            tool_call_content_regex = rf"<{TOOL_CALL}>(?:.|\n)*?</{TOOL_CALL}>"
            other_content = re.split(tool_call_content_regex, response, flags=re.DOTALL)
            other_content = [
                str(content).strip()
                for content in other_content
                if str(content).strip()
            ]
            content = "\n\n".join(other_content)

            # return the message
            return ChatMessageAssistant(
                content=filter_assistant_header(content),
                tool_calls=tool_calls,
                source="generate",
            )

        # otherwise this is just an ordinary assistant message
        else:
            return ChatMessageAssistant(
                content=filter_assistant_header(response), source="generate"
            )

    @override
    def assistant_message(self, message: ChatMessageAssistant) -> ChatAPIMessage:
        if message.tool_calls:
            content = "\n\n".join(
                [message.text]
                + [
                    f'<tool_call>{{"name": "{tool.function}", "arguments": {json.dumps(tool.arguments)} }}</tool_call>'
                    for tool in message.tool_calls
                ]
            ).strip()
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


def parse_tool_call_content(content: str, tools: list[ToolInfo]) -> ToolCall:
    """Attempt to parse content from inside <tool_call> tags.

    Content inside a <tool_call> should be a JSON dictionary with `name` and
    `arguments` (which in turn should be a `dict[str,Any]` but in some cases
    we've seen models pass `str`). This function attempts to extract this from
    the passed tcontentext. A `ToolCall` is returned for all cases (if the
    parsing fails then it will have a `parse_error`, which will be subsequently
    reported to the model.
    """
    try:
        # parse raw JSON
        tool_call_data = json.loads(content)

        # if its not a dict then report error
        if not isinstance(tool_call_data, dict):
            raise ValueError("The provided arguments are not a JSON dictionary.")

        # see if we can get the fields (if not report error)
        name = tool_call_data.get("name", None)
        arguments = tool_call_data.get("arguments", None)
        if not name or not arguments:
            raise ValueError(
                "Required 'name' and 'arguments' not provided in JSON dictionary."
            )

        # now perform the parse (we need to call thi function because it includes
        # the special handling to for mapping arguments that are a plain `str`
        # to the first parameter of the function)
        unique_id = f"{name}_{uuid()}"
        return parse_tool_call(unique_id, name, json.dumps(arguments), tools)

    except Exception as ex:
        # buld error message
        parse_error = tool_parse_error_message(content, ex)

        # log it to 'info'
        logger.info(parse_error)

        # notify model
        return ToolCall(
            id="unknown",
            function="unknown",
            arguments={},
            type="function",
            parse_error=parse_error,
        )


def filter_assistant_header(message: str) -> str:
    return re.sub(r"<\|start_header_id\|>assistant<\|end_header_id\|>", "", message)
