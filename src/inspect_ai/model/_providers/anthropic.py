import functools
import os
from typing import Any, Literal, Tuple, cast

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
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlock,
    ToolUseBlockParam,
    message_create_params,
)
from anthropic.types.tool_param import (
    InputSchema,
)
from typing_extensions import override

from inspect_ai._util.constants import DEFAULT_MAX_RETRIES, DEFAULT_MAX_TOKENS
from inspect_ai._util.error import exception_message
from inspect_ai._util.images import image_as_data_uri
from inspect_ai._util.url import data_uri_mime_type, data_uri_to_base64, is_data_uri

from .._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageSystem
from .._content import Content, ContentText
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .._tool import ToolCall, ToolChoice, ToolFunction, ToolInfo
from .._util import chat_api_tool
from .util import model_base_url

ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"


class AnthropicAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None,
        config: GenerateConfig = GenerateConfig(),
        bedrock: bool = False,
        **model_args: Any,
    ):
        super().__init__(model_name=model_name, base_url=base_url, config=config)

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
            (system_message, tools_param, messages) = await resolve_chat_input(
                input, tools, config
            )

            message = await self.client.messages.create(
                stream=False,
                messages=messages,
                system=system_message if system_message is not None else NOT_GIVEN,
                stop_sequences=(
                    config.stop_seqs if config.stop_seqs is not None else NOT_GIVEN
                ),
                tools=tools_param,
                tool_choice=(
                    message_tool_choice(tool_choice) if len(tools) > 0 else NOT_GIVEN
                ),
                **self.completion_params(config),
            )

            return model_output_from_message(message, tools)

        except BadRequestError as ex:
            output = self.handle_bad_request(ex)
            if output:
                return output
            else:
                raise ex

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
        # anthropic requires you to explicitly specify max_tokens (most others
        # set it to the maximum allowable output tokens for the model).
        return DEFAULT_MAX_TOKENS

    @override
    def connection_key(self) -> str:
        return self.api_key

    @override
    def is_rate_limit(self, ex: BaseException) -> bool:
        # We have observed that anthropic will frequently return InternalServerError
        # seemingly in place of RateLimitError (at the very least the errors seem to
        # always be transient). Equating this to rate limit errors may occasionally
        # result in retrying too many times, but much more often will avert a failed
        # eval that just needed to survive a transient error
        return isinstance(ex, RateLimitError | InternalServerError | APIConnectionError)

    @override
    def collapse_user_messages(self) -> bool:
        return True

    @override
    def collapse_assistant_messages(self) -> bool:
        return True

    # convert some common BadRequestError states into 'refusal' model output
    def handle_bad_request(self, ex: BadRequestError) -> ModelOutput | None:
        error = exception_message(ex)
        content: str | None = None
        stop_reason: StopReason | None = None

        if "prompt is too long" in error:
            content = "Sorry, but your prompt is too long."
            stop_reason = "length"

        if content and stop_reason:
            return ModelOutput.from_content(
                model=self.model_name,
                content=content,
                stop_reason=stop_reason,
                error=error,
            )
        else:
            return None


async def resolve_chat_input(
    input: list[ChatMessage],
    tools: list[ToolInfo],
    config: GenerateConfig,
) -> Tuple[str | None, list[ToolParam], list[MessageParam]]:
    # extract system message
    system_message, messages = split_system_message(input, config)

    # some special handling for tools
    if len(tools) > 0:
        # encourage claude to show its thinking, see
        # https://docs.anthropic.com/claude/docs/tool-use#chain-of-thought-tool-use
        system_message = f"{system_message}\n\nBefore answering, explain your reasoning step-by-step in tags."

    # messages
    message_params = [(await message_param(message)) for message in messages]

    # collapse user messages (as Inspect 'tool' messages become Claude 'user' messages)
    message_params = functools.reduce(
        consecutive_user_message_reducer, message_params, []
    )

    # tools
    chat_functions = [chat_api_tool(tool)["function"] for tool in tools]
    tools_param = [
        ToolParam(
            name=function["name"],
            description=function["description"],
            input_schema=cast(InputSchema, function["parameters"]),
        )
        for function in chat_functions
    ]

    return system_message, tools_param, message_params


def consecutive_user_message_reducer(
    messages: list[MessageParam],
    message: MessageParam,
) -> list[MessageParam]:
    return consective_message_reducer(messages, message, "user")


def consective_message_reducer(
    messages: list[MessageParam],
    message: MessageParam,
    role: Literal["user", "assistant"],
) -> list[MessageParam]:
    if message["role"] == role and len(messages) > 0 and messages[-1]["role"] == role:
        messages[-1] = combine_messages(messages[-1], message)
    else:
        messages.append(message)
    return messages


def combine_messages(a: MessageParam, b: MessageParam) -> MessageParam:
    role = a["role"]
    a_content = a["content"]
    b_content = b["content"]
    if isinstance(a_content, str) and isinstance(a_content, str):
        return MessageParam(role=role, content=f"{a_content}\n{b_content}")
    elif isinstance(a_content, list) and isinstance(b_content, list):
        return MessageParam(role=role, content=a_content + b_content)
    elif isinstance(a_content, str) and isinstance(b_content, list):
        return MessageParam(
            role=role, content=[TextBlockParam(type="text", text=a_content)] + b_content
        )
    elif isinstance(a_content, list) and isinstance(b_content, str):
        return MessageParam(
            role=role, content=a_content + [TextBlockParam(type="text", text=b_content)]
        )
    else:
        raise ValueError(f"Unexpected content types for messages: {a}, {b}")


def message_tool_choice(tool_choice: ToolChoice) -> message_create_params.ToolChoice:
    if isinstance(tool_choice, ToolFunction):
        return {"type": "tool", "name": tool_choice.name}
    elif tool_choice == "any":
        return {"type": "any"}
    else:
        return {"type": "auto"}


async def message_param(message: ChatMessage) -> MessageParam:
    # no system role for anthropic (this is more like an assertion,
    # as these should have already been filtered out)
    if message.role == "system":
        raise ValueError("Anthropic models do not support the system role")

    # "tool" means serving a tool call result back to claude
    elif message.role == "tool":
        if message.tool_error is not None:
            content: str | list[TextBlockParam | ImageBlockParam] = message.tool_error
        if isinstance(message.content, str):
            content = [TextBlockParam(type="text", text=message.content)]
        else:
            content = [
                await message_param_content(content) for content in message.content
            ]

        return MessageParam(
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

        # filter out empty text content (sometimes claude passes empty text
        # context back with tool calls but won't let us play them back)
        tools_content = [
            c for c in tools_content if not c["type"] == "text" or len(c["text"]) > 0
        ]

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

        return MessageParam(
            role=message.role,
            content=tools_content,
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


def model_output_from_message(message: Message, tools: list[ToolInfo]) -> ModelOutput:
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
