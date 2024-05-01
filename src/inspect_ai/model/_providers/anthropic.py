import ast
import builtins
import os
import re
from copy import deepcopy
from typing import Any, Tuple, cast
from xml.sax.saxutils import escape

from anthropic import (
    APIConnectionError,
    AsyncAnthropic,
    AsyncAnthropicBedrock,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
from anthropic._types import NOT_GIVEN
from anthropic.types import (
    ImageBlockParam,
    Message,
    MessageParam,
    TextBlock,
    TextBlockParam,
)
from anthropic.types.beta.tools import ToolParam as BetaToolParam
from anthropic.types.beta.tools import (
    ToolResultBlockParam,
    ToolsBetaMessage,
    ToolsBetaMessageParam,
    ToolUseBlock,
    ToolUseBlockParam,
)
from anthropic.types.beta.tools.tool_param import (
    InputSchema,
)
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_RETRIES, DEFAULT_MAX_TOKENS
from inspect_ai._util.error import exception_message
from inspect_ai._util.images import image_as_data_uri
from inspect_ai._util.json import json_type_to_python_type
from inspect_ai._util.url import data_uri_mime_type, data_uri_to_base64, is_data_uri
from inspect_ai.model._providers.util import model_base_url

from .._model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    Content,
    ContentText,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .._tool import ToolCall, ToolChoice, ToolFunction, ToolInfo, ToolParam
from .._util import chat_api_tool

ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"


class AnthropicAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        config: GenerateConfig = GenerateConfig(),
        bedrock: bool = False,
        tools_beta: bool = True,
        **model_args: Any,
    ):
        super().__init__(model_name=model_name, base_url=base_url, config=config)

        self.tools_beta = tools_beta and not bedrock

        # create client
        if bedrock:
            base_url = model_base_url(
                base_url, ["ANTHROPIC_BEDROCK_BASE_URL", "BEDROCK_ANTHROPIC_BASE_URL"]
            )

            self.client: AsyncAnthropic | AsyncAnthropicBedrock = AsyncAnthropicBedrock(
                base_url=base_url,
                max_retries=(
                    config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES
                ),
                **model_args,
            )
        else:
            # resolve api_key
            api_key = os.environ.get(ANTHROPIC_API_KEY, None)
            if api_key is None:
                raise ValueError(f"{ANTHROPIC_API_KEY} environment variable not found.")
            self.api_key = api_key
            base_url = model_base_url(base_url, "ANTHROPIC_BASE_URL")
            self.client = AsyncAnthropic(
                base_url=base_url,
                api_key=self.api_key,
                max_retries=(
                    config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES
                ),
                **model_args,
            )

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # generate
        try:
            # use tools beta endpoint if we have tools and haven't opted out (note that
            # bedrock is an implicit opt-out as it doesn't yet support the tools api
            if (
                len(tools) > 0
                and self.tools_beta
                and not isinstance(self.client, AsyncAnthropicBedrock)
            ):
                (
                    system_message,
                    beta_tools,
                    beta_messages,
                ) = await resolve_tools_beta_chat_input(
                    input, tools, tool_choice, config
                )

                message = await self.client.beta.tools.messages.create(
                    stream=False,
                    messages=beta_messages,
                    system=system_message if system_message is not None else NOT_GIVEN,
                    stop_sequences=(
                        config.stop_seqs if config.stop_seqs is not None else NOT_GIVEN
                    ),
                    tools=beta_tools,
                    **self.completion_params(config),
                )

                return tools_beta_model_output_from_message(message, tools)

            # otherwise use standard chat endpoint
            else:
                system_message, stop_seq, messages = await resolve_chat_input(
                    input, tools, config
                )

                message = await self.client.messages.create(
                    stream=False,
                    messages=messages,
                    system=system_message if system_message is not None else NOT_GIVEN,
                    stop_sequences=stop_seq if stop_seq is not None else NOT_GIVEN,
                    **self.completion_params(config),
                )

                # extract model output from text response (may have tool calls)
                return model_output_from_message(message, tools)

        except BadRequestError as ex:
            return ModelOutput.from_content(
                model=self.model_name,
                content="Sorry, but I can't assist with that",
                stop_reason="content_filter",
                error=exception_message(ex),
            )

    def completion_params(self, config: GenerateConfig) -> dict[str, Any]:
        return dict(
            model=self.model_name,
            max_tokens=cast(int, config.max_tokens),
            temperature=(
                config.temperature if config.temperature is not None else NOT_GIVEN
            ),
            top_p=config.top_p if config.top_p is not None else NOT_GIVEN,
            top_k=config.top_k if config.top_k is not None else NOT_GIVEN,
            timeout=float(config.timeout) if config.timeout is not None else NOT_GIVEN,
        )

    @override
    def max_tokens(self) -> int | None:
        # anthropic requires you to expicitly specify max_tokens (most others
        # set it to the maximum allowable output tokens for the model).
        return DEFAULT_MAX_TOKENS

    @override
    def connection_key(self) -> str:
        return self.api_key

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        # We have observed that anthropic will frequently return InternalServerError
        # seeminly in place of RateLimitError (at the very least the errors seem to
        # always be transient). Equating this to rate limit errors may occationally
        # result in retrying too many times, but much more often will avert a failed
        # eval that just needed to survive a transient error
        return (
            isinstance(ex, RateLimitError)
            or isinstance(ex, InternalServerError)
            or isinstance(ex, APIConnectionError)
        )

    @override
    def collapse_user_messages(self) -> bool:
        return True


