import functools
import os
import re
from copy import copy
from logging import getLogger
from typing import Any, Literal, Optional, Tuple, cast

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    AsyncAnthropicBedrock,
    AsyncAnthropicVertex,
    BadRequestError,
    NotGiven,
)
from anthropic._types import Body
from anthropic.types import (
    ImageBlockParam,
    Message,
    MessageParam,
    RedactedThinkingBlock,
    RedactedThinkingBlockParam,
    TextBlock,
    TextBlockParam,
    ThinkingBlock,
    ThinkingBlockParam,
    ToolParam,
    ToolResultBlockParam,
    ToolTextEditor20250124Param,
    ToolUseBlock,
    ToolUseBlockParam,
    message_create_params,
)
from anthropic.types.beta import (
    BetaToolComputerUse20250124Param,
    BetaToolTextEditor20241022Param,
)
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai._util.constants import BASE_64_DATA_REMOVED, NO_CONTENT
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.error import exception_message
from inspect_ai._util.http import is_retryable_http_status
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.logger import warn_once
from inspect_ai._util.trace import trace_message
from inspect_ai._util.url import data_uri_mime_type, data_uri_to_base64
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo

from ..._util.httpx import httpx_should_retry
from .._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageSystem
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_call import ModelCall
from .._model_output import ChatCompletionChoice, ModelOutput, ModelUsage, StopReason
from .util import environment_prerequisite_error, model_base_url
from .util.hooks import HttpxHooks

logger = getLogger(__name__)

ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"

INTERNAL_COMPUTER_TOOL_NAME = "computer"


class AnthropicAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        streaming: bool | Literal["auto"] = "auto",
        **model_args: Any,
    ):
        # extract any service prefix from model name
        parts = model_name.split("/")
        if len(parts) > 1:
            self.service: str | None = parts[0]
        else:
            self.service = None

        # record steraming pref
        self.streaming = streaming

        # collect generate model_args (then delete them so we can pass the rest on)
        def collect_model_arg(name: str) -> Any | None:
            nonlocal model_args
            value = model_args.get(name, None)
            if value is not None:
                model_args.pop(name)
            return value

        self.extra_body: Body | None = collect_model_arg("extra_body")

        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[ANTHROPIC_API_KEY],
            config=config,
        )

        # create client
        if self.is_bedrock():
            base_url = model_base_url(
                base_url, ["ANTHROPIC_BEDROCK_BASE_URL", "BEDROCK_ANTHROPIC_BASE_URL"]
            )

            # resolve the default region
            aws_region = None
            base_region = os.environ.get("AWS_REGION", None)
            if base_region is None:
                aws_region = os.environ.get("AWS_DEFAULT_REGION", None)

            self.client: (
                AsyncAnthropic | AsyncAnthropicBedrock | AsyncAnthropicVertex
            ) = AsyncAnthropicBedrock(
                base_url=base_url,
                aws_region=aws_region,
                **model_args,
            )
        elif self.is_vertex():
            base_url = model_base_url(
                base_url, ["ANTHROPIC_VERTEX_BASE_URL", "VERTEX_ANTHROPIC_BASE_URL"]
            )
            region = os.environ.get("ANTHROPIC_VERTEX_REGION", NotGiven())
            project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", NotGiven())
            self.client = AsyncAnthropicVertex(
                region=region,
                project_id=project_id,
                base_url=base_url,
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
                **model_args,
            )

        # create time tracker
        self._http_hooks = HttpxHooks(self.client._client)

    @override
    async def aclose(self) -> None:
        await self.client.close()

    def is_bedrock(self) -> bool:
        return self.service == "bedrock"

    def is_vertex(self) -> bool:
        return self.service == "vertex"

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # allocate request_id (so we can see it from ModelCall)
        request_id = self._http_hooks.start_request()

        # setup request and response for ModelCall
        request: dict[str, Any] = {}
        response: dict[str, Any] = {}

        def model_call() -> ModelCall:
            return ModelCall.create(
                request=request,
                response=response,
                filter=model_call_filter,
                time=self._http_hooks.end_request(request_id),
            )

        # generate
        try:
            system_param, tools_param, messages = await self.resolve_chat_input(
                input, tools, config
            )

            # prepare request params (assembled this way so we can log the raw model call)
            request = dict(messages=messages)

            # system messages and tools
            if system_param is not None:
                request["system"] = system_param
            request["tools"] = tools_param
            if len(tools) > 0:
                request["tool_choice"] = message_tool_choice(
                    tool_choice, self.is_using_thinking(config)
                )

            # additional options
            req, headers, betas = self.completion_config(config)
            request = request | req

            # extra headers (for time tracker and computer use)
            extra_headers = headers | {HttpxHooks.REQUEST_ID_HEADER: request_id}
            if any(
                tool.get("type", None) == "computer_20250124" for tool in tools_param
            ):
                # From: https://docs.anthropic.com/en/docs/agents-and-tools/computer-use#claude-3-7-sonnet-beta-flag
                # Note: The Bash (bash_20250124) and Text Editor (text_editor_20250124)
                # tools are generally available for Claude 3.5 Sonnet (new) as well and
                # can be used without the computer use beta header.
                betas.append("computer-use-2025-01-24")
            if any("20241022" in str(tool.get("type", "")) for tool in tools_param):
                betas.append("computer-use-2024-10-22")
            if len(betas) > 0:
                extra_headers["anthropic-beta"] = ",".join(betas)

            request["extra_headers"] = extra_headers

            # extra_body
            if self.extra_body is not None:
                request["extra_body"] = self.extra_body

            # make request (unless overrideen, stream if we are using reasoning)
            streaming = (
                self.is_using_thinking(config)
                if self.streaming == "auto"
                else self.streaming
            )
            if streaming:
                async with self.client.messages.stream(**request) as stream:
                    message = await stream.get_final_message()
            else:
                message = await self.client.messages.create(**request, stream=False)

            # set response for ModelCall
            response = message.model_dump()

            # extract output
            output = await model_output_from_message(
                self.client, self.service_model_name(), message, tools
            )

            # return output and call
            return output, model_call()

        except BadRequestError as ex:
            return self.handle_bad_request(ex), model_call()

        except APIStatusError as ex:
            if ex.status_code == 413:
                return ModelOutput.from_content(
                    model=self.service_model_name(),
                    content=ex.message,
                    stop_reason="model_length",
                    error=ex.message,
                ), model_call()
            else:
                raise ex

    def completion_config(
        self, config: GenerateConfig
    ) -> tuple[dict[str, Any], dict[str, str], list[str]]:
        max_tokens = cast(int, config.max_tokens)
        params = dict(model=self.service_model_name(), max_tokens=max_tokens)
        headers: dict[str, str] = {}
        betas: list[str] = []
        # some params not compatible with thinking models
        if not self.is_using_thinking(config):
            if config.temperature is not None:
                params["temperature"] = config.temperature
            if config.top_p is not None:
                params["top_p"] = config.top_p
            if config.top_k is not None:
                params["top_k"] = config.top_k

        # some thinking-only stuff
        if self.is_using_thinking(config):
            params["thinking"] = dict(
                type="enabled", budget_tokens=config.reasoning_tokens
            )
            headers["anthropic-version"] = "2023-06-01"
            if max_tokens > 8192:
                betas.append("output-128k-2025-02-19")

        # config that applies to all models
        if config.stop_seqs is not None:
            params["stop_sequences"] = config.stop_seqs

        # return config
        return params, headers, betas

    @override
    def max_tokens(self) -> int | None:
        # anthropic requires you to explicitly specify max_tokens (most others
        # set it to the maximum allowable output tokens for the model).
        # set to 4096 which is the highest possible for claude 3 (claude 3.5
        # allows up to 8192)
        return 4096

    @override
    def max_tokens_for_config(self, config: GenerateConfig) -> int | None:
        max_tokens = cast(int, self.max_tokens())
        if self.is_thinking_model() and config.reasoning_tokens is not None:
            max_tokens = max_tokens + config.reasoning_tokens
        return max_tokens

    def is_using_thinking(self, config: GenerateConfig) -> bool:
        return self.is_thinking_model() and config.reasoning_tokens is not None

    def is_thinking_model(self) -> bool:
        return not self.is_claude_3() and not self.is_claude_3_5()

    def is_claude_3(self) -> bool:
        return re.search(r"claude-3-[a-zA-Z]", self.service_model_name()) is not None

    def is_claude_3_5(self) -> bool:
        return "claude-3-5-" in self.service_model_name()

    def is_claude_3_7(self) -> bool:
        return "claude-3-7-" in self.service_model_name()

    @override
    def connection_key(self) -> str:
        return str(self.api_key)

    def service_model_name(self) -> str:
        """Model name without any service prefix."""
        return self.model_name.replace(f"{self.service}/", "", 1)

    @override
    def should_retry(self, ex: Exception) -> bool:
        if isinstance(ex, APIStatusError):
            # for unknown reasons, anthropic does not always set status_code == 529
            # for "overloaded_error" so we check for it explicitly
            if (
                isinstance(ex.body, dict)
                and ex.body.get("error", {}).get("type", "") == "overloaded_error"
            ):
                return True

            # standard http status code checking
            return is_retryable_http_status(ex.status_code)
        elif httpx_should_retry(ex):
            return True
        elif isinstance(ex, APIConnectionError | APITimeoutError):
            return True
        else:
            return False

    @override
    def collapse_user_messages(self) -> bool:
        return True

    @override
    def collapse_assistant_messages(self) -> bool:
        return True

    @override
    def tools_required(self) -> bool:
        return True

    @override
    def tool_result_images(self) -> bool:
        return True

    @override
    def emulate_reasoning_history(self) -> bool:
        return False

    @override
    def force_reasoning_history(self) -> Literal["none", "all", "last"] | None:
        return "all"

    # convert some common BadRequestError states into 'refusal' model output
    def handle_bad_request(self, ex: BadRequestError) -> ModelOutput | Exception:
        error = exception_message(ex).lower()
        content: str | None = None
        stop_reason: StopReason | None = None

        # NOTE: Using case insensitive matching because the Anthropic Bedrock API seems to capitalize the work 'input' in its error message, other times it doesn't.
        if any(
            message in error.lower()
            for message in [
                "prompt is too long",
                "input is too long",
                "input length and `max_tokens` exceed context limit",
            ]
        ):
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
                model=self.service_model_name(),
                content=content,
                stop_reason=stop_reason,
                error=error,
            )
        else:
            return ex

    async def resolve_chat_input(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        config: GenerateConfig,
    ) -> Tuple[list[TextBlockParam] | None, list["ToolParamDef"], list[MessageParam]]:
        # extract system message
        system_messages, messages = split_system_messages(input, config)

        # messages
        message_params = [(await message_param(message)) for message in messages]

        # collapse user messages (as Inspect 'tool' messages become Claude 'user' messages)
        message_params = functools.reduce(
            consecutive_user_message_reducer, message_params, []
        )

        # tools
        tools_params = [self.tool_param_for_tool_info(tool, config) for tool in tools]

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
            model_name = self.service_model_name()
            if (
                "claude-3-sonnet" in model_name
                or "claude-2" in model_name
                or "claude-instant" in model_name
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
        return system_param, tools_params, message_params

    def tool_param_for_tool_info(
        self, tool: ToolInfo, config: GenerateConfig
    ) -> "ToolParamDef":
        # Use a native tool implementation when available. Otherwise, use the
        # standard tool implementation
        return self.maybe_native_tool_param(tool, config) or ToolParam(
            name=tool.name,
            description=tool.description,
            input_schema=tool.parameters.model_dump(exclude_none=True),
        )

    def maybe_native_tool_param(
        self, tool: ToolInfo, config: GenerateConfig
    ) -> Optional["ToolParamDef"]:
        return (
            (self.computer_use_tool_param(tool) or self.text_editor_tool_param(tool))
            if config.internal_tools is not False
            else None
        )

    def computer_use_tool_param(
        self, tool: ToolInfo
    ) -> Optional[BetaToolComputerUse20250124Param]:
        # check for compatible 'computer' tool
        if tool.name == "computer" and (
            sorted(tool.parameters.properties.keys())
            == sorted(
                [
                    "action",
                    "coordinate",
                    "duration",
                    "scroll_amount",
                    "scroll_direction",
                    "start_coordinate",
                    "text",
                ]
            )
        ):
            if self.is_claude_3_5():
                warn_once(
                    logger,
                    "Use of Anthropic's native computer use support is not enabled in Claude 3.5. Please use 3.7 or later to leverage the native support.",
                )
                return None
            return BetaToolComputerUse20250124Param(
                type="computer_20250124",
                name="computer",
                # Note: The dimensions passed here for display_width_px and display_height_px should
                # match the dimensions of screenshots returned by the tool.
                # Those dimensions will always be one of the values in MAX_SCALING_TARGETS
                # in _x11_client.py.
                # TODO: enhance this code to calculate the dimensions based on the scaled screen
                # size used by the container.
                display_width_px=1366,
                display_height_px=768,
                display_number=1,
            )
        # not a computer_use tool
        else:
            return None

    def text_editor_tool_param(
        self, tool: ToolInfo
    ) -> ToolTextEditor20250124Param | BetaToolTextEditor20241022Param | None:
        # check for compatible 'text editor' tool
        if tool.name == "text_editor" and (
            sorted(tool.parameters.properties.keys())
            == sorted(
                [
                    "command",
                    "file_text",
                    "insert_line",
                    "new_str",
                    "old_str",
                    "path",
                    "view_range",
                ]
            )
        ):
            return (
                BetaToolTextEditor20241022Param(
                    type="text_editor_20241022", name="str_replace_editor"
                )
                if self.is_claude_3_5()
                else ToolTextEditor20250124Param(
                    type="text_editor_20250124", name="str_replace_editor"
                )
            )
        # not a text_editor tool
        else:
            return None


# tools can be either a stock tool param or a special Anthropic native use tool param
ToolParamDef = (
    ToolParam
    | BetaToolComputerUse20250124Param
    | ToolTextEditor20250124Param
    | BetaToolTextEditor20241022Param
)


def add_cache_control(
    param: TextBlockParam
    | ToolParam
    | BetaToolComputerUse20250124Param
    | ToolTextEditor20250124Param
    | BetaToolTextEditor20241022Param
    | dict[str, Any],
) -> None:
    cast(dict[str, Any], param)["cache_control"] = {"type": "ephemeral"}


def consecutive_user_message_reducer(
    messages: list[MessageParam],
    message: MessageParam,
) -> list[MessageParam]:
    return consecutive_message_reducer(messages, message, "user")


def consecutive_message_reducer(
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
    # TODO: Fix this code as it currently drops interesting properties when combining
    role = a["role"]
    a_content = a["content"]
    b_content = b["content"]
    if isinstance(a_content, str) and isinstance(b_content, str):
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


def message_tool_choice(
    tool_choice: ToolChoice, thinking_model: bool
) -> message_create_params.ToolChoice:
    if isinstance(tool_choice, ToolFunction):
        # forced tool use not compatible with thinking models
        if thinking_model:
            return {"type": "any"}
        else:
            return {"type": "tool", "name": tool_choice.name}
    elif tool_choice == "any":
        return {"type": "any"}
    elif tool_choice == "none":
        return {"type": "none"}
    else:
        return {"type": "auto"}


async def message_param(message: ChatMessage) -> MessageParam:
    # if content is empty that is going to result in an error when we replay
    # this message to claude, so in that case insert a NO_CONTENT message
    if isinstance(message.content, list) and len(message.content) == 0:
        message = message.model_copy()
        message.content = [ContentText(text=NO_CONTENT)]

    # no system role for anthropic (this is more like an assertion,
    # as these should have already been filtered out)
    if message.role == "system":
        raise ValueError("Anthropic models do not support the system role")

    # "tool" means serving a tool call result back to claude
    elif message.role == "tool":
        if message.error is not None:
            content: (
                str
                | list[
                    TextBlockParam
                    | ImageBlockParam
                    | ThinkingBlockParam
                    | RedactedThinkingBlockParam
                ]
            ) = message.error.message
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
                    content=cast(list[TextBlockParam | ImageBlockParam], content),
                    is_error=message.error is not None,
                )
            ],
        )

    # tool_calls means claude is attempting to call our tools
    elif message.role == "assistant" and message.tool_calls:
        # first include content (claude <thinking>)
        tools_content: list[
            TextBlockParam
            | ThinkingBlockParam
            | RedactedThinkingBlockParam
            | ImageBlockParam
            | ToolUseBlockParam
        ] = (
            [TextBlockParam(type="text", text=message.content or NO_CONTENT)]
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
            internal_name = _internal_name_from_tool_call(tool_call)
            tools_content.append(
                ToolUseBlockParam(
                    type="tool_use",
                    id=tool_call.id,
                    name=internal_name or tool_call.function,
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


async def model_output_from_message(
    client: AsyncAnthropic | AsyncAnthropicBedrock | AsyncAnthropicVertex,
    model: str,
    message: Message,
    tools: list[ToolInfo],
) -> ModelOutput:
    # extract content and tool calls
    content: list[Content] = []
    reasoning_tokens = 0
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
            (tool_name, internal_name) = _names_for_tool_call(content_block.name, tools)
            tool_calls.append(
                ToolCall(
                    id=content_block.id,
                    function=tool_name,
                    arguments=content_block.model_dump().get("input", {}),
                    internal=internal_name,
                )
            )
        elif isinstance(content_block, RedactedThinkingBlock):
            content.append(
                ContentReasoning(reasoning=content_block.data, redacted=True)
            )
        elif isinstance(content_block, ThinkingBlock):
            reasoning_tokens += await count_tokens(
                client, model, content_block.thinking
            )
            content.append(
                ContentReasoning(
                    reasoning=content_block.thinking, signature=content_block.signature
                )
            )

    # resolve choice
    choice = ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=content, tool_calls=tool_calls, model=model, source="generate"
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
        + message.usage.output_tokens  # includes reasoning tokens
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
            reasoning_tokens=reasoning_tokens if reasoning_tokens > 0 else None,
        ),
    )


def _internal_name_from_tool_call(tool_call: ToolCall) -> str | None:
    assert isinstance(tool_call.internal, str | None), (
        f"ToolCall internal must be `str | None`: {tool_call.internal}"
    )
    return tool_call.internal


def _names_for_tool_call(
    tool_called: str, tools: list[ToolInfo]
) -> tuple[str, str | None]:
    """
    Return the name of the tool to call and potentially an internal name.

    Anthropic prescribes names for their native tools - `computer`, `bash`, and
    `str_replace_editor`. For a variety of reasons, Inspect's tool names to not
    necessarily conform to internal names. Anthropic also provides specific tool
    types for these built-in tools.
    """
    mappings = (
        (INTERNAL_COMPUTER_TOOL_NAME, "computer_20250124", "computer"),
        ("str_replace_editor", "text_editor_20241022", "text_editor"),
        ("str_replace_editor", "text_editor_20250124", "text_editor"),
        ("bash", "bash_20250124", "bash_session"),
    )

    return next(
        (
            (entry[2], entry[0])
            for entry in mappings
            if entry[0] == tool_called and any(tool.name == entry[2] for tool in tools)
        ),
        (tool_called, None),
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
) -> TextBlockParam | ImageBlockParam | ThinkingBlockParam | RedactedThinkingBlockParam:
    if isinstance(content, ContentText):
        return TextBlockParam(type="text", text=content.text or NO_CONTENT)
    elif isinstance(content, ContentImage):
        # resolve to url
        image = await file_as_data_uri(content.image)

        # resolve mime type and base64 content
        media_type = data_uri_mime_type(image) or "image/png"
        image = data_uri_to_base64(image)

        if media_type not in ["image/jpeg", "image/png", "image/gif", "image/webp"]:
            raise ValueError(f"Unable to read image of type {media_type}")

        return ImageBlockParam(
            type="image",
            source=dict(type="base64", media_type=cast(Any, media_type), data=image),
        )
    elif isinstance(content, ContentReasoning):
        if content.redacted:
            return RedactedThinkingBlockParam(
                type="redacted_thinking",
                data=content.reasoning,
            )
        else:
            if content.signature is None:
                raise ValueError("Thinking content without signature.")
            return ThinkingBlockParam(
                type="thinking", thinking=content.reasoning, signature=content.signature
            )
    else:
        raise RuntimeError(
            "Anthropic models do not currently support audio or video inputs."
        )


async def count_tokens(
    client: AsyncAnthropic | AsyncAnthropicBedrock | AsyncAnthropicVertex,
    model: str,
    text: str,
) -> int:
    try:
        response = await client.messages.count_tokens(
            model=model,
            messages=[{"role": "user", "content": text}],
        )
        return response.input_tokens
    except Exception as ex:
        warn_once(
            logger,
            f"Unable to call count_tokens API for model {model} (falling back to estimated tokens)",
        )
        trace_message(
            logger,
            "Anthropic",
            f"Unable to call count_tokens API for model {model} ({ex})",
        )
        words = text.split()
        estimated_tokens = int(len(words) * 1.3)
        return estimated_tokens


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
