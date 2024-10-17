import functools
import os
from copy import copy
from logging import getLogger
from typing import Any, Literal, Tuple, cast

from anthropic import (
    APIConnectionError,
    AsyncAnthropic,
    AsyncAnthropicBedrock,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
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
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai._util.constants import BASE_64_DATA_REMOVED, DEFAULT_MAX_RETRIES
from inspect_ai._util.content import Content, ContentText
from inspect_ai._util.error import exception_message
from inspect_ai._util.images import image_as_data_uri
from inspect_ai._util.logger import warn_once
from inspect_ai._util.url import data_uri_mime_type, data_uri_to_base64, is_data_uri
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo

from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from .util import environment_prerequisite_error, model_base_url

logger = getLogger(__name__)

ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"


class AnthropicAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        bedrock: bool = False,
        **model_args: Any,
    ):
        # extract any service prefix from model name
        parts = model_name.split("/")
        if len(parts) > 1:
            service = parts[0]
            bedrock = service == "bedrock"
            model_name = "/".join(parts[1:])

        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[ANTHROPIC_API_KEY],
            config=config,
        )

        # create client
        if bedrock:
            base_url = model_base_url(
                base_url, ["ANTHROPIC_BEDROCK_BASE_URL", "BEDROCK_ANTHROPIC_BASE_URL"]
            )

            # resolve the default region
            aws_region = None
            base_region = os.environ.get("AWS_REGION", None)
            if base_region is None:
                aws_region = os.environ.get("AWS_DEFAULT_REGION", None)

            self.client: AsyncAnthropic | AsyncAnthropicBedrock = AsyncAnthropicBedrock(
                base_url=base_url,
                max_retries=(
                    config.max_retries if config.max_retries else DEFAULT_MAX_RETRIES
                ),
                aws_region=aws_region,
                **model_args,
            )
        else:
            # resolve api_key
            if not self.api_key:
                self.api_key = os.environ.get(ANTHROPIC_API_KEY, None)
            if self.api_key is None:
                raise environment_prerequisite_error("Anthropic", ANTHROPIC_API_KEY)
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
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        # generate
        try:
            (
                system_param,
                tools_param,
                messages,
                cache_prompt,
            ) = await resolve_chat_input(self.model_name, input, tools, config)

            # prepare request params (assembed this way so we can log the raw model call)
            request: dict[str, Any] = dict(messages=messages)

            # system messages and tools
            if system_param is not None:
                request["system"] = system_param
            request["tools"] = tools_param
            if len(tools) > 0:
                request["tool_choice"] = message_tool_choice(tool_choice)

            # additional options
            request = request | self.completion_params(config)

            # caching header
            if cache_prompt:
                request["extra_headers"] = {
                    "anthropic-beta": "prompt-caching-2024-07-31"
                }

            # call model
            message = await self.client.messages.create(**request, stream=False)

            # extract output
            output = model_output_from_message(message, tools)

            # return output and call
            call = ModelCall.create(
                request=request,
                response=message.model_dump(),
                filter=model_call_filter,
            )

            return output, call

        except BadRequestError as ex:
            error_output = self.handle_bad_request(ex)
            if error_output is not None:
                return error_output
            else:
                raise ex

    def completion_params(self, config: GenerateConfig) -> dict[str, Any]:
        params = dict(model=self.model_name, max_tokens=cast(int, config.max_tokens))
        if config.temperature is not None:
            params["temperature"] = config.temperature
        if config.top_p is not None:
            params["top_p"] = config.top_p
        if config.top_k is not None:
            params["top_k"] = config.top_k
        if config.timeout is not None:
            params["timeout"] = float(config.timeout)
        if config.stop_seqs is not None:
            params["stop_sequences"] = config.stop_seqs
        return params

    @override
    def max_tokens(self) -> int | None:
        # anthropic requires you to explicitly specify max_tokens (most others
        # set it to the maximum allowable output tokens for the model).
        # set to 4096 which is the lowest documented max_tokens for claude models
        return 4096

    @override
    def connection_key(self) -> str:
        return str(self.api_key)

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

    @override
    def tools_required(self) -> bool:
        return True

    # convert some common BadRequestError states into 'refusal' model output
    def handle_bad_request(self, ex: BadRequestError) -> ModelOutput | None:
        error = exception_message(ex).lower()
        content: str | None = None
        stop_reason: StopReason | None = None

        if "prompt is too long" in error:
            if (
                isinstance(ex.body, dict)
                and "error" in ex.body.keys()
                and isinstance(ex.body.get("error"), dict)
            ):
                error_dict = cast(dict[str, Any], ex.body.get("error"))
                if "message" in error_dict:
                    content = str(error_dict.get("message"))
                else:
                    content = str(error_dict)
            else:
                content = error
            stop_reason = "model_length"
        elif "content filtering" in error:
            content = "Sorry, but I am unable to help with that request."
            stop_reason = "content_filter"

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
    model: str,
    input: list[ChatMessage],
    tools: list[ToolInfo],
    config: GenerateConfig,
) -> Tuple[list[TextBlockParam] | None, list[ToolParam], list[MessageParam], bool]:
    # extract system message
    system_messages, messages = split_system_messages(input, config)

    # messages
    message_params = [(await message_param(message)) for message in messages]

    # collapse user messages (as Inspect 'tool' messages become Claude 'user' messages)
    message_params = functools.reduce(
        consecutive_user_message_reducer, message_params, []
    )

    # tools
    tools_params = [
        ToolParam(
            name=tool.name,
            description=tool.description,
            input_schema=tool.parameters.model_dump(exclude_none=True),
        )
        for tool in tools
    ]

    # system messages
    if len(system_messages) > 0:
        system_param: list[TextBlockParam] | None = [
            TextBlockParam(type="text", text=message.text)
            for message in system_messages
        ]
    else:
        system_param = None

    # add caching directives if necessary
    cache_prompt = (
        config.cache_prompt
        if isinstance(config.cache_prompt, bool)
        else True
        if len(tools_params)
        else False
    )

    # only certain claude models qualify
    if cache_prompt:
        if (
            "claude-3-sonnet" in model
            or "claude-2" in model
            or "claude-instant" in model
        ):
            cache_prompt = False

    if cache_prompt:
        # system
        if system_param:
            add_cache_control(system_param[-1])
        # tools
        if tools_params:
            add_cache_control(tools_params[-1])
        # last 2 user messages
        user_message_params = list(
            filter(lambda m: m["role"] == "user", reversed(message_params))
        )
        for message in user_message_params[:2]:
            if isinstance(message["content"], str):
                text_param = TextBlockParam(type="text", text=message["content"])
                add_cache_control(text_param)
                message["content"] = [text_param]
            else:
                content = list(message["content"])
                add_cache_control(cast(dict[str, Any], content[-1]))

    # return chat input
    return system_param, tools_params, message_params, cache_prompt