#######################################################################################
# Resolve input, tools, and config into the right shape of input for the Anthropic
# tool use beta. we also keep the legacy tools implementation around for now (see below)
# for users on Bedrock of who want to opt out for tools beta for any reason
#######################################################################################


async def resolve_tools_beta_chat_input(
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
) -> Tuple[str | None, list[BetaToolParam], list[ToolsBetaMessageParam]]:
    # extract system message
    system_message, messages = split_system_message(input, config)

    # some special handling for tools
    if len(tools) > 0:
        # encourage claude to show its thinking, see
        # https://docs.anthropic.com/claude/docs/tool-use#chain-of-thought-tool-use
        system_message = f"{system_message}\n\nBefore answering, explain your reasoning step-by-step."

        # implement tool_choice by appending to the last user message, see
        # https://docs.anthropic.com/claude/docs/tool-use#forcing-tool-use
        if isinstance(tool_choice, ToolFunction):
            messages = deepcopy(messages)
            message = next(
                (
                    message
                    for message in reversed(messages)
                    if isinstance(message, ChatMessageUser)
                ),
                None,
            )
            if message:
                message.text = (
                    f"{message.text} Use the {tool_choice.name} tool in your response."
                )

    # messages
    beta_messages = [(await tools_beta_message_param(message)) for message in messages]

    # tools
    chat_functions = [chat_api_tool(tool)["function"] for tool in tools]
    beta_tools = [
        BetaToolParam(
            name=function["name"],
            description=function["description"],
            input_schema=cast(InputSchema, function["parameters"]),
        )
        for function in chat_functions
    ]

    return system_message, beta_tools, beta_messages


