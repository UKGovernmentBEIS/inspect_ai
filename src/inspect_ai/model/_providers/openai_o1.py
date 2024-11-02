import json
import re
import textwrap
from logging import getLogger
from typing import Any

from openai import AsyncOpenAI, BadRequestError
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionUserMessageParam,
)
from shortuuid import uuid
from typing_extensions import override

from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ModelOutput,
)
from inspect_ai.tool import ToolCall, ToolInfo

from .._model_call import ModelCall
from .._model_output import ModelUsage
from .._providers.util import (
    ChatAPIHandler,
    ChatAPIMessage,
    as_stop_reason,
    chat_api_input,
    parse_tool_call,
    tool_parse_error_message,
)

logger = getLogger(__name__)


async def generate_o1(
    client: AsyncOpenAI,
    model: str,
    input: list[ChatMessage],
    tools: list[ToolInfo],
    **params: Any,
) -> ModelOutput | tuple[ModelOutput, ModelCall]:
    # create chatapi handler
    handler = O1PreviewChatAPIHandler()

    # map max_tokens => max_completion_tokens
    max_tokens = params.get("max_tokens", None)
    if max_tokens:
        params["max_completion_tokens"] = max_tokens
        del params["max_tokens"]

    # call model
    request = dict(
        model=model,
        messages=chat_messages(input, tools, handler),
        **params,
    )
    try:
        response: ChatCompletion = await client.chat.completions.create(**request)
    except BadRequestError as ex:
        return handle_bad_request(model, ex)

    # return model output
    return ModelOutput(
        model=response.model,
        choices=chat_choices_from_response(response, tools, handler),
        usage=ModelUsage(
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
        )
        if response.usage
        else None,
    ), ModelCall.create(
        request=request,
        response=response.model_dump(),
    )


def handle_bad_request(model: str, ex: BadRequestError) -> ModelOutput:
    if ex.code == "invalid_prompt":
        return ModelOutput.from_content(
            model=model, content=str(ex), stop_reason="content_filter"
        )
    else:
        raise ex


def chat_messages(
    input: list[ChatMessage], tools: list[ToolInfo], handler: ChatAPIHandler
) -> list[ChatCompletionMessageParam]:
    # o1 does not allow system messages so convert system -> user
    messages: list[ChatMessage] = [
        ChatMessageUser(content=message.content)
        if message.role == "system"
        else message
        for message in input
    ]

    # prepare input for REST style chat API (including presenting tools to the
    # model in the fashion designated by the ChatAPIHandler)
    chat_messages = chat_api_input(messages, tools, handler)

    # convert these REST style chat messages to OpenAI message dicts
    return [chat_message(message) for message in chat_messages]


def chat_message(message: ChatAPIMessage) -> ChatCompletionMessageParam:
    if message["role"] == "user":
        return ChatCompletionUserMessageParam(role="user", content=message["content"])
    elif message["role"] == "assistant":
        return ChatCompletionAssistantMessageParam(
            role="assistant", content=message["content"]
        )
    # the handler should have already ensured that there are no system or tool messages
    else:
        raise ValueError(f"Unexpected message role: {message.get('role')}")


def chat_choices_from_response(
    response: ChatCompletion, tools: list[ToolInfo], handler: ChatAPIHandler
) -> list[ChatCompletionChoice]:
    choices = list(response.choices)
    choices.sort(key=lambda c: c.index)
    return [
        # the assistant message might include a tool call so we call the
        # ChatAPIHandler to parse it and sort this out
        ChatCompletionChoice(
            message=handler.parse_assistant_response(
                choice.message.content or "", tools
            ),
            stop_reason=as_stop_reason(choice.finish_reason),
        )
        for choice in choices
    ]


TOOL_CALL = "tool_call"


class O1PreviewChatAPIHandler(ChatAPIHandler):
    @override
    def input_with_tools(
        self, input: list[ChatMessage], tools: list[ToolInfo]
    ) -> list[ChatMessage]:
        """Prepare model input with tool definitions.

        In this implementation we borrow the technique used by Ollama to implement OpenAI
        compatible tool calling for Llama3.1 models. Tool definitions are prepended as a
        user message to the `input` messages.
        """
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

        # return the tool prompt prepended to the input messages
        return [ChatMessageUser(content=tool_prompt)] + input

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
                content=content, tool_calls=tool_calls, source="generate"
            )

        # otherwise this is just an ordinary assistant message
        else:
            return ChatMessageAssistant(content=response, source="generate")

    @override
    def assistant_message(self, message: ChatMessageAssistant) -> ChatAPIMessage:
        """Construct a chat REST API message from an assistant message.

        This method is called by `chat_api_input()` to convert assistant messages to
        something the model will recognize. Therefore, iff the message has tool calls,
        we need to reconstruct the native assistant tool calling syntax (as such this
        method also has an interdependency with `input_with_tools()`).
        """
        # for tool calls, join any message text with the calls in <tool_call> form
        if message.tool_calls:
            content = "\n\n".join(
                [message.text]
                + [
                    f'<{TOOL_CALL}>{{"name": "{tool.function}", "arguments": {json.dumps(tool.arguments)} }}</{TOOL_CALL}>'
                    for tool in message.tool_calls
                ]
            )

        # normal message, just get the text
        else:
            content = message.text

        # return assistant message
        return {"role": "assistant", "content": content}

    @override
    def tool_message(self, message: ChatMessageTool) -> ChatAPIMessage:
        """Construct a chat REST API message from a tool message.

        o1 models do not support role="tool", so we need to present
        these as user messages that report the results of calls.
        """
        # might be an error in which case we prepend 'Error'
        results = f"Error: {message.error.message}" if message.error else message.text

        # try to clearly spell out that this 'user' message is the response to a function call
        content = f"The '{message.function}' function was called. The results are:\n\n{results}"

        # return user message
        return {"role": "user", "content": content}


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
        if (not name) or (arguments is None):
            raise ValueError(
                "Required 'name' and/or 'arguments' not provided in JSON dictionary."
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
