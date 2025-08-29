import functools
import json
import os
import re
from contextvars import ContextVar
from copy import copy
from dataclasses import dataclass, field
from logging import getLogger
from typing import (
    Any,
    Iterable,
    Literal,
    Optional,
    Sequence,
    Tuple,
    TypeGuard,
    Union,
    cast,
)

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
    Base64PDFSourceParam,
    ContentBlock,
    ContentBlockParam,
    ContentBlockSourceParam,
    DocumentBlockParam,
    ImageBlockParam,
    Message,
    MessageParam,
    PlainTextSourceParam,
    RedactedThinkingBlock,
    RedactedThinkingBlockParam,
    ServerToolUseBlock,
    ServerToolUseBlockParam,
    TextBlock,
    TextBlockParam,
    ThinkingBlock,
    ThinkingBlockParam,
    ToolParam,
    ToolResultBlockParam,
    ToolTextEditor20250124Param,
    ToolUseBlock,
    ToolUseBlockParam,
    URLPDFSourceParam,
    WebSearchResultBlock,
    WebSearchTool20250305Param,
    WebSearchToolRequestErrorParam,
    WebSearchToolResultBlock,
    WebSearchToolResultBlockParam,
    WebSearchToolResultError,
    message_create_params,
)
from anthropic.types.beta import (
    BetaMCPToolResultBlock,
    BetaMCPToolUseBlock,
    BetaMCPToolUseBlockParam,
    BetaRequestMCPServerToolConfigurationParam,
    BetaRequestMCPServerURLDefinitionParam,
    BetaRequestMCPToolResultBlockParam,
    BetaTextBlockParam,
    BetaToolComputerUse20250124Param,
    BetaToolTextEditor20241022Param,
    BetaToolTextEditor20250429Param,
)
from anthropic.types.document_block_param import Source
from anthropic.types.web_search_tool_result_block_param_content_param import (
    WebSearchToolResultBlockParamContentParam,
)
from pydantic import JsonValue, TypeAdapter, ValidationError
from typing_extensions import override