async def tools_beta_message_param(message: ChatMessage) -> ToolsBetaMessageParam:
    # no system role for anthropic (this is more like an asseration,
    # as these should have already been filtered out)
    if message.role == "system":
        raise ValueError("Antropic models do not support the system role")

    # "tool" means serving a tool call result back to claude
    elif message.role == "tool":
        if message.tool_error is not None:
            content: str | list[TextBlockParam] = message.tool_error
        if isinstance(message.content, str):
            content = [TextBlockParam(type="text", text=message.content)]
        else:
            content = [
                TextBlockParam(type="text", text=content.text)
                for content in message.content
                if isinstance(content, ContentText)
            ]

        return ToolsBetaMessageParam(
            role="user",
            content=[
                ToolResultBlockParam(
                    tool_use_id=str(message.tool_call_id),
                    type="tool_result",
                    content=content,
                    is_error=message.tool_error is not None,
                )
            ],
        )

    # tool_calls means claude is attempting to call our tools
    elif message.role == "assistant" and message.tool_calls:
        # first include content (claude <thinking>)
        tools_content: list[TextBlockParam | ImageBlockParam | ToolUseBlockParam] = (
            [TextBlockParam(type="text", text=message.content)]
            if isinstance(message.content, str)
            else (
                [(await message_param_content(content)) for content in message.content]
            )
        )

        # now add tools
        for tool_call in message.tool_calls:
            tools_content.append(
                ToolUseBlockParam(
                    type="tool_use",
                    id=tool_call.id,
                    name=tool_call.function,
                    input=tool_call.arguments,
                )
            )

        return ToolsBetaMessageParam(
            role=message.role,
            content=tools_content,
        )

    # normal text content
    elif isinstance(message.content, str):
        return ToolsBetaMessageParam(role=message.role, content=message.content)

    # mixed text/images
    else:
        return ToolsBetaMessageParam(
            role=message.role,
            content=[
                await message_param_content(content) for content in message.content
            ],
        )


def tools_beta_model_output_from_message(
    message: ToolsBetaMessage, tools: list[ToolInfo]
) -> ModelOutput:
    # extract content and tool calls
    content: list[Content] = []
    tool_calls: list[ToolCall] | None = None

    for content_block in message.content:
        if isinstance(content_block, TextBlock):
            # if this was a tool call then remove <result></result> tags that
            # claude sometimes likes to insert!
            content_text = content_block.text
            if len(tools) > 0:
                content_text = content_text.replace("<result>", "").replace(
                    "</result>", ""
                )
            content.append(ContentText(type="text", text=content_text))
        elif isinstance(content_block, ToolUseBlock):
            tool_calls = tool_calls or []
            tool_calls.append(
                ToolCall(
                    type="function",
                    id=content_block.id,
                    function=content_block.name,
                    arguments=content_block.model_dump().get("input", {}),
                )
            )

    # resolve choice
    choice = ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=content, tool_calls=tool_calls, source="generate"
        ),
        stop_reason=tools_beta_message_stop_reason(message),
    )

    # return ModelOutput
    return ModelOutput(
        model=message.model,
        choices=[choice],
        usage=ModelUsage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            total_tokens=message.usage.input_tokens + message.usage.output_tokens,
        ),
    )


def tools_beta_message_stop_reason(message: ToolsBetaMessage) -> StopReason:
    match message.stop_reason:
        case "end_turn" | "stop_sequence":
            return "stop"
        case "max_tokens":
            return "length"
        case "tool_use":
            return "tool_calls"
        case _:
            return "unknown"


def split_system_message(
    input: list[ChatMessage], config: GenerateConfig
) -> Tuple[str | None, list[ChatMessage]]:
    # split messages
    system_messages = [m for m in input if isinstance(m, ChatMessageSystem)]
    messages = [m for m in input if not isinstance(m, ChatMessageSystem)]

    # build system message
    system_message = (
        "\n\n".join([message.text for message in system_messages])
        if len(system_messages) > 0
        else None
    )

    # prepend any config based system message
    if config.system_message:
        system_message = f"{config.system_message}\n\n{system_message}"

    # return
    return system_message, cast(list[ChatMessage], messages)


#######################################################################################
# Resolve input, tools, and config into the right shape of input for Anthropic models.
#
# Anthropic tools are defined not using a tools component of their API, but rather by
# defineing all available tools in the system message. If there are tools then there
# is also a requirement to define a custom stop sequence. This fucntion sorts all of
# that out and returns a system message, a stop sequence (if necessary) and the list
# of anthropic-native MessageParam objects (including converting role="tool" messages
# into XML encoded role="user" messages for Claude
#######################################################################################

FUNCTIONS_STOP_SEQ = "</function_calls>"