def add_cache_control(param: TextBlockParam | ToolParam | dict[str, Any]) -> None:
    cast(dict[str, Any], param)["cache_control"] = {"type": "ephemeral"}


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
    elif tool_choice == "none":
        warn_once(
            logger,
            'The Anthropic API does not support tool_choice="none" (using "auto" instead)',
        )
        return {"type": "auto"}
    else:
        return {"type": "auto"}


# text we insert when there is no content passed
# (as this will result in an Anthropic API error)
NO_CONTENT = "(no content)"


async def message_param(message: ChatMessage) -> MessageParam:
    # no system role for anthropic (this is more like an assertion,
    # as these should have already been filtered out)
    if message.role == "system":
        raise ValueError("Anthropic models do not support the system role")

    # "tool" means serving a tool call result back to claude
    elif message.role == "tool":
        if message.error is not None:
            content: str | list[TextBlockParam | ImageBlockParam] = (
                message.error.message
            )
            # anthropic requires that content be populated when
            # is_error is true (throws bad_request_error when not)
            # so make sure this precondition is met
            if not content:
                content = message.text
            if not content:
                content = "error"
        elif isinstance(message.content, str):
            content = [TextBlockParam(type="text", text=message.content or NO_CONTENT)]
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
                    is_error=message.error is not None,
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
        return MessageParam(role=message.role, content=message.content or NO_CONTENT)

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
    usage = message.usage.model_dump()
    input_tokens_cache_write = usage.get("cache_creation_input_tokens", None)
    input_tokens_cache_read = usage.get("cache_read_input_tokens", None)
    total_tokens = (
        message.usage.input_tokens
        + (input_tokens_cache_write or 0)
        + (input_tokens_cache_read or 0)
        + message.usage.output_tokens
    )
    return ModelOutput(
        model=message.model,
        choices=[choice],
        usage=ModelUsage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            total_tokens=total_tokens,
            input_tokens_cache_write=input_tokens_cache_write,
            input_tokens_cache_read=input_tokens_cache_read,
        ),
    )


def message_stop_reason(message: Message) -> StopReason:
    match message.stop_reason:
        case "end_turn" | "stop_sequence":
            return "stop"
        case "tool_use":
            return "tool_calls"
        case "max_tokens":
            return message.stop_reason
        case _:
            return "unknown"


def split_system_messages(
    input: list[ChatMessage], config: GenerateConfig
) -> Tuple[list[ChatMessageSystem], list[ChatMessage]]:
    # split messages
    system_messages = [m for m in input if isinstance(m, ChatMessageSystem)]
    messages = [m for m in input if not isinstance(m, ChatMessageSystem)]

    # return
    return system_messages, cast(list[ChatMessage], messages)


async def message_param_content(
    content: Content,
) -> TextBlockParam | ImageBlockParam:
    if isinstance(content, ContentText):
        return TextBlockParam(type="text", text=content.text or NO_CONTENT)
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


def model_call_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    # remove base64 encoded images
    if (
        key == "source"
        and isinstance(value, dict)
        and value.get("type", None) == "base64"
    ):
        value = copy(value)
        value.update(data=BASE_64_DATA_REMOVED)
    return value