from inspect_ai._util.constants import BASE_64_DATA_REMOVED, NO_CONTENT
from inspect_ai._util.content import (
    Content,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
from inspect_ai._util.error import exception_message
from inspect_ai._util.http import is_retryable_http_status
from inspect_ai._util.images import file_as_data, file_as_data_uri
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.logger import warn_once
from inspect_ai._util.trace import trace_message
from inspect_ai._util.url import data_uri_mime_type, data_uri_to_base64, is_http_url
from inspect_ai.model._internal import (
    CONTENT_INTERNAL_TAG,
    content_internal_tag,
    parse_content_with_internal,
)
from inspect_ai.model._retry import model_retry_config
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._mcp._remote import is_mcp_server_tool

from ..._util.httpx import httpx_should_retry
from .._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageSystem
from .._generate_config import GenerateConfig, normalized_batch_config
from .._model import ModelAPI, log_model_retry
from .._model_call import ModelCall
from .._model_output import ChatCompletionChoice, ModelOutput, ModelUsage, StopReason
from .._providers._anthropic_citations import (
    to_anthropic_citation,
    to_inspect_citation,
)
from ._anthropic_batch import AnthropicBatcher
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
        betas: str | list[str] = [],
        **model_args: Any,
    ):
        # extract any service prefix from model name
        parts = model_name.split("/")
        if len(parts) > 1:
            self.service: str | None = parts[0]
        else:
            self.service = None

        # record steraming and betas prefs
        self.streaming = streaming
        self.betas = betas if isinstance(betas, list) else [str(betas)]

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

        self._batcher: AnthropicBatcher | None = None

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
            (
                system_param,
                tools_param,
                mcp_servers_param,
                messages,
            ) = await self.resolve_chat_input(input, tools, config)

            # prepare request params (assembled this way so we can log the raw model call)
            request = dict(messages=messages)

            # system messages and tools
            if system_param is not None:
                request["system"] = system_param
            request["tools"] = tools_param
            if len(tools_param) > 0 and not self.is_using_thinking(config):
                request["tool_choice"] = message_tool_choice(tool_choice)

            # additional options
            req, headers, betas = self.completion_config(config)
            request = request | req

            # beta param for mcp tools
            if len(mcp_servers_param) > 0:
                betas.append("mcp-client-2025-04-04")

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
                betas = list(dict.fromkeys(betas))  # remove duplicates
                extra_headers["anthropic-beta"] = ",".join(betas)

            request["extra_headers"] = extra_headers

            # extra_body
            if self.extra_body is not None:
                request["extra_body"] = self.extra_body

            # mcp servers
            if len(mcp_servers_param) > 0:
                if "extra_body" not in request:
                    request["extra_body"] = dict()
                request["extra_body"]["mcp_servers"] = mcp_servers_param

            # stream if we are using reasoning or >= 8192 max_tokens
            streaming = (
                self.auto_streaming(config)
                if self.streaming == "auto"
                else self.streaming
            )

            response, output = await self._perform_request_and_continuations(
                request, streaming, tools, config
            )

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

    async def _perform_request_and_continuations(
        self,
        request: dict[str, Any],
        streaming: bool,
        tools: list[ToolInfo],
        config: GenerateConfig,
    ) -> tuple[dict[str, Any], ModelOutput]:
        """
        This helper function is split out so that it can be easily call itself recursively in cases where the model requires a continuation

        It considers the result from the initial request the "head" and the result
        from the continuation the "tail".
        """
        # TODO: Bogus that we have to do this on each call. Ideally, it would be
        # done only once and ideally by non-provider specific code.
        batch_config = normalized_batch_config(config.batch)
        if batch_config:
            if not self._batcher:
                self._batcher = AnthropicBatcher(
                    self.client,
                    batch_config,
                    # TODO: In the future, we could pass max_retries and timeout
                    # from batch_config falling back to config
                    model_retry_config(
                        self.model_name,
                        config.max_retries,
                        config.timeout,
                        self.should_retry,
                        log_model_retry,
                    ),
                )
            head_message = await self._batcher.generate_for_request(request)
        elif streaming:
            async with self.client.messages.stream(**request) as stream:
                head_message = await stream.get_final_message()
        else:
            head_message = await self.client.messages.create(**request, stream=False)

        head_model_output, continuation_required = await model_output_from_message(
            self.client, self.service_model_name(), head_message, tools
        )

        if continuation_required:
            tail_request = dict(request)
            tail_request["messages"] = request["messages"] + [
                MessageParam(role=head_message.role, content=head_message.content)
            ]
            _, tail_model_output = await self._perform_request_and_continuations(
                tail_request, streaming, tools, config
            )

            head_content = _content_list(head_model_output.message.content)
            tail_content = _content_list(tail_model_output.message.content)
            tail_model_output.message.content = head_content + tail_content

            # TODO:
            # It looks weird to return the head message with the tail output, but
            # the contract for this function is that it returns the head message
            # even when it has needed to recurse. This is because model_call()
            # above doesn't currently support multiple requests
            return head_message.model_dump(warnings="none"), tail_model_output

        # NOTE: we do warnings="none" here because we are including beta API message
        # params (for MCP tool use/result) in the payload which causes Message to emit
        # Pydantic UserWarning for. We can remove this when remote MCP is out of beta
        return head_message.model_dump(warnings="none"), head_model_output

    def completion_config(
        self, config: GenerateConfig
    ) -> tuple[dict[str, Any], dict[str, str], list[str]]:
        max_tokens = cast(int, config.max_tokens)
        params = dict(model=self.service_model_name(), max_tokens=max_tokens)
        headers: dict[str, str] = {}
        betas: list[str] = self.betas.copy()

        # temperature not compatible with extended thinking
        THINKING_WARNING = "anthropic models do not support the '{parameter}' parameter when using extended thinking."
        if config.temperature is not None:
            if self.is_using_thinking(config):
                warn_once(logger, THINKING_WARNING.format(parameter="temperature"))
            else:
                params["temperature"] = config.temperature
        # top_p not compatible with extended thinking
        if config.top_p is not None:
            if self.is_using_thinking(config):
                warn_once(logger, THINKING_WARNING.format(parameter="top_p"))
            else:
                params["top_p"] = config.top_p
        # top_k not compatible with extended thinking
        if config.top_k is not None:
            if self.is_using_thinking(config):
                warn_once(logger, THINKING_WARNING.format(parameter="top_k"))
            else:
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

        # look for any of our native fields not in GenerateConfig in extra_body
        if config.extra_body is not None:
            for field in anthropic_extra_body_fields():
                if field in config.extra_body and field not in params:
                    params[field] = config.extra_body[field]

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

    # see https://github.com/anthropics/anthropic-sdk-python?tab=readme-ov-file#long-requests
    def auto_streaming(self, config: GenerateConfig) -> bool:
        return self.is_using_thinking(config) or (
            config.max_tokens is not None and config.max_tokens >= 8192
        )

    def is_thinking_model(self) -> bool:
        return not self.is_claude_3() and not self.is_claude_3_5()

    def is_claude_3(self) -> bool:
        return re.search(r"claude-3-[a-zA-Z]", self.service_model_name()) is not None

    def is_claude_3_5(self) -> bool:
        return "claude-3-5-" in self.service_model_name()

    def is_claude_3_7(self) -> bool:
        return "claude-3-7-" in self.service_model_name()

    def is_claude_4(self) -> bool:
        return re.search(r"claude-4-[a-zA-Z]", self.service_model_name()) is not None

    @override
    def connection_key(self) -> str:
        return str(self.api_key)

    def service_model_name(self) -> str:
        """Model name without any service prefix."""
        return self.model_name.replace(f"{self.service}/", "", 1)

    @override
    def should_retry(self, ex: BaseException) -> bool:
        if isinstance(ex, APIStatusError):
            # when streaming, anthropic does not set status_code == 529
            # for overloaded errors so we check for it explicitly
            if isinstance(ex.body, dict):
                if "overloaded" in str(ex.body).lower():
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
    def supports_remote_mcp(self) -> bool:
        if self.is_bedrock() or self.is_vertex():
            return False
        else:
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
    ) -> Tuple[
        list[TextBlockParam] | None,
        list["ToolParamDef"],
        list[BetaRequestMCPServerURLDefinitionParam],
        list[MessageParam],
    ]:
        # extract system message
        system_messages, messages = split_system_messages(input, config)

        # messages
        message_params = [(await message_param(message)) for message in messages]

        # collapse user messages (as Inspect 'tool' messages become Claude 'user' messages)
        message_params = functools.reduce(
            consecutive_user_message_reducer, message_params, []
        )

        # cleave out MCP servers from tools
        tools, mcp_servers = self.partition_tools(tools)

        # tools
        tools_params = [self.tool_param_for_tool_info(tool, config) for tool in tools]

        # mcp servers
        mcp_server_params = [
            self.mcp_server_param(mcp_server) for mcp_server in mcp_servers
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
        return system_param, tools_params, mcp_server_params, message_params

    def partition_tools(
        self,
        tools: list[ToolInfo],
    ) -> tuple[list[ToolInfo], list[MCPServerConfigHTTP]]:
        standard_tools: list[ToolInfo] = []
        mcp_servers: list[MCPServerConfigHTTP] = []
        for tool in tools:
            if is_mcp_server_tool(tool):
                mcp_servers.append(MCPServerConfigHTTP.model_validate(tool.options))
            else:
                standard_tools.append(tool)
        return standard_tools, mcp_servers

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

    def mcp_server_param(
        self, mcp_server: MCPServerConfigHTTP
    ) -> BetaRequestMCPServerURLDefinitionParam:
        return BetaRequestMCPServerURLDefinitionParam(
            name=mcp_server.name,
            type="url",
            url=mcp_server.url,
            authorization_token=mcp_server.authorization_token,
            tool_configuration=BetaRequestMCPServerToolConfigurationParam(
                enabled=True, allowed_tools=mcp_server.tools
            )
            if isinstance(mcp_server.tools, list)
            else None,
        )

    def maybe_native_tool_param(
        self, tool: ToolInfo, config: GenerateConfig
    ) -> Optional["ToolParamDef"]:
        return (
            (
                self.computer_use_tool_param(tool)
                or self.text_editor_tool_param(tool)
                or self.web_search_tool_param(tool)
            )
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
    ) -> (
        ToolTextEditor20250124Param
        | BetaToolTextEditor20241022Param
        | BetaToolTextEditor20250429Param
        | None
    ):
        # See: https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/text-editor-tool#before-using-the-text-editor-tool
        # TODO: It would be great to enhance our `is_claude_xxx` functions to help here.
        if self.model_name.startswith(("claude-3-5-haiku", "claude-3-opus")):
            return None

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
                BetaToolTextEditor20250429Param(
                    type="text_editor_20250429", name="str_replace_based_edit_tool"
                )
                if self.is_claude_4()
                else BetaToolTextEditor20241022Param(
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

    def web_search_tool_param(
        self, tool: ToolInfo
    ) -> WebSearchTool20250305Param | None:
        if (
            tool.name == "web_search"
            and tool.options
            and "anthropic" in tool.options
            and _supports_web_search(self.model_name)
        ):
            return _web_search_tool_param(tool.options["anthropic"])
        else:
            return None


def _supports_web_search(model_name: str) -> bool:
    """Check if the model supports Anthropic's native web search tool."""
    # https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool#supported-models
    # https://docs.anthropic.com/en/docs/about-claude/models/overview#model-aliases
    # https://docs.anthropic.com/en/docs/about-claude/model-deprecations
    return model_name.startswith(
        ("claude-opus-4", "claude-sonnet-4", "claude-3-7-sonnet")
    ) or model_name in ("claude-3-5-sonnet-latest", "claude-3-5-haiku-latest")


def _web_search_tool_param(
    maybe_anthropic_options: object,
) -> WebSearchTool20250305Param:
    if maybe_anthropic_options is not None and not isinstance(
        maybe_anthropic_options, dict
    ):
        raise TypeError(
            f"Expected a dictionary for anthropic_options, got {type(maybe_anthropic_options)}"
        )

    result = WebSearchTool20250305Param(
        name="web_search",
        type="web_search_20250305",
    )

    if maybe_anthropic_options:
        if "allowed_domains" in maybe_anthropic_options:
            result["allowed_domains"] = maybe_anthropic_options["allowed_domains"]
        if "blocked_domains" in maybe_anthropic_options:
            result["blocked_domains"] = maybe_anthropic_options["blocked_domains"]
        if "cache_control" in maybe_anthropic_options:
            result["cache_control"] = maybe_anthropic_options["cache_control"]
        if "max_uses" in maybe_anthropic_options:
            result["max_uses"] = maybe_anthropic_options["max_uses"]
        if "user_location" in maybe_anthropic_options:
            result["user_location"] = maybe_anthropic_options["user_location"]

    return result


# tools can be either a stock tool param or a special Anthropic native use tool param
ToolParamDef = (
    ToolParam
    | BetaToolComputerUse20250124Param
    | ToolTextEditor20250124Param
    | BetaToolTextEditor20241022Param
    | BetaToolTextEditor20250429Param
    | WebSearchTool20250305Param
)


def is_tool_param(param: ToolParamDef) -> TypeGuard[ToolParam]:
    return "input_schema" in param


def is_text_editor_tool(
    param: ToolParamDef,
) -> TypeGuard[
    ToolTextEditor20250124Param
    | BetaToolTextEditor20241022Param
    | BetaToolTextEditor20250429Param
]:
    type = param.get("type", None)
    if type is not None:
        return type.startswith("text_editor") and not is_tool_param(param)
    else:
        return False


def is_computer_tool(
    param: ToolParamDef,
) -> TypeGuard[BetaToolComputerUse20250124Param]:
    return param.get("name") == "computer" and not is_tool_param(param)


def is_web_search_tool(param: ToolParamDef) -> TypeGuard[WebSearchTool20250305Param]:
    return param.get("name") == "web_search" and not is_tool_param(param)


def add_cache_control(
    param: TextBlockParam
    | ToolParam
    | BetaToolComputerUse20250124Param
    | ToolTextEditor20250124Param
    | BetaToolTextEditor20241022Param
    | BetaToolTextEditor20250429Param
    | WebSearchTool20250305Param
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


def message_tool_choice(tool_choice: ToolChoice) -> message_create_params.ToolChoice:
    if isinstance(tool_choice, ToolFunction):
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
            content: str | list[MessageBlockParam] = message.error.message
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
                item
                for content in message.content
                for item in await message_block_params(content)
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
    elif message.role == "assistant":
        block_params = await assistant_message_block_params(message)

        return MessageParam(
            role=message.role,
            content=block_params,  # type: ignore[typeddict-item]
        )

    # normal text content
    elif isinstance(message.content, str):
        return MessageParam(role=message.role, content=message.content or NO_CONTENT)

    # mixed text/images
    else:
        return MessageParam(
            role=message.role,
            content=[
                item  # type: ignore[misc]
                for content in message.content
                for item in await message_block_params(content)
            ],
        )


MessageBlock = Union[
    TextBlock
    | ThinkingBlock
    | RedactedThinkingBlock
    | ToolUseBlock
    | ServerToolUseBlock
    | WebSearchToolResultBlock
    | BetaMCPToolUseBlock
    | BetaMCPToolResultBlock
]

MessageBlockParam = Union[
    TextBlockParam
    | ThinkingBlockParam
    | RedactedThinkingBlockParam
    | DocumentBlockParam
    | ImageBlockParam
    | ToolUseBlockParam
    | ServerToolUseBlockParam
    | WebSearchToolResultBlockParam
    | BetaMCPToolUseBlockParam
    | BetaRequestMCPToolResultBlockParam
]


async def assistant_message_blocks(message: ChatMessageAssistant) -> list[MessageBlock]:
    blocks: list[MessageBlock] = []
    block_params = await assistant_message_block_params(message)
    for block_param in block_params:
        if block_param["type"] == "text":
            blocks.append(TextBlock.model_validate(block_param))
        elif block_param["type"] == "thinking":
            blocks.append(ThinkingBlock.model_validate(block_param))
        elif block_param["type"] == "redacted_thinking":
            blocks.append(RedactedThinkingBlock.model_validate(block_param))
        elif block_param["type"] == "tool_use":
            blocks.append(ToolUseBlock.model_validate(block_param))
        elif block_param["type"] == "server_tool_use":
            blocks.append(ServerToolUseBlock.model_validate(block_param))
        elif block_param["type"] == "web_search_tool_result":
            blocks.append(WebSearchToolResultBlock.model_validate(block_param))
        elif block_param["type"] == "mcp_tool_use":
            blocks.append(BetaMCPToolUseBlock.model_validate(block_param))
        elif block_param["type"] == "mcp_tool_result":
            blocks.append(BetaMCPToolResultBlock.model_validate(block_param))
        else:
            logger.warning(
                f"Unexpecxted assistant message block type: {block_param['type']}"
            )

    return blocks


async def assistant_message_block_params(
    message: ChatMessageAssistant,
) -> list[MessageBlockParam]:
    block_params: list[MessageBlockParam] = (
        [TextBlockParam(type="text", text=message.content or NO_CONTENT)]
        if isinstance(message.content, str)
        else (
            [
                item
                for content in message.content
                for item in await message_block_params(content)
            ]
        )
    )

    # move the first instance of thinking to the front
    for i, c in enumerate(block_params):
        if c["type"] in ["thinking", "redacted_thinking"] and i > 0:
            block_params.pop(i)
            block_params.insert(0, c)
            break

    # filter out empty text content (sometimes claude passes empty text
    # context back with tool calls but won't let us play them back)
    block_params = [
        c for c in block_params if not c["type"] == "text" or len(c["text"]) > 0
    ]

    # now add tools
    for tool_call in message.tool_calls or []:
        internal_name = _internal_name_from_tool_call(tool_call)
        block_params.append(
            ToolUseBlockParam(
                type="tool_use",
                id=tool_call.id,
                name=internal_name or tool_call.function,
                input=tool_call.arguments,
            )
        )

    return block_params


@dataclass
class _AssistantInternal:
    tool_call_internal_names: dict[str, str | None] = field(default_factory=dict)
    server_mcp_tool_uses: dict[
        str, tuple[BetaMCPToolUseBlockParam, BetaRequestMCPToolResultBlockParam]
    ] = field(default_factory=dict)
    server_web_searches: dict[
        str, tuple[ServerToolUseBlockParam, WebSearchToolResultBlockParam]
    ] = field(default_factory=dict)


def assistant_internal() -> _AssistantInternal:
    return _anthropic_assistant_internal.get()


def init_sample_anthropic_assistant_internal() -> None:
    _anthropic_assistant_internal.set(_AssistantInternal())


_anthropic_assistant_internal: ContextVar[_AssistantInternal] = ContextVar(
    "anthropic_assistant_internal", default=_AssistantInternal()
)


async def model_output_from_message(
    client: AsyncAnthropic | AsyncAnthropicBedrock | AsyncAnthropicVertex,
    model: str,
    message: Message,
    tools: list[ToolInfo],
) -> tuple[ModelOutput, bool]:
    # extract content and tool calls
    content, tool_calls = content_and_tool_calls_from_assistant_content_blocks(
        message.content, tools
    )

    # count reasoning tokens
    reasoning_tokens = 0
    for content_block in message.content:
        if isinstance(content_block, ThinkingBlock):
            reasoning_tokens += await count_tokens(
                client, model, content_block.thinking
            )

    # resolve choice
    stop_reason, pause_turn = message_stop_reason(message)
    choice = ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=content, tool_calls=tool_calls, model=model, source="generate"
        ),
        stop_reason=stop_reason,
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
    return (
        ModelOutput(
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
        ),
        pause_turn,
    )


content_block_adapter = TypeAdapter[ContentBlock](ContentBlock)


def content_and_tool_calls_from_assistant_content_blocks(
    content_blocks_input: Sequence[ContentBlockParam | ContentBlock],
    tools: list[ToolInfo],
) -> tuple[list[Content], list[ToolCall] | None]:
    # reoslve params to blocks
    content_blocks: list[ContentBlock] = []
    for block in content_blocks_input:
        if isinstance(block, dict):
            content_blocks.append(content_block_adapter.validate_python(block))
        else:
            content_blocks.append(block)

    # extract content and tool calls
    content: list[Content] = []
    tool_calls: list[ToolCall] | None = None

    pending_tool_uses: dict[str, ServerToolUseBlock] = dict()
    pending_mcp_tool_uses: dict[str, BetaMCPToolUseBlock] = dict()
    for content_block in content_blocks:
        if content_block.type == "mcp_tool_use":  # type: ignore[comparison-overlap]
            tool_use_block = BetaMCPToolUseBlock.model_validate(
                content_block.model_dump()
            )
            pending_mcp_tool_uses[tool_use_block.id] = tool_use_block
        elif content_block.type == "mcp_tool_result":  # type: ignore[comparison-overlap]
            tool_result_block = BetaMCPToolResultBlock.model_validate(
                content_block.model_dump()
            )
            pending_mcp_tool_use = pending_mcp_tool_uses.get(
                tool_result_block.tool_use_id, None
            )
            if pending_mcp_tool_use is None:
                raise RuntimeError(
                    "MCPToolResultBlock without previous MCPToolUseBlock"
                )

            # record in internal
            assistant_internal().server_mcp_tool_uses[tool_result_block.tool_use_id] = (
                pending_mcp_tool_use.model_dump(exclude_none=True),
                tool_result_block.model_dump(exclude_none=True),
            )

            content.append(
                ContentToolUse(
                    tool_type="mcp_call",
                    id=tool_result_block.tool_use_id,
                    name=pending_mcp_tool_use.name,
                    context=pending_mcp_tool_use.server_name,
                    arguments=to_json_str_safe(pending_mcp_tool_use.input),
                    result=tool_result_block.content
                    if isinstance(tool_result_block.content, str)
                    else to_json_str_safe(
                        [
                            c.model_dump(exclude_none=True)
                            for c in tool_result_block.content
                        ]
                    ),
                    error="error" if tool_result_block.is_error else None,
                )
            )
        elif isinstance(content_block, TextBlock):
            # if this was a tool call then remove <result></result> tags that
            # claude sometimes likes to insert!
            content_text = content_block.text
            if len(tools) > 0:
                content_text = content_text.replace("<result>", "").replace(
                    "</result>", ""
                )

            # parse out <internal> tags which might be here due to the bridge
            content_text, content_internal = parse_content_with_internal(
                content_text, CONTENT_INTERNAL_TAG
            )

            content.append(
                ContentText(
                    type="text",
                    text=content_text,
                    internal=content_internal,
                    citations=(
                        [
                            to_inspect_citation(citation)
                            for citation in content_block.citations
                        ]
                        if content_block.citations
                        else None
                    ),
                )
            )
        elif isinstance(content_block, ToolUseBlock):
            tool_calls = tool_calls or []
            (tool_name, internal_name) = _names_for_tool_call(content_block.name, tools)
            assistant_internal().tool_call_internal_names[content_block.id] = (
                internal_name
            )
            tool_calls.append(
                ToolCall(
                    id=content_block.id,
                    function=tool_name,
                    arguments=content_block.model_dump().get("input", {}),
                )
            )
        elif isinstance(content_block, ServerToolUseBlock):
            pending_tool_uses[content_block.id] = content_block
        elif isinstance(content_block, WebSearchToolResultBlock):
            pending_tool_use = pending_tool_uses.get(content_block.tool_use_id, None)
            if pending_tool_use is None:
                raise RuntimeError(
                    "WebSearchToolResultBlock without previous ServerToolUseBlock"
                )

            # record in internal
            assistant_internal().server_web_searches[pending_tool_use.id] = (
                cast(
                    ServerToolUseBlockParam,
                    pending_tool_use.model_dump(exclude_none=True),
                ),
                cast(
                    WebSearchToolResultBlockParam,
                    content_block.model_dump(exclude_none=True),
                ),
            )

            content.append(
                ContentToolUse(
                    tool_type="web_search",
                    id=pending_tool_use.id,
                    name=pending_tool_use.name,
                    arguments=to_json_str_safe(pending_tool_use.input),
                    result=web_search_result_block_adapter.dump_json(
                        content_block.content, exclude_none=True
                    ).decode(),
                    error=content_block.content.error_code
                    if isinstance(content_block.content, WebSearchToolResultError)
                    else None,
                )
            )
        elif isinstance(content_block, RedactedThinkingBlock):
            content.append(
                ContentReasoning(reasoning=content_block.data, redacted=True)
            )
        elif isinstance(content_block, ThinkingBlock):
            content.append(
                ContentReasoning(
                    reasoning=content_block.thinking, signature=content_block.signature
                )
            )

    return content, tool_calls


def _internal_name_from_tool_call(tool_call: ToolCall) -> str | None:
    return assistant_internal().tool_call_internal_names.get(tool_call.id, None)


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
        ("str_replace_based_edit_tool", "text_editor_20250429", "text_editor"),
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


def message_stop_reason(message: Message) -> tuple[StopReason, bool]:
    match message.stop_reason:
        case "end_turn" | "stop_sequence":
            return "stop", False
        case "tool_use":
            return "tool_calls", False
        case "max_tokens":
            return message.stop_reason, False
        case "refusal":
            return "content_filter", False
        case _:
            return "unknown", message.stop_reason == "pause_turn"


def split_system_messages(
    input: list[ChatMessage], config: GenerateConfig
) -> Tuple[list[ChatMessageSystem], list[ChatMessage]]:
    # split messages
    system_messages = [m for m in input if isinstance(m, ChatMessageSystem)]
    messages = [m for m in input if not isinstance(m, ChatMessageSystem)]

    # return
    return system_messages, cast(list[ChatMessage], messages)


web_search_result_block_param_adapter = TypeAdapter[
    WebSearchToolResultBlockParamContentParam
](WebSearchToolResultBlockParamContentParam)


web_search_result_block_adapter = TypeAdapter[
    WebSearchToolResultError | list[WebSearchResultBlock]
](WebSearchToolResultError | list[WebSearchResultBlock])


beta_text_block_param_adapter = TypeAdapter[Union[str, Iterable[BetaTextBlockParam]]](
    Union[str, Iterable[BetaTextBlockParam]]
)


async def message_block_params(
    content: Content,
) -> list[MessageBlockParam]:
    if isinstance(content, ContentText):
        text = content.text or NO_CONTENT
        if content.internal:
            text = f"{text}\n{content_internal_tag(content.internal)}"

        citations = (
            [
                citation
                for citation in (
                    to_anthropic_citation(citation) for citation in content.citations
                )
                if citation is not None
            ]
            if content.citations
            else None
        )

        return [TextBlockParam(type="text", text=text, citations=citations)]
    elif isinstance(content, ContentImage):
        return [await image_block_param(content.image)]

    elif isinstance(content, ContentReasoning):
        if content.redacted:
            return [
                RedactedThinkingBlockParam(
                    type="redacted_thinking",
                    data=content.reasoning,
                )
            ]
        else:
            if content.signature is None:
                raise ValueError("Thinking content without signature.")
            return [
                ThinkingBlockParam(
                    type="thinking",
                    thinking=content.reasoning,
                    signature=content.signature,
                )
            ]

    elif isinstance(content, ContentToolUse):
        if content.id in assistant_internal().server_mcp_tool_uses:
            return list(assistant_internal().server_mcp_tool_uses[content.id])

        elif content.id in assistant_internal().server_web_searches:
            return list(assistant_internal().server_web_searches[content.id])

        if content.tool_type == "web_search":
            # we might be parsing an openai web search result so defend ourselves accordingly
            try:
                result_content = web_search_result_block_param_adapter.validate_json(
                    content.result
                )
            except ValidationError:
                result_content = WebSearchToolRequestErrorParam(
                    type="web_search_tool_result_error", error_code="unavailable"
                )

            return [
                ServerToolUseBlockParam(
                    id=content.id,
                    input=json.loads(content.arguments),
                    type="server_tool_use",
                    name="web_search",
                ),
                WebSearchToolResultBlockParam(
                    content=result_content,
                    tool_use_id=content.id,
                    type="web_search_tool_result",
                ),
            ]
        elif content.tool_type == "mcp_call":
            # we might be parsing an openai mcp tool result so defend ourselves accordingly
            try:
                mcp_result_content = beta_text_block_param_adapter.validate_json(
                    content.result
                )
            except ValidationError:
                mcp_result_content = content.result

            return [
                BetaMCPToolUseBlockParam(
                    id=content.id,
                    input=json.loads(content.arguments),
                    name=content.name,
                    server_name=content.context or "",
                    type="mcp_tool_use",
                ),
                BetaRequestMCPToolResultBlockParam(
                    tool_use_id=content.id,
                    type="mcp_tool_result",
                    content=mcp_result_content,
                    is_error=content.error is not None and len(content.error) > 0,
                ),
            ]
        else:
            raise RuntimeError(
                f"Unexpected tool use: {content.tool_type}/{content.name}"
            )
    elif isinstance(content, ContentDocument):
        if content.mime_type == "application/pdf":
            if is_http_url(content.document):
                source: Source = URLPDFSourceParam(type="url", url=content.document)
            else:
                pdf_data_uri = await file_as_data_uri(content.document)
                pdf_data = data_uri_to_base64(pdf_data_uri)
                source = Base64PDFSourceParam(
                    type="base64", data=pdf_data, media_type="application/pdf"
                )
        elif is_image_type(content.mime_type):
            source = ContentBlockSourceParam(
                type="content", content=[await image_block_param(content.document)]
            )
        else:
            file_bytes, _ = await file_as_data(content.document)
            source = PlainTextSourceParam(
                type="text", media_type="text/plain", data=file_bytes.decode()
            )
        return [
            DocumentBlockParam(type="document", source=source, title=content.filename)
        ]

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


def _content_list(input: str | list[Content]) -> list[Content]:
    if isinstance(input, str):
        # parse out <internal> tags which might be here due to the bridge
        input, content_internal = parse_content_with_internal(
            input, CONTENT_INTERNAL_TAG
        )
        return [ContentText(text=input, internal=content_internal)]
    else:
        return input


async def image_block_param(image: str) -> ImageBlockParam:
    # resolve to url
    image = await file_as_data_uri(image)

    # resolve mime type and base64 content
    media_type = data_uri_mime_type(image) or "image/png"
    image = data_uri_to_base64(image)

    if not is_image_type(media_type):
        raise ValueError(f"Unable to read image of type {media_type}")

    return ImageBlockParam(
        type="image",
        source=dict(type="base64", media_type=cast(Any, media_type), data=image),
    )


def is_image_type(media_type: str) -> bool:
    return media_type in ["image/jpeg", "image/png", "image/gif", "image/webp"]


def anthropic_extra_body_fields() -> list[str]:
    return ["metadata", "service_tier"]