async def resolve_chat_input(
    input: list[ChatMessage], tools: list[ToolInfo], config: GenerateConfig
) -> Tuple[str | None, list[str] | None, list[MessageParam]]:
    # extract system message
    system_message, messages = split_system_message(input, config)

    # resolve tool use (system message and stop sequences)
    stop_seqs = deepcopy(config.stop_seqs)
    if len(tools) > 0:
        system_message = f"{system_message}\n\n{tools_system_message(tools)}"
        stop_seqs = (
            config.stop_seqs if config.stop_seqs else ["\n\nHuman:", "\n\nAssistant"]
        )
        stop_seqs.append(FUNCTIONS_STOP_SEQ)

    # create anthropic message params
    message_params = [await message_param(m) for m in messages]

    # done!
    return system_message, stop_seqs, message_params


def tools_system_message(tools: list[ToolInfo]) -> str:
    tool_sep = "\n\n"
    return f"""
In this environment you have access to a set of tools you can use to answer the user's question.

You may call them like this:
<function_calls>
<invoke>
<tool_name>$TOOL_NAME</tool_name>
<parameters>
<$PARAMETER_NAME>$PARAMETER_VALUE</$PARAMETER_NAME>
...
</parameters>
</invoke>
</function_calls>

Here are the tools available:
<tools>
{tool_sep.join([tool_description(tool) for tool in tools])}
</tools>
"""


def tool_description(tool: ToolInfo) -> str:
    newline = "\n"
    return f"""
<tool_description>
<tool_name>{escape(tool.name)}</tool_name>
<description>{escape(tool.description)}</description>
<parameters>
{newline.join(tool_param(param) for param in tool.params)}
</parameter>
</tool_description>
"""


def tool_param(param: ToolParam) -> str:
    return f"""
<parameter>
<name>{escape(param.name)}</name>
<type>{escape(param.type)}</type>
<description>{escape(param.description)}</description>
</parameter>
"""


async def message_param(message: ChatMessage) -> MessageParam:
    # no system role for anthropic (this is more like an assertion,
    # as these should have already been filtered out)
    if message.role == "system":
        raise ValueError("Antropic models do not support the system role")

    # "tool" means serving a tool call result back to claude
    elif message.role == "tool":
        return tool_message_param(message)

    # tool_calls means claude is attempting to call our tools
    elif message.role == "assistant" and message.tool_calls:
        return MessageParam(
            role=message.role,
            content=f"{message.content}\n{function_calls(message.tool_calls)}",
        )

    # normal text content
    elif isinstance(message.content, str):
        return MessageParam(role=message.role, content=message.content)

    # mixed text/images
    else:
        return MessageParam(
            role=message.role,
            content=[
                await message_param_content(content) for content in message.content
            ],
        )


async def message_param_content(
    content: Content,
) -> TextBlockParam | ImageBlockParam:
    if isinstance(content, ContentText):
        return TextBlockParam(type="text", text=content.text)
    else:
        # resolve to url
        image = content.image
        if not is_data_uri(image):
            image = await image_as_data_uri(image)

        # resolve mime type and base64 content
        media_type = data_uri_mime_type(image) or "image/png"
        image = data_uri_to_base64(image)

        if media_type not in ["image/jpeg", "image/png", "image/gif", "image/webp"]:
            raise ValueError(f"Unable to read image of type {media_type}")

        return ImageBlockParam(
            type="image",
            source=dict(type="base64", media_type=cast(Any, media_type), data=image),
        )


def tool_message_param(message: ChatMessageTool) -> MessageParam:
    results = f"""
<function_results>
{function_result(message)}
</function_results>
"""
    return MessageParam(role="user", content=results)


def function_calls(tool_calls: list[ToolCall]) -> str:
    nl = "\n"
    return f"""
<function_calls>
{nl.join([function_call(tool_call) for tool_call in tool_calls])}
</function_calls>
"""


def function_call(tool_call: ToolCall) -> str:
    nl = "\n"
    return f"""
<invoke>
<tool_name>{escape(tool_call.function)}</tool_name>
<parameters>
{nl.join([function_parameter(name,value) for name, value in tool_call.arguments.items()])}
</parameters>
</invoke>
"""


def function_parameter(name: str, value: Any) -> str:
    return f"<{name}>{value}</{name}>"


