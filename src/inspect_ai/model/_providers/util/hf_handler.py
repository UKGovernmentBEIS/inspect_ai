import json
import re
from logging import getLogger

from shortuuid import uuid
from typing_extensions import override

from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo

from ..._chat_message import ChatMessageAssistant
from .chatapi import ChatAPIHandler
from .util import parse_tool_call, tool_parse_error_message

logger = getLogger(__name__)


# Hugging Face handler currently supports LLama, Mistral and Qwen models, but will
# work with any model that uses the same tool calling conventions


class HFHandler(ChatAPIHandler):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    @override
    def parse_assistant_response(
        self, response: str, tools: list[ToolInfo]
    ) -> ChatMessageAssistant:
        """Parse content and tool calls from a model response.

        This method has an interdependency with `input_with_tools()` (as that is the
        prompt that asks the model to use the <tool_call>...</tool_call> syntax)
        """
        # extract tool calls
        content, tool_calls_content = model_specific_tool_parse(
            response, self.model_name
        )
        # if there are tool calls proceed with parsing
        if len(tool_calls_content) > 0:
            # parse each tool call (if there are parsing error that occur
            # this will be reported in the `parse_error` field of the ToolCall
            # and ultimately reported back to the model)
            tool_calls = [
                parse_tool_call_content(content, tools)
                for content in tool_calls_content
            ]

            # return the message
            return ChatMessageAssistant(
                content=content,
                tool_calls=tool_calls,
                source="generate",
            )

        # otherwise this is just an ordinary assistant message
        else:
            return ChatMessageAssistant(
                content=filter_assistant_header(response), source="generate"
            )


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
        if "parameters" in tool_call_data:
            tool_call_data["arguments"] = tool_call_data.pop("parameters")

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


def model_specific_tool_parse(response: str, model_name: str) -> tuple[str, list[str]]:
    model_name = model_name.lower()

    if "llama" in model_name:
        if "name" in response and ("parameters" in response or "arguments" in response):
            function_calls, content = json_extract_raw(response)
        else:
            content = response
            function_calls = []
    elif "mistral" in model_name:
        if "name" in response and "arguments" in response:
            content = ""
            function_calls = [json.dumps(tool) for tool in json.loads(response)]
        else:
            content = response
            function_calls = []
    elif "qwen" in model_name and "coder" in model_name:
        if "name" in response and "arguments" in response:
            function_calls, content = json_extract(response)
        else:
            content = response
            function_calls = []
    elif "qwen" in model_name and "instruct" in model_name:
        if "name" in response and "arguments" in response:
            function_calls, content = xml_extract(response, "tool_call")
        else:
            content = response
            function_calls = []
    else:
        try:
            function_calls, content = parse_unknown_tool_calls(response)
        except Exception:
            raise ValueError(
                f"Unsupported model: {model_name}. No tool parsing implemented. Check if any of the current parsings work with your tool calling conventions and add the model name to the correct elif block."
            )
    return content, function_calls


def json_extract(raw_string: str) -> tuple[list[str], str]:
    """Extract tools in form ```json{...}``` and return the remaining content."""
    function_calls = re.findall(r"```json\s*(\{.*?\})\s*```", raw_string, re.DOTALL)

    remaining_content = re.sub(
        r"```json\s*\{.*?\}\s*```", "", raw_string, flags=re.DOTALL
    ).strip()

    return function_calls, remaining_content


def json_extract_raw(raw_string: str) -> tuple[list[str], str]:
    """Extract tools in form `{...}` and return the remaining content."""
    # Regex to extract sequences starting with '{' and ending with '}}'
    json_like_regex = r"\{.*?\}\}"
    function_calls = re.findall(json_like_regex, raw_string)
    remaining_content = re.sub(json_like_regex, "", raw_string).strip()

    return function_calls, remaining_content


def xml_extract(raw_string: str, tag: str) -> tuple[list[str], str]:
    """Extract tools in form <tag>{...}</tag> and return the remaining content."""
    tool_call_regex = rf"<{tag}>((?:.|\n)*?)</{tag}>"
    function_calls = re.findall(tool_call_regex, raw_string)
    tool_call_content_regex = rf"<{tag}>(?:.|\n)*?</{tag}>"
    other_content = re.split(tool_call_content_regex, raw_string, flags=re.DOTALL)
    other_content = [
        str(content).strip() for content in other_content if str(content).strip()
    ]
    content = "\n\n".join(other_content)
    return function_calls, content


def parse_unknown_tool_calls(response: str) -> tuple[list[str], str]:
    if "```json" in response:
        return json_extract(response)
    elif "<tool_call>" in response:
        return xml_extract(response, "tool_call")
    elif "<function>" in response:
        return xml_extract(response, "function")
    elif "{" in response and "}}" in response:
        return json_extract_raw(response)
    else:
        return [], response


def filter_assistant_header(message: str) -> str:
    return re.sub(r"<\|start_header_id\|>assistant<\|end_header_id\|>", "", message)