def function_result(message: ChatMessageTool) -> str:
    if message.tool_error:
        return f"""
<system>
{escape(message.tool_error)}
</system>
"""
    else:
        return f"""
<result>
<tool_name>{escape(str(message.tool_call_id))}</tool_name>
<stdout>
{escape(message.text)}
</stdout>
</result>
"""


#######################################################################################
# Extract model output (including tool calls) from an Anthropic message
#
# Anthropic encodes tool calls (in XML) directly in role="assistant" messages. The
# code below deals with this by parsing out the tool calls and separating them into
# the Inspect native ToolCall objects.
#######################################################################################


def model_output_from_message(message: Message, tools: list[ToolInfo]) -> ModelOutput:
    # extract function calls (if any); throws ValueError if xml is invalid
    try:
        content_with_functions = extract_function_calls(message)
        if content_with_functions:
            content = content_with_functions.content
            tool_calls = [
                tool_call(function_call, tools)
                for function_call in content_with_functions.function_calls
            ]
        else:
            content = message_content(message)
            tool_calls = None
    except ValueError as ex:
        return ModelOutput.from_content(
            message.model,
            f"{message_content(message)}\n\nError: {exception_message(ex)}",
        )

    # resolve choice
    choice = ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=content, tool_calls=tool_calls, source="generate"
        ),
        stop_reason=message_stop_reason(message),
    )

    # return ModelOutput
    return ModelOutput(
        model=message.model,
        choices=[choice],
        usage=ModelUsage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            total_tokens=message.usage.input_tokens + message.usage.output_tokens,
        ),
    )


def message_stop_reason(message: Message) -> StopReason:
    match message.stop_reason:
        case "end_turn":
            return "stop"
        case "max_tokens":
            return "length"
        case "stop_sequence":
            if message.stop_sequence == FUNCTIONS_STOP_SEQ:
                return "tool_calls"
            else:
                return "stop"
        case _:
            return "unknown"


# This function call parsing code is adapted from the anthropic-tools package (which is in "alpha"
# and not on PyPI, This will likely end up in the main anthropic package -- when that happens we'll
# switch to using that. Here is the commit we forked:
# https://github.com/anthropics/anthropic-tools/blob/a7822678db8a0867b1d05da9c836c456d263e3d9/tool_use_package/tool_user.py#L243


class FunctionCall:
    def __init__(self, function: str, parameters: list[tuple[str, str]]) -> None:
        self.function = function
        self.parameters = parameters


def message_content(message: Message) -> str:
    return "\n".join([content.text for content in message.content])


class ContentWithFunctionCalls:
    def __init__(
        self,
        content: str,
        function_calls: list[FunctionCall],
    ) -> None:
        self.content = content
        self.function_calls = function_calls


def extract_function_calls(message: Message) -> ContentWithFunctionCalls | None:
    content = message_content(message)

    # see if we need to append the </function_calls> stop token
    if (
        message.stop_reason == "stop_sequence"
        and message.stop_sequence == "</function_calls>"
    ):
        content = f"{content}</function_calls>"

    """Check if the function call follows a valid format and extract the attempted function calls if so.
    Does not check if the tools actually exist or if they are called with the requisite params."""
    # Check if there are any of the relevant XML tags present that would indicate an attempted function call.
    function_call_tags = re.findall(
        r"<function_calls>|</function_calls>|<invoke>|</invoke>|<tool_name>|</tool_name>|<parameters>|</parameters>",
        content,
        re.DOTALL,
    )
    if not function_call_tags:
        return None

    # Extract content between <function_calls> tags. If there are multiple we will only parse the first and ignore the rest, regardless of their correctness.
    match = re.search(r"<function_calls>(.*)</function_calls>", content, re.DOTALL)
    if not match:
        return None
    func_calls = match.group(1)

    # get content appearing before the function calls
    prefix_match = re.search(r"^(.*?)<function_calls>", content, re.DOTALL)
    if prefix_match:
        func_call_prefix_content = prefix_match.group(1)

    # Check for invoke tags
    invoke_regex = r"<invoke>.*?</invoke>"
    if not re.search(invoke_regex, func_calls, re.DOTALL):
        raise ValueError(
            "Missing <invoke></invoke> tags inside of <function_calls></function_calls> tags."
        )

    # Check each invoke contains tool name and parameters
    invoke_strings = re.findall(invoke_regex, func_calls, re.DOTALL)
    invokes: list[FunctionCall] = []
    for invoke_string in invoke_strings:
        tool_name = re.findall(r"<tool_name>.*?</tool_name>", invoke_string, re.DOTALL)
        if not tool_name:
            raise ValueError(
                "Missing <tool_name></tool_name> tags inside of <invoke></invoke> tags."
            )

        if len(tool_name) > 1:
            raise ValueError(
                "More than one tool_name specified inside single set of <invoke></invoke> tags."
            )

        parameters = re.findall(
            r"<parameters>.*?</parameters>", invoke_string, re.DOTALL
        )
        if not parameters:
            raise ValueError(
                "Missing <parameters></paraeters> tags inside of <invoke></invoke> tags."
            )

        if len(parameters) > 1:
            raise ValueError(
                "More than one set of <parameters></parameters> tags specified inside single set of <invoke></invoke> tags."
            )

        # Check for balanced tags inside parameters
        # TODO: This will fail if the parameter value contains <> pattern or if there is a parameter called parameters. Fix that issue.
        tags = re.findall(
            r"<.*?>",
            parameters[0].replace("<parameters>", "").replace("</parameters>", ""),
            re.DOTALL,
        )
        if len(tags) % 2 != 0:
            raise ValueError("Imbalanced tags inside <parameters></parameters> tags.")

        # Loop through the tags and check if each even-indexed tag matches the tag in the position after it (with the / of course).
        # If valid store their content for later use.
        # TODO: Add a check to make sure there aren't duplicates provided of a given parameter.
        parameters_with_values = []
        for i in range(0, len(tags), 2):
            opening_tag = tags[i]
            closing_tag = tags[i + 1]
            closing_tag_without_second_char = closing_tag[:1] + closing_tag[2:]
            if closing_tag[1] != "/" or opening_tag != closing_tag_without_second_char:
                raise ValueError(
                    "Non-matching opening and closing tags inside <parameters></parameters> tags."
                )

            match_param = re.search(
                rf"{opening_tag}(.*?){closing_tag}", parameters[0], re.DOTALL
            )
            if match_param:
                parameters_with_values.append((opening_tag[1:-1], match_param.group(1)))

        # Parse out the full function call
        invokes.append(
            FunctionCall(
                tool_name[0].replace("<tool_name>", "").replace("</tool_name>", ""),
                parameters_with_values,
            )
        )

    return ContentWithFunctionCalls(func_call_prefix_content, invokes)


#######################################################################################
# Thse functions deal with converting Anthropic <function_call> to our native ToolCall
#######################################################################################


def tool_call(invoke: FunctionCall, tools: list[ToolInfo]) -> ToolCall:
    tool_def = next((tool for tool in tools if invoke.function == tool.name), None)
    return ToolCall(
        id=invoke.function,
        function=invoke.function,
        arguments=tool_arguments(invoke.parameters, tool_def),
        type="function",
    )


def tool_arguments(
    params: list[tuple[str, str]], tool_info: ToolInfo | None
) -> dict[str, Any]:
    arguments: dict[str, Any] = dict()
    for param in params:
        # get params
        name, value = param

        # coerce type if we have a tool_def
        if tool_info:
            type_str = next(
                (param.type for param in tool_info.params if param.name == name), None
            )
            if type_str:
                value = tool_argument_value(value, type_str)

        arguments[name] = value

    return arguments


def tool_argument_value(value: Any, type_str: str) -> Any:
    """Convert a string value into its appropriate Python data type based on the provided type string.

    Arg:
        value: the value to convert
        type_str: the type to convert the value to
    Returns:
        The value converted into the requested type or the original value
        if the conversion failed.
    """
    type_str = json_type_to_python_type(type_str)
    if type_str in ("list", "dict"):
        return ast.literal_eval(value)
    type_class = getattr(builtins, type_str)
    try:
        return type_class(value)
    except ValueError:
        return value
