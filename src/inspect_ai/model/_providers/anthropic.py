import functools
import json
import os
import re
from contextvars import ContextVar
from copy import copy, deepcopy
from dataclasses import dataclass, field
from logging import getLogger
from typing import (
    Any,
    Iterable,
    Literal,
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
    AsyncAnthropicFoundry,
    AsyncAnthropicVertex,
    BadRequestError,
    NotGiven,
)
from anthropic.lib.streaming import AsyncMessageStream
from anthropic.types import (
    Base64PDFSourceParam,
    CacheControlEphemeralParam,
    CodeExecutionToolResultBlock,
    CodeExecutionToolResultBlockParam,
    Container,
    ContentBlock,
    ContentBlockParam,
    ContentBlockSourceParam,
    DocumentBlockParam,
    ImageBlockParam,
    Message,
    MessageParam,
    OutputConfigParam,
    PlainTextSourceParam,
    RedactedThinkingBlock,
    RedactedThinkingBlockParam,
    ServerToolUseBlock,
    ServerToolUseBlockParam,
    TextBlock,
    TextBlockParam,
    ThinkingBlock,
    ThinkingBlockParam,
    ToolChoiceAnyParam,
    ToolChoiceAutoParam,
    ToolChoiceNoneParam,
    ToolChoiceParam,
    ToolChoiceToolParam,
    ToolParam,
    ToolResultBlockParam,
    ToolTextEditor20250124Param,
    ToolUseBlock,
    ToolUseBlockParam,
    URLPDFSourceParam,
    WebSearchResultBlock,
    WebSearchTool20250305Param,
    WebSearchTool20260209Param,
    WebSearchToolRequestErrorParam,
    WebSearchToolResultBlock,
    WebSearchToolResultBlockParam,
    WebSearchToolResultError,
)
from anthropic.types.beta import (
    BetaBashCodeExecutionResultBlockParam,
    BetaBashCodeExecutionToolResultBlock,
    BetaBashCodeExecutionToolResultBlockParam,
    BetaCodeExecutionTool20250825Param,
    BetaCompact20260112EditParam,
    BetaCompactionBlock,
    BetaCompactionBlockParam,
    BetaDirectCaller,
    BetaFallbackBlock,
    BetaFallbackBlockParam,
    BetaFallbackInfoParam,
    BetaInputTokensTriggerParam,
    BetaMCPToolResultBlock,
    BetaMCPToolUseBlock,
    BetaMCPToolUseBlockParam,
    BetaMemoryTool20250818Param,
    BetaRedactedThinkingBlock,
    BetaRequestMCPServerToolConfigurationParam,
    BetaRequestMCPServerURLDefinitionParam,
    BetaRequestMCPToolResultBlockParam,
    BetaServerToolUseBlock,
    BetaServerToolUseBlockParam,
    BetaTextBlock,
    BetaTextBlockParam,
    BetaTextEditorCodeExecutionToolResultBlock,
    BetaTextEditorCodeExecutionToolResultBlockParam,
    BetaThinkingBlock,
    BetaToolBash20250124Param,
    BetaToolComputerUse20250124Param,
    BetaToolComputerUse20251124Param,
    BetaToolTextEditor20241022Param,
    BetaToolTextEditor20250429Param,
    BetaToolTextEditor20250728Param,
    BetaToolUseBlock,
    BetaWebFetchTool20250910Param,
    BetaWebFetchTool20260209Param,
    BetaWebFetchToolResultBlock,
    BetaWebFetchToolResultBlockParam,
    BetaWebSearchToolResultBlock,
)
from anthropic.types.document_block_param import Source
from anthropic.types.web_search_tool_result_block_param_content_param import (
    WebSearchToolResultBlockParamContentParam,
)
from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError
from typing_extensions import override

from inspect_ai._util.constants import BASE_64_DATA_REMOVED, NO_CONTENT
from inspect_ai._util.content import (
    Content,
    ContentData,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
from inspect_ai._util.error import PrerequisiteError, exception_message
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.http import (
    is_retryable_http_status,
    parse_retry_after_from_exception,
)
from inspect_ai._util.images import file_as_data, file_as_data_uri
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.logger import warn_once
from inspect_ai._util.trace import trace_message
from inspect_ai._util.url import data_uri_mime_type, data_uri_to_base64, is_http_url
from inspect_ai.log._samples import set_active_model_event_call
from inspect_ai.model._compaction.edit import (
    TOOL_RESULT_REMOVED,
    is_result_cleared,
)
from inspect_ai.model._internal import (
    CONTENT_INTERNAL_TAG,
    content_internal_tag,
    parse_content_with_internal,
)
from inspect_ai.model._retry import batch_admin_retry_config
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.tool._mcp._remote import is_mcp_server_tool
from inspect_ai.tool._tools._computer._computer import is_computer_tool_info
from inspect_ai.util._json import (
    JSON_SCHEMA_EXTENDED_FIELDS,
    json_schema_dump,
    set_additional_properties_false,
)

from ..._util.httpx import httpx_classify_retry
from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig, normalized_batch_config
from .._model import ModelAPI, RetryDecision
from .._model_call import ModelCall, as_error_response
from .._model_output import (
    ChatCompletionChoice,
    ModelFallback,
    ModelOutput,
    ModelUsage,
    StopCategory,
    StopDetails,
    StopReason,
    collect_stop_details,
)
from .._providers._anthropic_citations import (
    to_anthropic_citation,
    to_inspect_citation,
)
from .._reasoning import effort_to_reasoning_tokens
from ._anthropic_batch import AnthropicBatcher
from .util import (
    check_azure_deployment_mismatch,
    environment_prerequisite_error,
    model_base_url,
    require_azure_base_url,
    resolve_api_key,
)
from .util.hooks import HttpxHooks

logger = getLogger(__name__)

ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
AZUREAI_ANTHROPIC_API_KEY = "AZUREAI_ANTHROPIC_API_KEY"

_THINKING_WARNING = (
    "anthropic models do not support the '{parameter}' parameter "
    "when using extended thinking."
)
_ADAPTIVE_ONLY_WARNING = (
    "anthropic model '{model}' does not support the '{parameter}' parameter "
    "(adaptive thinking only)."
)
_REASONING_TOKENS_UNSUPPORTED_ERROR = (
    "anthropic model '{model}' does not support 'reasoning_tokens' (extended "
    "thinking with an explicit token budget was removed in Claude 4.7). Use "
    "'reasoning_effort' to control reasoning depth instead."
)
_MID_CONV_SYSTEM_HOISTED_WARNING = (
    "anthropic: {count} mid-conversation system message(s) were repositioned "
    "to the top-level system field because their placement violated the API "
    "invariants (a mid-conversation system message must immediately follow a "
    "user turn or an assistant turn ending in server tool use, and must "
    "either end the message array or precede an assistant turn)."
)
_REMINDER_SYSTEM_HOISTED_WARNING = (
    "anthropic: {count} mid-conversation system message(s) were hoisted to the "
    "top-level system field because they sit adjacent to a tool result. "
    "Rendering them as user turns would merge them into the tool-result turn "
    "(tool results map to user-role messages), which strips prior thinking and "
    "cache context on tool-use continuations."
)
_CACHE_DIAGNOSIS_BETA = "cache-diagnosis-2026-04-07"
_CACHE_MISS_WARNING = (
    "anthropic cache diagnostics: cache miss detected (reason: {reason})."
)
AZURE_ANTHROPIC_API_KEY = "AZURE_ANTHROPIC_API_KEY"

# Azure base URL environment variables
AZURE_ANTHROPIC_BASE_URL_VARS = [
    "AZUREAI_ANTHROPIC_BASE_URL",
    "AZURE_ANTHROPIC_BASE_URL",
]

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
        cache_ttl: Literal["5m", "1h"] | None = None,
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

        # validate and record prompt cache ttl
        if cache_ttl is not None and cache_ttl not in ("5m", "1h"):
            raise ValueError(
                f"Invalid cache_ttl '{cache_ttl}': valid values are '5m' and '1h'."
            )
        self.cache_ttl = cache_ttl

        # collect generate model_args (then delete them so we can pass the rest on)
        def collect_model_arg(name: str) -> Any | None:
            nonlocal model_args
            value = model_args.get(name, None)
            if value is not None:
                model_args.pop(name)
            return value

        self.extra_body: dict[str, Any] | None = collect_model_arg(EXTRA_BODY)

        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[
                ANTHROPIC_API_KEY,
                AZUREAI_ANTHROPIC_API_KEY,
                AZURE_ANTHROPIC_API_KEY,
            ],
            config=config,
        )

        # check for Azure model/URL mismatch
        if self.is_azure():
            check_azure_deployment_mismatch(
                self.service_model_name(),
                base_url,
                AZURE_ANTHROPIC_BASE_URL_VARS,
                "AZUREAI_ANTHROPIC",
            )

        self.model_args = model_args
        self.initialize()

    def _create_client(
        self,
    ) -> (
        AsyncAnthropic
        | AsyncAnthropicBedrock
        | AsyncAnthropicVertex
        | AsyncAnthropicFoundry
    ):
        if self.is_bedrock():
            base_url = model_base_url(
                self.base_url,
                ["ANTHROPIC_BEDROCK_BASE_URL", "BEDROCK_ANTHROPIC_BASE_URL"],
            )

            # resolve the default region
            aws_region = None
            base_region = os.environ.get("AWS_REGION", None)
            if base_region is None:
                aws_region = os.environ.get("AWS_DEFAULT_REGION", None)

            return AsyncAnthropicBedrock(
                base_url=base_url,
                aws_region=aws_region,
                **self.model_args,
            )
        elif self.is_vertex():
            base_url = model_base_url(
                self.base_url,
                ["ANTHROPIC_VERTEX_BASE_URL", "VERTEX_ANTHROPIC_BASE_URL"],
            )
            region = os.environ.get("ANTHROPIC_VERTEX_REGION", NotGiven())
            project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", NotGiven())
            return AsyncAnthropicVertex(
                region=region,
                project_id=project_id,
                base_url=base_url,
                **self.model_args,
            )
        elif self.is_azure():
            # resolve base_url (required for Azure)
            base_url = require_azure_base_url(
                self.base_url, AZURE_ANTHROPIC_BASE_URL_VARS, "Anthropic"
            )

            # resolve api_key (required for Azure)
            if not self.api_key:
                self.api_key = resolve_api_key(
                    [AZUREAI_ANTHROPIC_API_KEY, AZURE_ANTHROPIC_API_KEY]
                )
            if not self.api_key:
                raise environment_prerequisite_error(
                    "Anthropic on Azure",
                    [AZUREAI_ANTHROPIC_API_KEY, AZURE_ANTHROPIC_API_KEY],
                )

            return AsyncAnthropicFoundry(
                base_url=base_url,
                api_key=self.api_key,
                **self.model_args,
            )
        else:
            base_url = model_base_url(self.base_url, "ANTHROPIC_BASE_URL")
            # Support OAuth Bearer auth via ANTHROPIC_AUTH_TOKEN. When set,
            # create the client with auth_token= (sends Authorization: Bearer)
            # instead of api_key= (sends X-Api-Key). The Anthropic API rejects
            # requests that have both headers if the X-Api-Key is invalid, so
            # we must use one or the other — not both.
            auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
            if auth_token:
                return AsyncAnthropic(
                    base_url=base_url,
                    auth_token=auth_token,
                    default_headers={
                        "anthropic-beta": "oauth-2025-04-20",
                    },
                    **self.model_args,
                )
            # resolve api_key
            if not self.api_key:
                self.api_key = os.environ.get(ANTHROPIC_API_KEY, None)
            if self.api_key is None:
                raise environment_prerequisite_error("Anthropic", ANTHROPIC_API_KEY)
            return AsyncAnthropic(
                base_url=base_url,
                api_key=self.api_key,
                **self.model_args,
            )

    @override
    def initialize(self) -> None:
        super().initialize()
        self.client = self._create_client()
        self._http_hooks = HttpxHooks(self.client._client)
        self._batcher: AnthropicBatcher | None = None

    @override
    async def aclose(self) -> None:
        await self.client.close()

    def is_bedrock(self) -> bool:
        return self.service == "bedrock"

    def is_vertex(self) -> bool:
        return self.service == "vertex"

    def is_azure(self) -> bool:
        return self.service == "azure"

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput | Exception, ModelCall]:
        # allocate request_id (so we can see it from ModelCall)
        request_id = self._http_hooks.start_request()

        model_call: ModelCall | None = None

        # generate
        try:
            (
                system_param,
                tools_param,
                mcp_servers_param,
                messages,
                cache_prompt,
            ) = await self.resolve_chat_input(input, tools, config)

            # prepare request params (assembled this way so we can log the raw model call)
            request: dict[str, Any] = dict(messages=messages)

            # automatic caching for messages (system/tools use explicit breakpoints).
            # Per Anthropic's docs, the top-level `cache_control` field is only
            # supported on the direct Claude API and Azure AI Foundry (preview);
            # "support for Amazon Bedrock and Google Vertex AI is coming later." On
            # those services it is rejected as
            # `cache_control: Extra inputs are not permitted`. Fall back to the
            # per-block markers added in resolve_chat_input on those services.
            # ref: https://docs.claude.com/en/docs/build-with-claude/prompt-caching#automatic-caching
            if cache_prompt and not (self.is_bedrock() or self.is_vertex()):
                request["cache_control"] = cache_control_param(self.cache_ttl)

            # system messages and tools
            if system_param is not None:
                request["system"] = system_param
            request["tools"] = tools_param
            if len(tools_param) > 0 and not self.is_using_thinking(config):
                request["tool_choice"] = message_tool_choice(tool_choice, config)

            # additional options
            req, extra_body, headers, betas = self.completion_config(config)
            request = request | req

            # beta param for mcp tools
            if len(mcp_servers_param) > 0:
                betas.append("mcp-client-2025-04-04")

            # beta param for interleaved thinking
            if self.is_using_thinking(config) and (
                self.is_claude_4() or self.is_claude_5() or self.is_claude_latest()
            ):
                betas.append("interleaved-thinking-2025-05-14")

            # extra headers (for time tracker and computer use)
            extra_headers = headers | {HttpxHooks.REQUEST_ID_HEADER: request_id}
            if any(
                tool.get("type", None) == "computer_20251124" for tool in tools_param
            ):
                betas.append("computer-use-2025-11-24")
            elif any(
                tool.get("type", None) == "computer_20250124" for tool in tools_param
            ):
                # From: https://docs.anthropic.com/en/docs/agents-and-tools/computer-use#claude-3-7-sonnet-beta-flag
                # Note: The Bash (bash_20250124) and Text Editor (text_editor_20250124)
                # tools are generally available for Claude 3.5 Sonnet (new) as well and
                # can be used without the computer use beta header.
                betas.append("computer-use-2025-01-24")
            if any("20241022" in str(tool.get("type", "")) for tool in tools_param):
                betas.append("computer-use-2024-10-22")
            if any(tool.get("type", None) == "memory_20250818" for tool in tools_param):
                betas.append("context-management-2025-06-27")
            if any(
                tool.get("type", None) == "code_execution_20250825"
                for tool in tools_param
            ):
                betas.append("code-execution-2025-08-25")
            if any(
                tool.get("type", None) == "web_fetch_20250910" for tool in tools_param
            ):
                betas.append("web-fetch-2025-09-10")

            # extra_body
            if len(extra_body) > 0 or self.extra_body is not None:
                request[EXTRA_BODY] = extra_body | (self.extra_body or {})

            # cache diagnostics: thread the previous response id forward. The
            # SDK only exposes `diagnostics` on client.beta.messages.create,
            # but inspect calls client.messages.create — route via extra_body
            # so the field reaches /v1/messages without SDK kwarg validation.
            if self.cache_diagnostics_enabled(config):
                prev_id = _previous_assistant_message_id(input)
                request[EXTRA_BODY] = (request.get(EXTRA_BODY) or {}) | {
                    "diagnostics": {"previous_message_id": prev_id},
                }

            # add compaction if the input has it and there is no config
            if _input_has_compaction(input) and not _request_has_edit_compaction(
                request
            ):
                _add_edit_compaction(
                    request=request,
                    betas=betas,
                    has_1mm_context=self.is_claude_frontier(),
                )

            # add compaction beta header if required
            if _request_has_edit_compaction(request):
                betas.append("compact-2026-01-12")

            # add fallback beta header if the input contains fallback blocks
            # (so replayed blocks are accepted even if fallback_models is no
            # longer configured, e.g. on a resumed eval with changed config)
            if FALLBACK_BETA not in betas and _input_has_fallback(input):
                betas.append(FALLBACK_BETA)

            # resolve betas and extra headers — preserve any client default
            # betas (e.g. oauth-2025-04-20 set via ANTHROPIC_AUTH_TOKEN)
            if len(betas) > 0:
                for b in self._client_default_betas():
                    if b not in betas:
                        betas.insert(0, b)
                betas = list(dict.fromkeys(betas))  # remove duplicates
                extra_headers["anthropic-beta"] = ",".join(betas)
            request["extra_headers"] = extra_headers

            # mcp servers
            if len(mcp_servers_param) > 0:
                if EXTRA_BODY not in request:
                    request[EXTRA_BODY] = dict()
                request[EXTRA_BODY]["mcp_servers"] = mcp_servers_param

            # resume the prior turn's code execution container if it left
            # work pending (e.g. a client tool call cut the turn short)
            container = _pending_container_for_input(input)
            if container is not None:
                request["container"] = container

            model_call = set_active_model_event_call(request, model_call_filter)

            # stream if we are using reasoning or >= 8192 max_tokens
            streaming = (
                self.auto_streaming(config)
                if self.streaming == "auto"
                else self.streaming
            )

            try:
                response, output = await self._perform_request_and_continuations(
                    request, streaming, tools, config
                )
            except (BadRequestError, APIStatusError) as ex:
                model_call.set_error(
                    as_error_response(ex.body), self._http_hooks.end_request(request_id)
                )
                raise ex

            model_call.set_response(response, self._http_hooks.end_request(request_id))

            _warn_refusal_without_fallback(self, config, output)

            return output, model_call

        except BadRequestError as ex:
            return self.handle_bad_request(ex), model_call or ModelCall(request={})

        except APIStatusError as ex:
            if ex.status_code == 413:
                return ModelOutput.from_content(
                    model=self.service_model_name(),
                    content=ex.message,
                    stop_reason="model_length",
                    error=ex.message,
                ), model_call or ModelCall(request={})
            # Content-filter errors that arrive mid-stream surface as a plain
            # APIStatusError (the SDK can't infer the 400 subclass once the
            # HTTP response was 200), so route through handle_bad_request to
            # convert them into a content_filter refusal.
            handled = self.handle_bad_request(ex)
            if isinstance(handled, ModelOutput):
                return handled, model_call or ModelCall(request={})
            raise ex

    @override
    async def count_tokens(
        self,
        input: str | list[ChatMessage],
        config: GenerateConfig | None = None,
    ) -> int:
        """Estimate token count for an input."""
        # turn system into user for purposes of counting
        if isinstance(input, str):
            input = [ChatMessageUser(content=input)]
        input = [
            ChatMessageUser(content=m.content) if m.role == "system" else m
            for m in input
        ]

        # Check for content requiring beta opt-ins before conversion
        has_compaction = _messages_contain_compaction(input)
        has_fallback = _input_has_fallback(input)

        # Convert to Anthropic message format
        messages = [await message_param(m) for m in input]

        # Collapse consecutive user messages (as Inspect 'tool' messages become
        # Claude 'user' messages, and multiple tool results need to be merged)
        messages = functools.reduce(consecutive_user_message_reducer, messages, [])

        # Anthropic's API validates message structure even for token counting.
        # When counting tokens for individual messages (e.g., for caching in
        # compaction), we may have orphaned tool_use or tool_result blocks.
        # Pad with fake paired items to satisfy API validation.
        messages = pad_tool_messages_for_token_counting(messages)

        # count_tokens applies the same thinking-block validation as generate
        # (non-empty thinking; signatures on the latest assistant message must be
        # unmodified). Compaction counts message subsets, so an older assistant
        # turn can become the "latest" one and trip those checks — neutralize
        # thinking to plain text before counting (see the helper's docstring).
        messages = neutralize_thinking_for_token_counting(messages)

        # Beta opt-ins required for special content in the history. The API
        # validates content block types for token counting too, so replayed
        # compaction and fallback blocks need the same betas as generate.
        betas: list[str] = []
        request_extra: dict[str, Any] = {}
        if has_compaction:
            betas.append("compact-2026-01-12")
            request_extra["extra_body"] = {
                "context_management": {"edits": [{"type": "compact_20260112"}]}
            }
        if has_fallback:
            betas.append(FALLBACK_BETA)
        if betas:
            request_extra["extra_headers"] = {"anthropic-beta": ",".join(betas)}

        response = await self.client.messages.count_tokens(
            model=self.service_model_name(),
            messages=messages,
            **request_extra,
        )
        return response.input_tokens

    @override
    async def compact(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        config: GenerateConfig,
        instructions: str | None = None,
    ) -> tuple[list[ChatMessage], ModelUsage | None]:
        """Compact messages using provider-native compaction.

        Args:
            input: Chat message input (if a `str` is passed it is converted to a `ChatUserMessage`).
            tools: Tools available for the model to call.
            config: Model configuration.
            instructions: Additional instructions to give the model about compaction

        Returns:
            A tuple of (compacted_messages, usage) where compacted_messages is a
            list containing a single message with compaction metadata, and usage
            contains token counts for the compaction operation.

        Raises:
            NotImplementedError: For providers or models without native compaction support.
        """
        edit = BetaCompact20260112EditParam(
            type="compact_20260112",
            instructions=instructions,
            trigger=BetaInputTokensTriggerParam(
                type="input_tokens", value=MIN_COMPACTION_TOKENS
            ),
            pause_after_compaction=True,
        )

        # delegate to generate with context_management config
        config = config.model_copy(
            update={
                EXTRA_BODY: (config.extra_body or {})
                | {CONTEXT_MANAGEMENT: {EDITS: [edit]}}
            }
        )
        output, _ = await self.generate(input, tools, "auto", config)

        if isinstance(output, ModelOutput):
            # confirm a compaction occurred
            compaction = _compaction_from_message(output.message)
            if compaction is not None and compaction["content"] is not None:
                # Strip reasoning blocks from the compacted output — they're
                # from the compaction inference, not the task, and would waste
                # input tokens on subsequent turns.
                message = _strip_reasoning(output.message)
                return [
                    message,
                    ChatMessageUser(content="Please continue working."),
                ], output.usage
            elif compaction is not None:
                raise NotImplementedError(
                    "Anthropic compaction triggered but failed to compact."
                )
            else:
                raise NotImplementedError("Anthropic compaction did not trigger.")
        elif isinstance(output, BadRequestError):
            # Check if model doesn't support compaction
            error_msg = str(output)
            if "does not support context management" in error_msg or (
                "does not support" in error_msg and "compact" in error_msg
            ):
                raise NotImplementedError(
                    f"Model {self.model_name} does not support native compaction: {error_msg}"
                ) from output
            else:
                raise output from None
        else:
            raise output from None

    async def _perform_request_and_continuations(
        self,
        request: dict[str, Any],
        streaming: bool,
        tools: list[ToolInfo],
        config: GenerateConfig,
        pending_tool_uses: dict[str, ServerToolUseBlock | BetaServerToolUseBlock]
        | None = None,
        pending_mcp_tool_uses: dict[str, BetaMCPToolUseBlock] | None = None,
        span_recorder: "_ServerToolSpanRecorder | None" = None,
    ) -> tuple[dict[str, Any], ModelOutput]:
        """
        This helper function is split out so that it can be easily call itself recursively in cases where the model requires a continuation

        It considers the result from the initial request the "head" and the result
        from the continuation the "tail".
        """
        if pending_tool_uses is None:
            pending_tool_uses = dict()
        if pending_mcp_tool_uses is None:
            pending_mcp_tool_uses = dict()
        if span_recorder is None:
            # a server tool span can straddle a pause_turn continuation (use
            # block in the head message, result in the tail) so the recorder
            # is threaded through continuations like pending_tool_uses
            span_recorder = _ServerToolSpanRecorder()

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
                    batch_admin_retry_config(
                        self.model_name, config, self.should_retry
                    ),
                )
            head_message = await self._batcher.generate_for_request(request)
        elif streaming:
            async with self.client.messages.stream(**request) as stream:
                head_message, _ = await _capture_compaction_from_stream(stream)
        else:
            head_message = await self.client.messages.create(**request, stream=False)

        head_model_output, continuation_required = await model_output_from_message(
            self.client,
            self.service_model_name(),
            head_message,
            tools,
            pending_tool_uses=pending_tool_uses,
            pending_mcp_tool_uses=pending_mcp_tool_uses,
            cache_diagnostics=self.cache_diagnostics_enabled(config),
            span_recorder=span_recorder,
        )

        if continuation_required:
            tail_request = dict(request)
            tail_request["messages"] = request["messages"] + [
                MessageParam(role=head_message.role, content=head_message.content)
            ]
            # server tool calls (e.g. web search w/ dynamic filtering) may run
            # inside a code execution container -- reuse it for the continuation
            if head_message.container:
                tail_request["container"] = head_message.container.id
            _, tail_model_output = await self._perform_request_and_continuations(
                tail_request,
                streaming,
                tools,
                config,
                pending_tool_uses=pending_tool_uses,
                pending_mcp_tool_uses=pending_mcp_tool_uses,
                span_recorder=span_recorder,
            )

            head_content = _content_list(head_model_output.message.content)
            tail_content = _content_list(tail_model_output.message.content)
            tail_model_output.message.content = head_content + tail_content

            # server tool spans were recorded under the head and tail message
            # ids -- the merged content above lives on the tail message so
            # re-key the head message's spans under the tail message id
            merge_server_tool_spans(
                head_model_output.message.id, tail_model_output.message.id
            )

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

    def _client_default_betas(self) -> list[str]:
        """Betas set as client default headers (e.g. oauth-2025-04-20)."""
        # header names are case-insensitive; _custom_headers is a plain dict
        # that preserves the caller's original casing (e.g. 'Anthropic-Beta')
        custom_headers = getattr(self.client, "_custom_headers", {})
        client_beta = next(
            (v for k, v in custom_headers.items() if k.lower() == "anthropic-beta"),
            "",
        )
        return [b.strip() for b in client_beta.split(",") if b.strip()]

    def completion_config(
        self, config: GenerateConfig
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], list[str]]:
        # Claude 4.7+ (including Claude 5) removed extended thinking, so
        # `reasoning_tokens` (sent as `budget_tokens`) is rejected by the API.
        # Fail fast with an actionable error that names `reasoning_tokens` and
        # points to `reasoning_effort`, rather than letting the request 400 with
        # a message about `budget_tokens` the caller never set.
        if config.reasoning_tokens is not None and self.is_claude_4_7_or_later():
            raise PrerequisiteError(
                _REASONING_TOKENS_UNSUPPORTED_ERROR.format(
                    model=self.service_model_name()
                )
            )
        max_tokens = cast(int, config.max_tokens)
        params = dict(model=self.service_model_name(), max_tokens=max_tokens)
        headers: dict[str, str] = (config.extra_headers or {}).copy()
        extra_body: dict[str, Any] = {}
        betas: list[str] = self.betas.copy()

        # pull betas out of headers (accept the underscore convention and the
        # literal 'anthropic-beta' header spelling; header names are
        # case-insensitive, so match case-insensitively)
        for key in list(headers.keys()):
            if key.lower() in ("anthropic_beta", "anthropic-beta"):
                anthropic_beta_header = headers.pop(key)
                if anthropic_beta_header:
                    betas.extend([h.strip() for h in anthropic_beta_header.split(",")])

        # Claude 4.7+ is always in adaptive thinking and rejects these params
        # regardless of config; other models only reject them under thinking.
        forbid_sampling_params = (
            self.is_claude_4_7_or_later() or self.is_using_thinking(config)
        )

        def sampling_param_warning(parameter: str) -> str:
            if self.is_claude_4_7_or_later():
                return _ADAPTIVE_ONLY_WARNING.format(
                    parameter=parameter, model=self.service_model_name()
                )
            return _THINKING_WARNING.format(parameter=parameter)

        if config.temperature is not None:
            if forbid_sampling_params:
                warn_once(logger, sampling_param_warning("temperature"))
            else:
                params["temperature"] = config.temperature
        if config.top_p is not None:
            if forbid_sampling_params:
                warn_once(logger, sampling_param_warning("top_p"))
            else:
                params["top_p"] = config.top_p
        if config.top_k is not None:
            if forbid_sampling_params:
                warn_once(logger, sampling_param_warning("top_k"))
            else:
                params["top_k"] = config.top_k

        # effort
        if config.effort is not None:
            betas.append("effort-2025-11-24")
            effort = config.effort
            if effort == "max" and not (self.is_claude_frontier()):
                effort = "high"
            if effort == "xhigh" and not self.is_claude_4_7_or_later():
                effort = "high"
            params["output_config"] = OutputConfigParam(effort=effort)  # type: ignore[typeddict-item] # (no support for 'xhigh' in sdk yet)

        # some thinking-only stuff
        if self.is_using_thinking(config):
            reasoning_effort = self.effort_from_reasoning_effort(config)
            if reasoning_effort is not None:
                thinking: dict[str, Any] = dict(type="adaptive", display="summarized")
                # reasoning_effort takes precedence over effort
                params["output_config"] = OutputConfigParam(effort=reasoning_effort)  # type: ignore[typeddict-item]  # (no support for 'xhigh' in sdk yet)
            else:
                # pre-4.6 Claude: extended thinking with an explicit budget.
                # bridged_reasoning_tokens prefers reasoning_tokens, falling
                # back to a fixed-table translation of reasoning_effort.
                thinking = dict(
                    type="enabled",
                    budget_tokens=self.bridged_reasoning_tokens(config),
                    display="summarized",
                )

            # set thinking (remove 'display' for full-thinking). the beta may
            # arrive via per-request betas or as a client default header.
            full_thinking_beta = "dev-full-thinking-2025-05-14"
            if (
                full_thinking_beta in betas
                or full_thinking_beta in self._client_default_betas()
            ):
                thinking.pop("display", None)
            params["thinking"] = thinking

            headers["anthropic-version"] = "2023-06-01"
            if max_tokens > 8192:
                betas.append("output-128k-2025-02-19")

        elif config.reasoning_effort == "none" and self._supports_disabling_thinking():
            # Claude 4.7+ (incl. Sonnet 5) run adaptive thinking by default, so
            # `reasoning_effort="none"` must explicitly disable it. Pre-4.7 models
            # default to no thinking, so omitting the field already suffices.
            params["thinking"] = {"type": "disabled"}

        # config that applies to all models
        if config.stop_seqs is not None:
            params["stop_sequences"] = config.stop_seqs

        # structured output
        if config.response_schema is not None:
            schema = config.response_schema.json_schema.model_copy(deep=True)
            set_additional_properties_false(schema)
            betas.append("structured-outputs-2025-11-13")
            extra_body["output_format"] = {
                "type": "json_schema",
                "schema": json_schema_dump(schema, exclude=JSON_SCHEMA_EXTENDED_FIELDS),
            }

        # server-side refusal fallback (first-party Claude API only). routed
        # via extra_body as the SDK only exposes `fallbacks` on
        # client.beta.messages.create but inspect calls client.messages.create
        if config.fallback_models:
            if self.is_bedrock() or self.is_vertex() or self.is_azure():
                warn_once(
                    logger,
                    "fallback_models is only supported on the first-party "
                    "Anthropic API (not bedrock/vertex/azure) and will be ignored.",
                )
            elif normalized_batch_config(config.batch):
                warn_once(
                    logger,
                    "fallback_models is not supported with the Anthropic "
                    "Batches API and will be ignored.",
                )
            else:
                betas.append(FALLBACK_BETA)
                extra_body["fallbacks"] = [
                    {"model": model} for model in config.fallback_models
                ]

        # look for any of our native fields not in GenerateConfig in extra_body
        if config.extra_body is not None:
            for field in anthropic_extra_body_fields():
                if field in config.extra_body and field not in params:
                    params[field] = config.extra_body[field]
            # pass through context_management for compaction
            if CONTEXT_MANAGEMENT in config.extra_body:
                extra_body[CONTEXT_MANAGEMENT] = config.extra_body[CONTEXT_MANAGEMENT]

        # return config
        return params, extra_body, headers, betas

    @override
    def max_tokens(self) -> int | None:
        # Anthropic requires you to explicitly specify max_tokens (most others
        # set it to the maximum allowable output tokens for the model).
        # Claude 4 models currently have maxes of 32k (Opus 4 and 4.1) or
        # 64k (Sonnet 4 and 4.5 and Haiku 4.5). Claude 3.0 maxes at 4k and
        # Claude 3.5 at 8k (3.7 Sonnet can go all the way to 128k since we
        # automatically include the header that enables that features).
        # Therefore, we use 4k as the default for Claude 3 and 3.5 and
        # 32,000 as the default for everything else.
        if self.is_claude_3() or self.is_claude_3_5():
            return 4096
        else:
            return 32000

    @override
    def max_tokens_for_config(self, config: GenerateConfig) -> int | None:
        max_tokens = cast(int, self.max_tokens())
        if self.is_thinking_model():
            reasoning_effort = self.effort_from_reasoning_effort(config)
            if reasoning_effort is not None:
                # xhigh/max sized to reach the migration-guide floor of 64k
                # on top of the 32k base for thinking models.
                effort_tokens = {
                    "low": 4096,
                    "medium": 10000,
                    "high": 16000,
                    "xhigh": 32000,
                    "max": 32000,
                }
                max_tokens = max_tokens + effort_tokens.get(reasoning_effort, 16000)
            else:
                # pre-4.6 path: size for explicit reasoning_tokens, or for
                # the bridged effort->tokens translation when only effort is set.
                bridged = self.bridged_reasoning_tokens(config)
                if bridged is not None:
                    max_tokens = max_tokens + bridged

        # migration-guide floor: xhigh/max effort wants ≥64k max_tokens
        # (model caps below will still clamp on older models)
        if config.effort in ("xhigh", "max") and max_tokens < 64000:
            max_tokens = 64000

        # apply caps after bumping for reasoning
        if self.is_claude_frontier() and self.is_claude_4_opus():
            # Opus 4.6+ (and future 4.x minor opus versions)
            max_tokens = min(max_tokens, 128000)
        elif self.is_claude_5() or (self.is_claude_latest() and not self.is_claude_4()):
            # Claude 5+ and future major versions: assume opus-class limits
            max_tokens = min(max_tokens, 128000)
        elif self.is_claude_4_5() or self.is_claude_frontier():
            # All other 4.5 / 4.6+ non-opus models (incl. future 4.x minor versions)
            max_tokens = min(max_tokens, 64000)
        elif self.is_claude_4_opus():
            max_tokens = min(max_tokens, 32000)
        elif self.is_claude_3_7():
            max_tokens = min(max_tokens, 128000)
        else:
            max_tokens = min(max_tokens, 64000)

        return max_tokens

    def is_using_thinking(self, config: GenerateConfig) -> bool:
        return self.is_thinking_model() and (
            (self.bridged_reasoning_tokens(config) is not None)
            or (self.effort_from_reasoning_effort(config) is not None)
        )

    def _supports_disabling_thinking(self) -> bool:
        """Whether `reasoning_effort="none"` should send `thinking:{type:"disabled"}`.

        Claude 4.7+ (Opus 4.7/4.8, Sonnet 5) run adaptive thinking by default and
        accept `disabled` to turn it off. Fable/Mythos 5 also always think but
        reject `disabled` (400), so they're excluded — their thinking can't be
        turned off. Pre-4.7 models default to no thinking, so `"none"` is honored
        by simply omitting the `thinking` field.
        """
        return self.is_claude_4_7_or_later() and not (
            self.is_claude_5() and not self.is_claude_sonnet_5()
        )

    def bridged_reasoning_tokens(self, config: GenerateConfig) -> int | None:
        """Effective `budget_tokens` for pre-4.6 Claude (uses extended thinking).

        Explicit `reasoning_tokens` wins; otherwise `reasoning_effort` is
        translated via the shared fixed-table bridge. Frontier Claude uses
        adaptive thinking with `effort` and ignores this path (returns None).

        Note: `reasoning_tokens` on Claude 4.7+ (incl. Claude 5) is rejected up
        front in `completion_config` (those models removed `budget_tokens`), so
        this method is never reached with `reasoning_tokens` set on them.
        """
        if config.reasoning_tokens is not None:
            return config.reasoning_tokens
        if (
            not self.is_claude_frontier()
            and config.reasoning_effort is not None
            and config.reasoning_effort != "none"
        ):
            return effort_to_reasoning_tokens(config.reasoning_effort)
        return None

    # see https://github.com/anthropics/anthropic-sdk-python?tab=readme-ov-file#long-requests
    def auto_streaming(self, config: GenerateConfig) -> bool:
        return self.is_using_thinking(config) or (
            config.max_tokens is not None and config.max_tokens >= 8192
        )

    def is_thinking_model(self) -> bool:
        return not self.is_claude_3() and not self.is_claude_3_5()

    def is_claude_3(self) -> bool:
        return re.search(r"claude-3-[a-zA-Z]", self.model_family()) is not None

    def is_claude_3_5(self) -> bool:
        return "claude-3-5-" in self.model_family()

    def is_claude_3_7(self) -> bool:
        return "claude-3-7-" in self.model_family()

    def is_claude_4(self) -> bool:
        return re.search(r"claude-[a-zA-Z]+-4", self.model_family()) is not None

    def is_claude_4_0(self) -> bool:
        return self._is_claude_4_x(0) or (
            re.search(r"claude-[a-zA-Z]+-4[-@]20\d{6}", self.model_family()) is not None
        )

    def is_claude_4_1(self) -> bool:
        return self._is_claude_4_x(1)

    def is_claude_4_5(self) -> bool:
        return self._is_claude_4_x(5)

    def is_claude_4_6(self) -> bool:
        return self._is_claude_4_x(6)

    def is_claude_4_7(self) -> bool:
        return self._is_claude_4_x(7)

    def is_claude_4_8(self) -> bool:
        return self._is_claude_4_x(8)

    def is_claude_5(self) -> bool:
        return _is_claude_5(self.model_family())

    def is_claude_4_opus(self) -> bool:
        return self.is_claude_4() and "opus" in self.model_family()

    def is_claude_sonnet_5(self) -> bool:
        return self.is_claude_5() and "sonnet" in self.model_family()

    def _is_claude_4_x(self, x: int) -> bool:
        return (
            re.search(r"claude-[a-zA-Z]+-4-" + str(x), self.model_family()) is not None
        )

    # attempt to not require an inspect package update for new models
    # (assume that all capabilities of claude 4.6 are available in
    # future model versions)
    def is_claude_latest(self) -> bool:
        # future minor version
        if self.is_claude_4() and not (
            self.is_claude_4_0()
            or self.is_claude_4_1()
            or self.is_claude_4_5()
            or self.is_claude_4_6()
            or self.is_claude_4_7()
            or self.is_claude_4_8()
        ):
            return True
        # future major version (newer than Claude 5, which is a known version)
        elif (
            not self.is_claude_3()
            and not self.is_claude_3_5()
            and not self.is_claude_3_7()
            and not self.is_claude_4()
            and not self.is_claude_5()
        ):
            return True
        else:
            return False

    # many feature are 4.6+ which we call "frontier"
    def is_claude_frontier(self) -> bool:
        return (
            self.is_claude_4_6()
            or self.is_claude_4_7()
            or self.is_claude_4_8()
            or self.is_claude_5()
            or self.is_claude_latest()
        )

    # some features (e.g. xhigh effort) require 4.7 or any future minor version
    def is_claude_4_7_or_later(self) -> bool:
        return (
            self.is_claude_4_7()
            or self.is_claude_4_8()
            or self.is_claude_5()
            or self.is_claude_latest()
        )

    def is_claude_4_8_or_later(self) -> bool:
        return self.is_claude_4_8() or self.is_claude_5() or self.is_claude_latest()

    # https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages
    # Claude API and Claude Platform on AWS only; not Bedrock, Vertex, or Foundry.
    def supports_mid_conversation_system(self) -> bool:
        if self.is_bedrock() or self.is_vertex():
            return False
        # claude-mythos-preview falls through is_claude_latest() → True, but
        # the endpoint rejects role:"system" in messages with
        # "role 'system' is not supported on this model" (verified 2026-06-10
        # vs. claude-opus-4-8 which accepts it). Route via <system-reminder>.
        if "mythos-preview" in self.service_model_name():
            return False
        return self.is_claude_4_8_or_later()

    # https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics
    # Claude API only; not Bedrock or Vertex. Enabled when the caller opts
    # in via the cache-diagnosis-2026-04-07 beta header through any of the
    # three caller-controlled paths the provider honors: provider constructor
    # (self.betas), per-request (config.extra_headers), or SDK client default
    # header (set on the underlying AsyncAnthropic). Mirrors the merge done
    # in completion_config + generate so we stay consistent with the headers
    # actually sent to /v1/messages.
    def cache_diagnostics_enabled(self, config: GenerateConfig) -> bool:
        if self.is_bedrock() or self.is_vertex():
            return False
        if _CACHE_DIAGNOSIS_BETA in self.betas:
            return True
        if _CACHE_DIAGNOSIS_BETA in self._client_default_betas():
            return True
        for key, val in (config.extra_headers or {}).items():
            if key.lower() in ("anthropic_beta", "anthropic-beta") and val:
                if _CACHE_DIAGNOSIS_BETA in [b.strip() for b in val.split(",")]:
                    return True
        return False

    @override
    def connection_key(self) -> str:
        """Scope adaptive concurrency per (key, model).

        A pool shared across models lets the faster model's signals push the
        adaptive limit past the slower model's actual ceiling (cram-down).
        Per-model scoping avoids that, at the cost of slight over-fragmentation
        when models actually share an upstream rate-limit budget.
        """
        return f"{self.initial_api_key}:{self.service_model_name()}"

    def service_model_name(self) -> str:
        """Model name without any service prefix."""
        return self.model_name.replace(f"{self.service}/", "", 1)

    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup."""
        return f"anthropic/{self.service_model_name()}"

    def input_tokens_name(self) -> str:
        """Model name used for looking up model input tokens."""
        from inspect_ai.model._model_info import _get_model_info_direct

        if "context-1m-2025-08-07" in self.betas:
            return "anthropic/claude-opus-4-6"  # 1MM
        elif self.is_claude_latest():
            # Unknown future version: assume the current 1M frontier.
            return "anthropic/claude-opus-4-8"  # 1MM
        elif (
            self.is_claude_5() and _get_model_info_direct(self.canonical_name()) is None
        ):
            # A Claude 5 variant not yet registered in the model-info database
            # (e.g. a tier-named claude-*-5 or a new codename): assume the 1M
            # Claude 5 frontier rather than missing the lookup. Registered
            # Claude 5 models (Fable/Mythos and their point releases, which
            # fuzzy-match their base entry) fall through to the database below.
            return "anthropic/claude-opus-4-8"  # 1MM
        else:
            return super().input_tokens_name()

    @override
    def should_retry(self, ex: BaseException) -> bool | RetryDecision:
        if isinstance(ex, APIStatusError):
            retry_after = parse_retry_after_from_exception(ex)
            # when streaming, anthropic does not set status_code == 529
            # for overloaded or internal server errors so we check for them explicitly
            if isinstance(ex.body, dict):
                body_str = str(ex.body).lower()
                if "overloaded" in body_str or "internal server error" in body_str:
                    return RetryDecision.transient(retry_after=retry_after)
                # TCP interruptions can truncate large request bodies in transit,
                # causing a 400 even though json.dumps() produced valid JSON.
                if (
                    ex.status_code == 400
                    and "not valid json" in body_str
                    and "unexpected end of data" in body_str
                ):
                    return RetryDecision.transient(retry_after=retry_after)

            # standard http status code checking
            if not is_retryable_http_status(ex.status_code):
                return RetryDecision.no()
            if ex.status_code == 429:
                return RetryDecision.rate_limit(retry_after=retry_after)
            return RetryDecision.transient(retry_after=retry_after)

        decision = httpx_classify_retry(ex)
        if decision is not None:
            return decision
        if isinstance(ex, APIConnectionError | APITimeoutError):
            return RetryDecision.transient()
        return RetryDecision.no()

    @override
    def is_auth_failure(self, ex: Exception) -> bool:
        if isinstance(ex, APIStatusError):
            return ex.status_code == 401
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
    def tool_result_documents(self) -> bool:
        return True

    @override
    def force_reasoning_history(self) -> Literal["none", "all", "last"] | None:
        return "all"

    # convert some common APIStatusError states into 'refusal' model output
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
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
        bool,
    ]:
        # Convert orphaned tool results to text messages before processing
        # (handles case where native compaction summarized away tool_use blocks)
        input = _convert_orphaned_tool_results(input)

        # extract system messages — for Claude 4.8+ (Claude API / Claude
        # Platform on AWS), inline system messages are sent as `role="system"`
        # turns; only the leading contiguous block becomes the top-level
        # `system` param. For other models, only the leading block is hoisted
        # and mid-conversation system messages become `<system-reminder>` user
        # turns (preserving the prompt cache).
        messages: list[ChatMessage]
        if self.supports_mid_conversation_system():
            system_messages, messages = _split_for_mid_conversation_system(input)
        else:
            system_messages, messages = _split_system_as_reminders(input)

        # messages
        message_params = [(await message_param(message)) for message in messages]

        # collapse user messages (as Inspect 'tool' messages become Claude 'user' messages)
        message_params = functools.reduce(
            consecutive_user_message_reducer, message_params, []
        )

        # cleave out MCP servers from tools
        tools, mcp_servers = self.partition_tools(tools)

        # tools
        tools_params = [
            param
            for tool in tools
            for param in self.tool_params_for_tool_info(tool, config)
        ]

        # mcp servers
        mcp_server_params = [
            self.mcp_server_param(mcp_server) for mcp_server in mcp_servers
        ]

        # system messages
        system_param: list[TextBlockParam] | None = None
        if len(system_messages) > 0:
            system_param = [
                TextBlockParam(type="text", text=m.text)
                for m in system_messages
                if m.text
            ]
            if len(system_param) == 0:
                system_param = None
        else:
            system_param = None

        # add caching directives if necessary
        cache_prompt = (
            config.cache_prompt if isinstance(config.cache_prompt, bool) else True
        )

        # only certain claude models qualify
        if cache_prompt:
            model_name = self.model_family()
            if (
                "claude-3-sonnet" in model_name
                or "claude-2" in model_name
                or "claude-instant" in model_name
            ):
                cache_prompt = False

        if cache_prompt:
            # system
            if system_param:
                add_cache_control(system_param[-1], self.cache_ttl)
            # tools
            if tools_params:
                add_cache_control(tools_params[-1], self.cache_ttl)
            # mark the second-to-last cacheable block. auto-cache marks the
            # last; this write gives lookback a fallback when that block
            # changes (RAG, scorers, approvers, branching evals). harmless
            # extra write for append-only growth where auto-cache alone
            # suffices. Skip thinking/redacted_thinking blocks — the API
            # rejects cache_control on those.
            if message_params:
                add_lookback_cache_control(message_params, self.cache_ttl)

        # return chat input
        return (
            system_param,
            tools_params,
            mcp_server_params,
            message_params,
            cache_prompt,
        )

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

    def tool_params_for_tool_info(
        self, tool: ToolInfo, config: GenerateConfig
    ) -> Sequence["ToolParamDef"]:
        # Use a native tool implementation when available. Otherwise, use the
        # standard tool implementation
        return self.maybe_native_tool_params(tool, config) or [
            ToolParam(
                name=tool.name,
                description=tool.description,
                input_schema=json_schema_dump(tool.parameters),
            )
        ]

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

    def maybe_native_tool_params(
        self, tool: ToolInfo, config: GenerateConfig
    ) -> Sequence["ToolParamDef"] | None:
        if config.internal_tools is not False:
            web_search_params = self.web_search_tool_params(tool)
            if web_search_params is not None:
                return web_search_params
            else:
                param = (
                    self.computer_use_tool_param(tool)
                    or self.text_editor_tool_param(tool)
                    or self.memory_tool_param(tool)
                    or self.code_execution_tool_param(tool)
                )
                if param is not None:
                    return [param]
                else:
                    return None
        else:
            return None

    def computer_use_tool_param(
        self, tool: ToolInfo
    ) -> BetaToolComputerUse20250124Param | BetaToolComputerUse20251124Param | None:
        # check for compatible 'computer' tool
        if is_computer_tool_info(tool):
            if self.is_claude_3_5():
                warn_once(
                    logger,
                    "Use of Anthropic's native computer use support is not enabled in Claude 3.5. Please use 3.7 or later to leverage the native support.",
                )
                return None
            # Among Claude 5 models only Sonnet 5 is documented to support native
            # computer use (the computer-use-2025-11-24 tool). Fable/Mythos 5 are
            # not listed in Anthropic's computer-use docs, so error for those
            # rather than degrade to a non-native fallback tool.
            if self.is_claude_5() and not self.is_claude_sonnet_5():
                raise PrerequisiteError(
                    f"Computer use is not supported by the model '{self.service_model_name()}'. "
                    "Anthropic's native computer use requires a Claude 4.x model or "
                    "Claude Sonnet 5 (e.g. claude-opus-4-8, claude-sonnet-4-6, or "
                    "claude-sonnet-5)."
                )
            # Note: The dimensions passed here for display_width_px and display_height_px
            # should match the dimensions of screenshots returned by the tool. Those
            # dimensions will always be one of the values in MAX_SCALING_TARGETS
            # in _x11_client.py. This default container is currently configured with
            # a native display resolution of 1920x1080 and 1366x768 (FWXGA) as the
            # screenshot/API resolution since this most closely matches that native
            # 16:9 aspect ratio.
            #
            # TODO: enhance this code to calculate the dimensions based on the scaled screen
            # size used by the container.
            # computer_20251124 is supported by Claude Sonnet 5, Opus 4.6/4.7/4.8,
            # Sonnet 4.6, and Opus 4.5
            if self.is_claude_frontier() or (
                self.is_claude_4_5() and self.is_claude_4_opus()
            ):
                return BetaToolComputerUse20251124Param(
                    type="computer_20251124",
                    name="computer",
                    display_width_px=1366,
                    display_height_px=768,
                    display_number=1,
                    enable_zoom=True,
                )
            else:
                return BetaToolComputerUse20250124Param(
                    type="computer_20250124",
                    name="computer",
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
        | BetaToolTextEditor20250728Param
        | None
    ):
        # See: https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/text-editor-tool#before-using-the-text-editor-tool
        # TODO: It would be great to enhance our `is_claude_xxx` functions to help here.
        if self.model_family().startswith(("claude-3-5-haiku", "claude-3-opus")):
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
                BetaToolTextEditor20250728Param(
                    type="text_editor_20250728", name="str_replace_based_edit_tool"
                )
                if self.is_claude_4() or self.is_claude_5() or self.is_claude_latest()
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

    def web_search_tool_params(
        self, tool: ToolInfo
    ) -> (
        list[
            WebSearchTool20250305Param
            | BetaWebFetchTool20250910Param
            | WebSearchTool20260209Param
            | BetaWebFetchTool20260209Param
        ]
        | None
    ):
        if (
            tool.name == "web_search"
            and tool.options
            and "anthropic" in tool.options
            and (_supports_web_search(self.model_family()) or self.is_claude_frontier())
        ):
            # do we support dynamic filtering? (claude 4.6 and later; not
            # available on vertex or bedrock)
            # https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool#dynamic-filtering
            web_search_filtering = self.is_claude_frontier() and not (
                self.is_vertex() or self.is_bedrock()
            )
            return _web_search_tool_params(
                tool.options["anthropic"], web_search_filtering
            )
        else:
            return None

    def code_execution_tool_param(
        self, tool: ToolInfo
    ) -> BetaCodeExecutionTool20250825Param | None:
        if (
            tool.name == "code_execution"
            and _supports_code_interpreter(self.model_family())
            and tool.options
            and "anthropic" in tool.options.get("providers", {})
        ):
            return BetaCodeExecutionTool20250825Param(
                name="code_execution", type="code_execution_20250825"
            )
        else:
            return None

    def memory_tool_param(self, tool: ToolInfo) -> BetaMemoryTool20250818Param | None:
        # check for compatible 'memory' tool
        if tool.name == "memory" and (
            sorted(tool.parameters.properties.keys())
            == sorted(
                [
                    "command",
                    "file_text",
                    "insert_line",
                    "insert_text",
                    "new_path",
                    "new_str",
                    "old_path",
                    "old_str",
                    "path",
                    "view_range",
                ]
            )
        ):
            # memory tool supported on Claude 4+ models
            if _supports_memory(self.model_family()):
                return BetaMemoryTool20250818Param(
                    type="memory_20250818",
                    name="memory",
                )
            else:
                return None
        else:
            return None

    def effort_from_reasoning_effort(
        self, config: GenerateConfig
    ) -> Literal["max", "high", "medium", "low", "xhigh"] | None:
        # claude 4.6 supports reasoning effort via type: "adaptive"
        if (
            config.reasoning_effort is not None
            and config.reasoning_effort != "none"
            and (self.is_claude_frontier())
        ):
            match config.reasoning_effort:
                case "low" | "minimal":
                    return "low"
                case "medium":
                    return "medium"
                case "high":
                    return "high"
                case "xhigh":
                    return "xhigh" if self.is_claude_4_7_or_later() else "high"
                case "max":
                    return "max"

        else:
            return None


def _messages_contain_thinking(messages: list[MessageParam]) -> bool:
    """Check if any message contains thinking or redacted_thinking blocks."""
    for msg in messages:
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type in ("thinking", "redacted_thinking"):
                        return True
    return False


def _messages_contain_compaction(messages: list[ChatMessage]) -> bool:
    """Check if any message contains compaction blocks."""
    for msg in messages:
        if isinstance(msg.content, list):
            for content in msg.content:
                if _is_compaction_content(content):
                    return True
    return False


def _is_claude_5(model_name: str) -> bool:
    """Check if a model name is a Claude 5 model.

    Claude 5 model names carry no tier word (e.g. claude-fable-5,
    claude-mythos-5); match any claude-<name>-5. This deliberately also matches
    point-release, tier-named, and new-codename variants (claude-fable-5-1,
    claude-opus-5, claude-saga-5) so they are treated as known Claude 5 models
    without requiring a package update. Existing names with a digit before the
    trailing -5 (claude-haiku-4-5, claude-3-5-*) do not match.
    """
    return re.search(r"claude-[a-zA-Z]+-5", model_name) is not None


def _supports_web_search(model_name: str) -> bool:
    """Check if the model supports Anthropic's native web search tool."""
    # https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool#supported-models
    # https://docs.anthropic.com/en/docs/about-claude/models/overview#model-aliases
    # https://docs.anthropic.com/en/docs/about-claude/model-deprecations
    return model_name.startswith(
        ("claude-opus-4", "claude-sonnet-4", "claude-haiku-4", "claude-3-7-sonnet")
    ) or model_name in ("claude-3-5-sonnet-latest", "claude-3-5-haiku-latest")


def _supports_code_interpreter(model_name: str) -> bool:
    return model_name.startswith(
        (
            "claude-opus-4",
            "claude-sonnet-4",
            "claude-sonnet-5",
            "claude-haiku-4",
            "claude-3-7-sonnet",
            "claude-3-5-haiku-latest",
        )
    )


def _supports_memory(model_name: str) -> bool:
    """Check if the model supports Anthropic's native memory tool."""
    # https://docs.claude.com/en/docs/agents-and-tools/tool-use/memory-tool
    return model_name.startswith(
        ("claude-sonnet-4", "claude-opus-4", "claude-haiku-4")
    ) or _is_claude_5(model_name)


def _web_search_tool_params(
    maybe_anthropic_options: object,
    web_search_filtering: bool = False,
) -> list[
    WebSearchTool20250305Param
    | BetaWebFetchTool20250910Param
    | WebSearchTool20260209Param
    | BetaWebFetchTool20260209Param
]:
    if maybe_anthropic_options is not None and not isinstance(
        maybe_anthropic_options, dict
    ):
        raise TypeError(
            f"Expected a dictionary for anthropic_options, got {type(maybe_anthropic_options)}"
        )

    # use the dynamic filtering tool versions when supported (these run web
    # search/fetch inside the code execution sandbox so the model can filter
    # results programmatically before they enter the context window)
    web_fetch_tool: BetaWebFetchTool20250910Param | BetaWebFetchTool20260209Param
    web_search_tool: WebSearchTool20250305Param | WebSearchTool20260209Param
    if web_search_filtering:
        web_fetch_tool = BetaWebFetchTool20260209Param(
            name="web_fetch", type="web_fetch_20260209"
        )
        web_search_tool = WebSearchTool20260209Param(
            name="web_search",
            type="web_search_20260209",
        )
    else:
        web_fetch_tool = BetaWebFetchTool20250910Param(
            name="web_fetch", type="web_fetch_20250910"
        )
        web_search_tool = WebSearchTool20250305Param(
            name="web_search",
            type="web_search_20250305",
        )

    if maybe_anthropic_options:
        if "allowed_domains" in maybe_anthropic_options:
            web_search_tool["allowed_domains"] = maybe_anthropic_options[
                "allowed_domains"
            ]
            web_fetch_tool["allowed_domains"] = web_search_tool["allowed_domains"]
        if "blocked_domains" in maybe_anthropic_options:
            web_search_tool["blocked_domains"] = maybe_anthropic_options[
                "blocked_domains"
            ]
            web_fetch_tool["blocked_domains"] = web_search_tool["blocked_domains"]
        if "cache_control" in maybe_anthropic_options:
            web_search_tool["cache_control"] = maybe_anthropic_options["cache_control"]
        if "max_uses" in maybe_anthropic_options:
            web_search_tool["max_uses"] = maybe_anthropic_options["max_uses"]
            web_fetch_tool["max_uses"] = web_search_tool["max_uses"]
        if "user_location" in maybe_anthropic_options:
            web_search_tool["user_location"] = maybe_anthropic_options["user_location"]

        if "citations" in maybe_anthropic_options:
            web_fetch_tool["citations"] = maybe_anthropic_options["citations"]

        if "max_content_tokens" in maybe_anthropic_options:
            web_fetch_tool["max_content_tokens"] = maybe_anthropic_options[
                "max_content_tokens"
            ]

    return [web_fetch_tool, web_search_tool]


# tools can be either a stock tool param or a special Anthropic native use tool param
ToolParamDef = (
    ToolParam
    | BetaToolComputerUse20250124Param
    | BetaToolComputerUse20251124Param
    | ToolTextEditor20250124Param
    | BetaToolTextEditor20241022Param
    | BetaToolTextEditor20250429Param
    | BetaToolTextEditor20250728Param
    | WebSearchTool20250305Param
    | WebSearchTool20260209Param
    | BetaMemoryTool20250818Param
    | BetaCodeExecutionTool20250825Param
    | BetaWebFetchTool20250910Param
    | BetaWebFetchTool20260209Param
)


def is_tool_param(param: ToolParamDef) -> TypeGuard[ToolParam]:
    return "input_schema" in param


def is_text_editor_tool(
    param: ToolParamDef,
) -> TypeGuard[
    ToolTextEditor20250124Param
    | BetaToolTextEditor20241022Param
    | BetaToolTextEditor20250429Param
    | BetaToolTextEditor20250728Param
]:
    type = param.get("type", None)
    if type is not None:
        return type.startswith("text_editor") and not is_tool_param(param)
    else:
        return False


def is_computer_tool(
    param: ToolParamDef,
) -> TypeGuard[BetaToolComputerUse20250124Param | BetaToolComputerUse20251124Param]:
    return param.get("name") == "computer" and not is_tool_param(param)


def is_web_search_tool(
    param: ToolParamDef,
) -> TypeGuard[WebSearchTool20250305Param | WebSearchTool20260209Param]:
    return param.get("name") == "web_search" and not is_tool_param(param)


def is_web_fetch_tool(
    param: ToolParamDef,
) -> TypeGuard[BetaWebFetchTool20250910Param | BetaWebFetchTool20260209Param]:
    return param.get("name") == "web_fetch" and not is_tool_param(param)


def is_memory_tool(param: ToolParamDef) -> TypeGuard[BetaMemoryTool20250818Param]:
    return param.get("name") == "memory" and not is_tool_param(param)


def is_bash_tool(
    param: ToolParamDef,
) -> TypeGuard[BetaToolBash20250124Param]:
    return param.get("name") == "bash" and not is_tool_param(param)


def is_code_execution_tool(
    param: ToolParamDef,
) -> TypeGuard[BetaCodeExecutionTool20250825Param]:
    return param.get("name") == "code_execution" and not is_tool_param(param)


_NON_CACHEABLE_BLOCK_TYPES = frozenset({"thinking", "redacted_thinking"})


def add_lookback_cache_control(
    message_params: list[MessageParam], ttl: Literal["5m", "1h"] | None = None
) -> None:
    """Tag the second-to-last cacheable content block across `message_params`.

    Walks blocks in reverse (last message first), skipping
    thinking/redacted_thinking (the API rejects `cache_control` on those with
    `Extra inputs are not permitted`), and tags the second cacheable block
    found. Tagging the *second*-to-last rather than the last gives lookback
    caching a fallback when the final block changes (RAG, scorers, approvers,
    branching) — auto-cache already covers the very last block.

    Bare-string content counts as one cacheable block for position purposes
    (it is the "last block" that auto-cache covers) but cannot itself carry
    a `cache_control` field, so it is counted but never tagged.
    """
    seen_cacheable = 0
    for msg in reversed(message_params):
        content = msg["content"]
        if isinstance(content, str):
            seen_cacheable += 1
            if seen_cacheable >= 2:
                return
        elif isinstance(content, list):
            for block in reversed(content):
                if (
                    isinstance(block, dict)
                    and block.get("type") in _NON_CACHEABLE_BLOCK_TYPES
                ):
                    continue
                seen_cacheable += 1
                if seen_cacheable == 2:
                    add_cache_control(cast(dict[str, Any], block), ttl)
                    return


def add_cache_control(
    param: TextBlockParam
    | ToolParam
    | BetaToolComputerUse20250124Param
    | BetaToolComputerUse20251124Param
    | ToolTextEditor20250124Param
    | BetaToolTextEditor20241022Param
    | BetaToolTextEditor20250429Param
    | BetaToolTextEditor20250728Param
    | WebSearchTool20250305Param
    | WebSearchTool20260209Param
    | BetaMemoryTool20250818Param
    | BetaCodeExecutionTool20250825Param
    | BetaWebFetchTool20250910Param
    | BetaWebFetchTool20260209Param
    | dict[str, Any],
    ttl: Literal["5m", "1h"] | None = None,
) -> None:
    cast(dict[str, Any], param)["cache_control"] = cache_control_param(ttl)


def cache_control_param(ttl: Literal["5m", "1h"] | None) -> CacheControlEphemeralParam:
    cache_control = CacheControlEphemeralParam(type="ephemeral")
    if ttl is not None:
        cache_control["ttl"] = ttl
    return cache_control


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
    tool_choice: ToolChoice, config: GenerateConfig
) -> ToolChoiceParam:
    # carve out "none" (it doesn't support disable_parallel_tool_use)
    if tool_choice == "none":
        return ToolChoiceNoneParam(type="none")

    # determine tool_choice_param
    if isinstance(tool_choice, ToolFunction):
        tool_choice_param: (
            ToolChoiceToolParam | ToolChoiceAnyParam | ToolChoiceAutoParam
        ) = ToolChoiceToolParam(
            type="tool",
            name=tool_choice.name,
        )
    elif tool_choice == "any":
        tool_choice_param = ToolChoiceAnyParam(type="any")
    else:
        tool_choice_param = ToolChoiceAutoParam(type="auto")

    # set parallel_tool_calls if specified
    if config.parallel_tool_calls is not None:
        tool_choice_param["disable_parallel_tool_use"] = not config.parallel_tool_calls

    # return
    return tool_choice_param


def _tool_result_to_text(msg: ChatMessageTool) -> str:
    """Convert a tool result message to plain text."""
    function_name = msg.function or "unknown"

    # Extract text content
    if isinstance(msg.content, str):
        content = msg.content
    else:
        # Join text content from list
        content = "\n".join(c.text for c in msg.content if isinstance(c, ContentText))

    # Include error if present
    if msg.error:
        return (
            f"[Tool result for {function_name} (error: {msg.error.message})]\n{content}"
        )
    else:
        return f"[Tool result for {function_name}]\n{content}"


def _convert_orphaned_tool_results(
    messages: list[ChatMessage],
) -> list[ChatMessage]:
    """Convert orphaned tool results to regular user text messages.

    When native compaction summarizes away tool_use blocks, subsequent tool_results
    become "orphaned" (their tool_use_id has no match). This function detects such
    orphans and converts them to regular user text messages so the API doesn't
    reject them.

    Args:
        messages: List of messages to process.

    Returns:
        New list with orphaned tool results converted to user text messages.
    """
    # Collect all tool_use IDs from assistant messages
    tool_use_ids: set[str] = set()
    for msg in messages:
        if isinstance(msg, ChatMessageAssistant) and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_use_ids.add(tc.id)

    # Process messages, converting orphaned tool results to text
    result: list[ChatMessage] = []
    for msg in messages:
        if isinstance(msg, ChatMessageTool) and msg.tool_call_id:
            if msg.tool_call_id not in tool_use_ids:
                # Orphaned tool result - convert to user text message
                text_content = _tool_result_to_text(msg)
                result.append(ChatMessageUser(content=text_content))
            else:
                result.append(msg)
        else:
            result.append(msg)

    return result


def _split_system_as_reminders(
    input: list[ChatMessage],
) -> tuple[list[ChatMessageSystem], list[ChatMessage]]:
    """Split system messages for models without mid-conversation support.

    Pulls the leading contiguous block of system messages into the top-level
    `system` field (preserving the cacheable prefix). Any remaining
    mid-conversation system messages are converted to user turns wrapped in
    `<system-reminder>` tags rather than hoisted to the top-level field, which
    would bust the prompt cache on every new injection. The tag matches the
    convention Claude Code uses for pre-4.8 models, so models post-trained on
    those transcripts recognize it as an instruction signal.

    Exception: a system message adjacent to a tool result is hoisted instead.
    Tool results map to user-role wire messages, and the consecutive-user
    reducer merges adjacent user turns, so a reminder placed next to a tool
    result would fold into the tool-result turn. Non-tool-result content in a
    tool-result turn restarts the assistant loop and strips prior thinking /
    cache context on tool-use continuations, so those reminders are hoisted.
    """
    top: list[ChatMessageSystem] = []
    i = 0
    while i < len(input) and isinstance(input[i], ChatMessageSystem):
        top.append(cast(ChatMessageSystem, input[i]))
        i += 1

    rest = input[i:]
    result: list[ChatMessage] = []
    hoisted = 0
    for idx, m in enumerate(rest):
        if not isinstance(m, ChatMessageSystem):
            result.append(m)
            continue

        # neighbors that determine the user-role run this reminder would join:
        # the last already-emitted message, and the next non-system message
        # (consecutive systems are evaluated independently).
        prev_msg = result[-1] if result else None
        next_msg = next(
            (
                later
                for later in rest[idx + 1 :]
                if not isinstance(later, ChatMessageSystem)
            ),
            None,
        )
        if isinstance(prev_msg, ChatMessageTool) or isinstance(
            next_msg, ChatMessageTool
        ):
            top.append(m)
            hoisted += 1
        else:
            result.append(
                ChatMessageUser(
                    content=f"<system-reminder>\n{m.text}\n</system-reminder>"
                )
            )

    if hoisted:
        warn_once(logger, _REMINDER_SYSTEM_HOISTED_WARNING.format(count=hoisted))

    return top, result


def _split_for_mid_conversation_system(
    input: list[ChatMessage],
) -> tuple[list[ChatMessageSystem], list[ChatMessage]]:
    """Split system messages for Claude 4.8+ mid-conversation support.

    Pulls the leading contiguous block of system messages into the top-level
    `system` field. Remaining system messages stay inline (will be serialized
    as `role="system"` turns). Enforces the API's placement invariants by
    merging consecutive mid-conversation systems and hoisting any in invalid
    positions back to the top-level field.
    """
    # 1. Pull leading contiguous block.
    top: list[ChatMessageSystem] = []
    i = 0
    while i < len(input) and isinstance(input[i], ChatMessageSystem):
        top.append(cast(ChatMessageSystem, input[i]))
        i += 1

    # 2. Pre-merge consecutive system messages in the remainder so the
    #    placement check below sees the effective neighbors.
    merged: list[ChatMessage] = []
    for m in input[i:]:
        if (
            isinstance(m, ChatMessageSystem)
            and merged
            and isinstance(merged[-1], ChatMessageSystem)
        ):
            prev_sys = cast(ChatMessageSystem, merged.pop())
            merged.append(ChatMessageSystem(content=f"{prev_sys.text}\n\n{m.text}"))
        else:
            merged.append(m)

    # 3. Walk and classify each system message; hoist invalid ones.
    result: list[ChatMessage] = []
    hoisted = 0
    for j, m in enumerate(merged):
        if not isinstance(m, ChatMessageSystem):
            result.append(m)
            continue
        prev_msg = result[-1] if result else None
        next_msg = merged[j + 1] if j + 1 < len(merged) else None
        if _valid_mid_conv_position(prev_msg, next_msg):
            result.append(m)
        else:
            top.append(m)
            hoisted += 1

    if hoisted:
        warn_once(logger, _MID_CONV_SYSTEM_HOISTED_WARNING.format(count=hoisted))

    return top, result


def _valid_mid_conv_position(
    prev: ChatMessage | None, next_msg: ChatMessage | None
) -> bool:
    # Must immediately follow a user turn or an assistant turn ending in
    # server tool use. ChatMessageTool maps to user-role on the wire.
    if isinstance(prev, ChatMessageUser | ChatMessageTool):
        prev_ok = True
    elif isinstance(prev, ChatMessageAssistant):
        prev_ok = _ends_in_server_tool_use(prev)
    else:
        prev_ok = False
    # Must end the message array or immediately precede an assistant turn.
    next_ok = next_msg is None or isinstance(next_msg, ChatMessageAssistant)
    return prev_ok and next_ok


def _ends_in_server_tool_use(message: ChatMessageAssistant) -> bool:
    if isinstance(message.content, str) or not message.content:
        return False
    return isinstance(message.content[-1], ContentToolUse)


def _previous_assistant_message_id(input: list[ChatMessage]) -> str | None:
    """Return the upstream Anthropic message id of the most recent assistant.

    The id is tagged onto ChatMessageAssistant.metadata["message_id"] in
    `model_output_from_message` whenever the cache-diagnostics beta is on, so
    a subsequent generation can pass it as `diagnostics.previous_message_id`.
    Returns None if no prior assistant message carries an id.
    """
    for m in reversed(input):
        if isinstance(m, ChatMessageAssistant):
            mid = (m.metadata or {}).get("message_id")
            return mid if isinstance(mid, str) else None
    return None


async def message_param(message: ChatMessage) -> MessageParam:
    # if content is empty that is going to result in an error when we replay
    # this message to claude, so in that case insert a NO_CONTENT message
    if isinstance(message.content, list) and len(message.content) == 0:
        # only do this for non-assistant messages or assistant message with no
        # tool calls (asst. messages w/ tool calls are fine w/ no content)
        if (
            not isinstance(message, ChatMessageAssistant)
            or len(message.tool_calls or []) == 0
        ):
            message = message.model_copy()
            message.content = [ContentText(text=NO_CONTENT)]

    # system role: only reached on Claude 4.8+ where the leading-block
    # split keeps mid-conversation system messages inline. Earlier models
    # have all system messages hoisted to the top-level system field
    # before this function is called, so role=="system" is unreachable
    # there.
    if message.role == "system":
        if isinstance(message.content, str):
            return MessageParam(role="system", content=message.content or NO_CONTENT)
        text_blocks: list[TextBlockParam] = [
            TextBlockParam(type="text", text=block.text)
            for block in message.content
            if isinstance(block, ContentText) and block.text
        ]
        if not text_blocks:
            text_blocks = [TextBlockParam(type="text", text=NO_CONTENT)]
        return MessageParam(role="system", content=text_blocks)  # type: ignore[typeddict-item]

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
                _strip_text_block_citations(item)
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
    | BetaTextBlock
    | ThinkingBlock
    | BetaThinkingBlock
    | RedactedThinkingBlock
    | BetaRedactedThinkingBlock
    | ToolUseBlock
    | BetaToolUseBlock
    | ServerToolUseBlock
    | BetaCompactionBlock
    | BetaServerToolUseBlock
    | WebSearchToolResultBlock
    | BetaWebSearchToolResultBlock
    | BetaMCPToolUseBlock
    | BetaMCPToolResultBlock
    | BetaBashCodeExecutionToolResultBlock
    | BetaTextEditorCodeExecutionToolResultBlock
    | CodeExecutionToolResultBlock
    | BetaWebFetchToolResultBlock
    | BetaFallbackBlock
]

MessageBlockParam = Union[
    TextBlockParam
    | ThinkingBlockParam
    | RedactedThinkingBlockParam
    | DocumentBlockParam
    | ImageBlockParam
    | ToolUseBlockParam
    | ServerToolUseBlockParam
    | BetaCompactionBlockParam
    | BetaServerToolUseBlockParam
    | BetaBashCodeExecutionToolResultBlockParam
    | WebSearchToolResultBlockParam
    | BetaMCPToolUseBlockParam
    | BetaRequestMCPToolResultBlockParam
    | BetaTextEditorCodeExecutionToolResultBlockParam
    | CodeExecutionToolResultBlockParam
    | BetaWebFetchToolResultBlockParam
    | BetaFallbackBlockParam
]


def _strip_text_block_citations(block: MessageBlockParam) -> MessageBlockParam:
    """Strip citations from TextBlockParam.

    Citations are not allowed inside tool result blocks — they are only
    valid on top-level text blocks in the message content.
    """
    if isinstance(block, dict) and block.get("type") == "text" and "citations" in block:
        block = cast(TextBlockParam | DocumentBlockParam, block.copy())
        del block["citations"]
    return block


async def assistant_message_blocks(
    message: ChatMessageAssistant, *, beta: bool = False
) -> list[MessageBlock]:
    blocks: list[MessageBlock] = []
    block_params = await assistant_message_block_params(message)
    for block_param in block_params:
        if block_param["type"] == "text":
            text_cls = BetaTextBlock if beta else TextBlock
            blocks.append(text_cls.model_validate(block_param))
        elif block_param["type"] == "thinking":
            thinking_cls = BetaThinkingBlock if beta else ThinkingBlock
            blocks.append(thinking_cls.model_validate(block_param))
        elif block_param["type"] == "redacted_thinking":
            redacted_cls = BetaRedactedThinkingBlock if beta else RedactedThinkingBlock
            blocks.append(redacted_cls.model_validate(block_param))
        elif block_param["type"] == "tool_use":
            if beta:
                blocks.append(
                    BetaToolUseBlock(
                        id=block_param["id"],
                        input=block_param["input"],
                        name=block_param["name"],
                        type=block_param["type"],
                    )
                )
            else:
                blocks.append(ToolUseBlock.model_validate(block_param))
        elif block_param["type"] == "server_tool_use":
            # preserve the caller link (e.g. web search w/ dynamic filtering is
            # called from a code execution block) -- synthesize 'direct' only
            # when the param doesn't carry a caller
            blocks.append(
                BetaServerToolUseBlock.model_validate(
                    {"caller": {"type": "direct"}, **block_param}
                )
            )

        elif block_param["type"] == "web_search_tool_result":
            web_search_cls = (
                BetaWebSearchToolResultBlock if beta else WebSearchToolResultBlock
            )
            blocks.append(web_search_cls.model_validate(block_param))
        elif block_param["type"] == "bash_code_execution_tool_result":
            blocks.append(
                BetaBashCodeExecutionToolResultBlock.model_validate(block_param)
            )
        elif block_param["type"] == "text_editor_code_execution_tool_result":
            blocks.append(
                BetaTextEditorCodeExecutionToolResultBlock.model_validate(block_param)
            )
        elif block_param["type"] == "code_execution_tool_result":
            blocks.append(CodeExecutionToolResultBlock.model_validate(block_param))
        elif block_param["type"] == "mcp_tool_use":
            blocks.append(BetaMCPToolUseBlock.model_validate(block_param))
        elif block_param["type"] == "mcp_tool_result":
            blocks.append(BetaMCPToolResultBlock.model_validate(block_param))
        elif block_param["type"] == "web_fetch_tool_result":
            blocks.append(BetaWebFetchToolResultBlock.model_validate(block_param))
        elif block_param["type"] == "compaction":
            blocks.append(BetaCompactionBlock.model_validate(block_param))
        elif block_param["type"] == "fallback":
            # BetaFallbackBlock requires a server-side refusal `trigger` (added in
            # anthropic 0.110.0); inspect only round-trips `from`/`to`, so
            # synthesize one when the param doesn't carry it -- mirroring the
            # server_tool_use "synthesize a default caller" pattern above.
            blocks.append(
                BetaFallbackBlock.model_validate(
                    {"trigger": {"type": "refusal"}, **block_param}
                )
            )
        else:
            logger.warning(
                f"Unexpecxted assistant message block type: {block_param['type']}"
            )

    return blocks


async def assistant_message_block_params(
    message: ChatMessageAssistant,
) -> list[MessageBlockParam]:
    block_params: list[MessageBlockParam] = []
    if isinstance(message.content, str):
        block_params = [TextBlockParam(type="text", text=message.content or NO_CONTENT)]
    else:
        # server tool spans recorded for this message at generate time. server
        # tool blocks are opaque server artifacts (encrypted content, caller
        # links, nesting) so they are replayed verbatim as a unit, while the
        # editable content (text, reasoning, client tool calls) is still
        # rendered from the content list so that scaffold edits surface.
        record = (
            assistant_internal().server_tool_spans.get(message.id)
            if message.id is not None
            else None
        )
        emitted: set[int] = set()
        for content in message.content:
            span = _server_tool_span_for_content(content, record)
            if span is not None:
                # emit the whole span verbatim at the position of its first
                # content item (subsequent items of the same span emit nothing)
                if id(span) not in emitted:
                    emitted.add(id(span))
                    block_params.extend(_span_block_params(span, message))
            else:
                block_params.extend(await message_block_params(content))
        # a span whose results never arrived (the turn ended first, e.g. a
        # client tool call cut in) has no content item to anchor it, so the
        # loop above never emits it. it must still be replayed: the API
        # resumes the pending work and requires its use block (plus the
        # `container` request param) to do so. only spans that never produced
        # content qualify -- a span whose content items were removed by a
        # scaffold edit was deleted deliberately and stays dropped.
        for span in record or []:
            if not span.content_ids and id(span) not in emitted:
                emitted.add(id(span))
                block_params.extend(_span_block_params(span, message))

    # move the first instance of thinking to the front (we only need to do this
    # for claude 3 models as we enable interleaved thinking for claude 4)
    if message.model and message.model.startswith("claude-3"):
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

    # Ensure thinking blocks are not the final block in the message.
    # The API rejects messages where the last block is thinking/redacted_thinking.
    # This can happen when the model uses its entire output budget on thinking
    # and produces no text or tool calls.
    if block_params and all(
        c.get("type") in ("thinking", "redacted_thinking") for c in block_params
    ):
        block_params.append(TextBlockParam(type="text", text=NO_CONTENT))

    return block_params


# server tool block params recorded for verbatim replay (use blocks and
# result blocks for web_search, web_fetch, and code_execution server tools)
_ServerToolSpanBlockParam = Union[
    ServerToolUseBlockParam
    | BetaServerToolUseBlockParam
    | WebSearchToolResultBlockParam
    | BetaWebFetchToolResultBlockParam
    | BetaBashCodeExecutionToolResultBlockParam
    | BetaTextEditorCodeExecutionToolResultBlockParam
    | CodeExecutionToolResultBlockParam
]


@dataclass
class _ServerToolSpan:
    """A group of server tool blocks recorded in original wire order.

    A span is one top-level server tool call group: it opens with a
    `server_tool_use` block and closes once results have arrived for it and
    for any nested tool uses it issued (e.g. web searches called from a code
    execution block when web search dynamic filtering is enabled). The API
    requires that this structure -- block order, use/result nesting, and
    `caller` source links -- be replayed exactly, so spans are recorded
    verbatim and re-emitted as a unit.
    """

    blocks: list[_ServerToolSpanBlockParam] = field(default_factory=list)
    """Block params in original wire order (callers intact)."""

    content_ids: list[str] = field(default_factory=list)
    """Ids of the ContentToolUse items produced by this span (content order)."""

    open_use_ids: set[str] = field(default_factory=set)
    """Tool use ids awaiting results.

    Used while recording to detect span completion; non-empty on a taken
    span means the turn ended with the work still pending, which is what
    obligates the follow-up request to name the container (see
    `_pending_container_for_input`)."""


class _ServerToolSpanRecorder:
    """Records server tool spans during assistant content parsing.

    A span can remain open across a pause_turn continuation (its use block
    arrives in the head message and its result in the tail), so a single
    recorder is threaded through continuation requests just like
    `pending_tool_uses`.
    """

    def __init__(self) -> None:
        self._spans: list[_ServerToolSpan] = []
        self._open: _ServerToolSpan | None = None

    def add_use(self, block: ServerToolUseBlock | BetaServerToolUseBlock) -> None:
        span = self._open_span()
        span.blocks.append(
            cast(_ServerToolSpanBlockParam, block.model_dump(exclude_none=True))
        )
        span.open_use_ids.add(block.id)

    def add_result(
        self,
        use: ServerToolUseBlock | BetaServerToolUseBlock,
        result: _ServerToolSpanBlockParam,
        content_id: str,
    ) -> None:
        span = self._open_span()
        # defensively ensure the use block is present (results normally arrive
        # within the span that their use block opened)
        if use.id not in span.open_use_ids:
            span.blocks.append(
                cast(_ServerToolSpanBlockParam, use.model_dump(exclude_none=True))
            )
        else:
            span.open_use_ids.discard(use.id)
        span.blocks.append(result)
        span.content_ids.append(content_id)
        # close the span once all of its tool uses have results
        if not span.open_use_ids:
            self._spans.append(span)
            self._open = None

    def take_spans(self, include_open: bool) -> list[_ServerToolSpan]:
        """Take all completed spans (and optionally any still-open span)."""
        spans = self._spans
        self._spans = []
        if include_open and self._open is not None:
            spans.append(self._open)
            self._open = None
        return spans

    def _open_span(self) -> _ServerToolSpan:
        if self._open is None:
            self._open = _ServerToolSpan()
        return self._open


@dataclass
class _AssistantInternal:
    thinking_blocks: dict[str, ThinkingBlockParam | RedactedThinkingBlockParam] = field(
        default_factory=dict
    )
    tool_call_internal_names: dict[str, str | None] = field(default_factory=dict)
    server_mcp_tool_uses: dict[
        str, tuple[BetaMCPToolUseBlockParam, BetaRequestMCPToolResultBlockParam]
    ] = field(default_factory=dict)
    server_tool_spans: dict[str, list[_ServerToolSpan]] = field(default_factory=dict)
    """Server tool spans keyed by assistant message id."""
    server_tool_span_index: dict[str, _ServerToolSpan] = field(default_factory=dict)
    """Server tool spans keyed by member tool use id (for replay of messages
    whose id was rewritten, e.g. by the agent bridge -- server tool use ids
    survive the bridge whereas message ids do not)."""
    containers: dict[str, str] = field(default_factory=dict)
    """Code execution container ids keyed by assistant message id.

    Replayed as the `container` request param when a turn left code
    execution pending (see `_pending_container_for_input`)."""


def assistant_internal() -> _AssistantInternal:
    return _anthropic_assistant_internal.get()


def init_sample_anthropic_assistant_internal(value: JsonValue | None = None) -> None:
    """Initialize (``value is None``) or restore the sample's assistant internal.

    Restore (``value`` from a prior :func:`dump_anthropic_assistant_internal`)
    mutates the current instance in place rather than rebinding the context
    var, so the restored state is visible outside the restoring task — see
    ``inspect_ai.model._assistant_internal``.
    """
    if value is None:
        _anthropic_assistant_internal.set(_AssistantInternal())
        return
    assert isinstance(value, dict)
    internal = assistant_internal()
    internal.thinking_blocks.update(
        cast("dict[str, Any]", value.get("thinking_blocks", {}))
    )
    internal.tool_call_internal_names.update(
        cast("dict[str, str | None]", value.get("tool_call_internal_names", {}))
    )
    internal.server_mcp_tool_uses.update(
        {
            tool_use_id: (use, result)
            for tool_use_id, (use, result) in cast(
                "dict[str, Any]", value.get("server_mcp_tool_uses", {})
            ).items()
        }
    )
    # Spans were dumped as an identity-deduped table with the two maps
    # holding indices into it; rebuilding from the table restores the
    # object sharing between (and within) the maps.
    spans = [
        _ServerToolSpan(
            blocks=cast("list[_ServerToolSpanBlockParam]", span["blocks"]),
            content_ids=cast("list[str]", span["content_ids"]),
            open_use_ids=set(cast("list[str]", span["open_use_ids"])),
        )
        for span in cast("list[dict[str, Any]]", value.get("spans", []))
    ]
    internal.server_tool_spans.update(
        {
            message_id: [spans[index] for index in indexes]
            for message_id, indexes in cast(
                "dict[str, list[int]]", value.get("server_tool_spans", {})
            ).items()
        }
    )
    internal.server_tool_span_index.update(
        {
            content_id: spans[index]
            for content_id, index in cast(
                "dict[str, int]", value.get("server_tool_span_index", {})
            ).items()
        }
    )
    internal.containers.update(cast("dict[str, str]", value.get("containers", {})))


def dump_anthropic_assistant_internal() -> JsonValue | None:
    """Dump the sample's assistant internal as a JSON value (``None`` if empty).

    Block params are the SDK's ``TypedDict`` request params — plain dicts
    at runtime, so they serialize as-is and restore via cast with no
    validation (corrupt data surfaces at request time, as it would have
    in-memory). ``_ServerToolSpan`` objects are shared between
    ``server_tool_spans`` and ``server_tool_span_index`` (and the index can
    hold spans absent from the message map), so spans are dumped once into
    a table and the maps reference table indices.
    """
    internal = assistant_internal()
    span_table: list[_ServerToolSpan] = []
    span_indexes: dict[int, int] = {}
    for span in (
        *(s for spans in internal.server_tool_spans.values() for s in spans),
        *internal.server_tool_span_index.values(),
    ):
        if id(span) not in span_indexes:
            span_indexes[id(span)] = len(span_table)
            span_table.append(span)

    if not (
        internal.thinking_blocks
        or internal.tool_call_internal_names
        or internal.server_mcp_tool_uses
        or span_table
        or internal.containers
    ):
        return None
    return cast(
        JsonValue,
        {
            "thinking_blocks": dict(internal.thinking_blocks),
            "tool_call_internal_names": dict(internal.tool_call_internal_names),
            "server_mcp_tool_uses": {
                tool_use_id: list(use_result)
                for tool_use_id, use_result in internal.server_mcp_tool_uses.items()
            },
            "spans": [
                {
                    "blocks": span.blocks,
                    "content_ids": span.content_ids,
                    "open_use_ids": sorted(span.open_use_ids),
                }
                for span in span_table
            ],
            "server_tool_spans": {
                message_id: [span_indexes[id(span)] for span in spans]
                for message_id, spans in internal.server_tool_spans.items()
            },
            "server_tool_span_index": {
                content_id: span_indexes[id(span)]
                for content_id, span in internal.server_tool_span_index.items()
            },
            "containers": dict(internal.containers),
        },
    )


_anthropic_assistant_internal: ContextVar[_AssistantInternal] = ContextVar(
    "anthropic_assistant_internal", default=_AssistantInternal()
)


def record_server_tool_spans(message_id: str, spans: list[_ServerToolSpan]) -> None:
    """Record server tool spans for an assistant message (verbatim replay)."""
    internal = assistant_internal()
    internal.server_tool_spans[message_id] = (
        internal.server_tool_spans.get(message_id, []) + spans
    )
    for span in spans:
        for content_id in span.content_ids:
            internal.server_tool_span_index[content_id] = span


def index_server_tool_spans(spans: list[_ServerToolSpan]) -> None:
    """Register spans in the tool use id index only (no message id record).

    Used when re-parsing conversation history (e.g. via the agent bridge):
    only fills gaps so that spans recorded at generate time -- which have
    full fidelity -- are never overwritten.
    """
    internal = assistant_internal()
    for span in spans:
        if not any(
            content_id in internal.server_tool_span_index
            for content_id in span.content_ids
        ):
            for content_id in span.content_ids:
                internal.server_tool_span_index[content_id] = span


def merge_server_tool_spans(head_id: str | None, tail_id: str | None) -> None:
    """Re-key the head message's spans and container under the tail message id.

    Continuations merge head message content into the tail message, so spans
    (and the container id) recorded under the head message id belong to the
    tail message.
    """
    if head_id is None or tail_id is None or head_id == tail_id:
        return
    internal = assistant_internal()
    head_spans = internal.server_tool_spans.pop(head_id, [])
    if head_spans:
        internal.server_tool_spans[tail_id] = (
            head_spans + internal.server_tool_spans.get(tail_id, [])
        )
    head_container = internal.containers.pop(head_id, None)
    if head_container is not None:
        # the tail response's own container (the same container, re-reported)
        # wins if present
        internal.containers.setdefault(tail_id, head_container)


def _pending_container_for_input(input: list[ChatMessage]) -> str | None:
    """Container id to resume when the last assistant turn left work pending.

    A turn that mixes code-execution-backed server tool use (including web
    search with dynamic filtering) with a client tool call ends with
    stop_reason "tool_use" while the container work is still running. The
    follow-up request must name the container or the API rejects it with
    "container_id is required when there are pending tool uses generated by
    code execution with tools."

    Only pending work triggers this -- a container from fully-completed work
    is not replayed, since unconditionally reusing containers across turns
    would change behavior (state carry-over) and risk naming an expired
    container.
    """
    last_assistant = next(
        (m for m in reversed(input) if isinstance(m, ChatMessageAssistant)), None
    )
    if last_assistant is None or last_assistant.id is None:
        return None
    internal = assistant_internal()
    container = internal.containers.get(last_assistant.id)
    if container is None:
        return None
    spans = internal.server_tool_spans.get(last_assistant.id, [])
    if any(span.open_use_ids for span in spans):
        return container
    return None


def _server_tool_span_for_content(
    content: Content, record: list[_ServerToolSpan] | None
) -> _ServerToolSpan | None:
    """Resolve the recorded server tool span for a content item (if any)."""
    if not isinstance(content, ContentToolUse) or content.tool_type == "mcp_call":
        return None
    # match within the message's own record
    if record is not None:
        for span in record:
            if content.id in span.content_ids:
                return span
    # fall back to the sample-wide index (handles message ids rewritten by
    # the agent bridge -- server tool use ids survive the bridge)
    return assistant_internal().server_tool_span_index.get(content.id)


def _span_block_params(
    span: _ServerToolSpan, message: ChatMessageAssistant
) -> list[MessageBlockParam]:
    """Block params for a span (with compaction result-clearing applied)."""
    # determine which of the span's results were cleared during compaction
    cleared_ids = (
        {
            c.id
            for c in message.content
            if isinstance(c, ContentToolUse)
            and c.id in span.content_ids
            and is_result_cleared(c)
        }
        if isinstance(message.content, list)
        else set()
    )
    if not cleared_ids:
        return cast(list[MessageBlockParam], list(span.blocks))

    # deep copy so the recorded blocks are never mutated
    blocks = deepcopy(list(span.blocks))
    for i, block in enumerate(blocks):
        if cast(dict[str, Any], block).get("tool_use_id") in cleared_ids:
            blocks[i] = _cleared_result_block_param(block)
    return cast(list[MessageBlockParam], blocks)


def _cleared_result_block_param(
    block_param: _ServerToolSpanBlockParam,
) -> _ServerToolSpanBlockParam:
    """Copy of a server tool result block param with its result content removed."""
    block = cast(dict[str, Any], block_param)
    cleared: dict[str, Any]
    match block.get("type"):
        case "web_search_tool_result":
            cleared = {
                **block,
                "content": {
                    "type": "web_search_tool_result_error",
                    "error_code": "unavailable",
                },
            }
        case "web_fetch_tool_result":
            original_content = block.get("content", {})
            url = (
                str(original_content.get("url", ""))
                if isinstance(original_content, dict)
                else ""
            )
            cleared = {
                **block,
                "content": {
                    "type": "web_fetch_result",
                    "url": url,
                    "content": {
                        "type": "document",
                        "source": {
                            "type": "text",
                            "media_type": "text/plain",
                            "data": TOOL_RESULT_REMOVED,
                        },
                    },
                },
            }
        case "bash_code_execution_tool_result":
            cleared = {
                **block,
                "content": {
                    "type": "bash_code_execution_result",
                    "return_code": 0,
                    "stdout": TOOL_RESULT_REMOVED,
                    "stderr": "",
                    "content": [],
                },
            }
        case "text_editor_code_execution_tool_result":
            # use a view result with placeholder for text editor
            cleared = {
                **block,
                "content": {
                    "type": "text_editor_code_execution_view_result",
                    "content": TOOL_RESULT_REMOVED,
                    "file_type": "text",
                },
            }
        case "code_execution_tool_result":
            cleared = {
                **block,
                "content": {
                    "type": "code_execution_result",
                    "return_code": 0,
                    "stdout": TOOL_RESULT_REMOVED,
                    "stderr": "",
                    "content": [],
                },
            }
        case _:
            # not a result block (e.g. server_tool_use) -- leave as-is
            cleared = block
    return cast(_ServerToolSpanBlockParam, cleared)


async def model_output_from_message(
    client: AsyncAnthropic | AsyncAnthropicBedrock | AsyncAnthropicVertex | None,
    model: str | None,
    message: Message,
    tools: list[ToolInfo],
    pending_tool_uses: dict[str, ServerToolUseBlock | BetaServerToolUseBlock]
    | None = None,
    pending_mcp_tool_uses: dict[str, BetaMCPToolUseBlock] | None = None,
    cache_diagnostics: bool = False,
    span_recorder: _ServerToolSpanRecorder | None = None,
) -> tuple[ModelOutput, bool]:
    # record server tool spans for verbatim replay on subsequent turns
    if span_recorder is None:
        span_recorder = _ServerToolSpanRecorder()

    # extract content and tool calls
    content, tool_calls = content_and_tool_calls_from_assistant_content_blocks(
        message.content,
        tools,
        pending_tool_uses=pending_tool_uses,
        pending_mcp_tool_uses=pending_mcp_tool_uses,
        span_recorder=span_recorder,
    )

    # count reasoning tokens
    reasoning_tokens = 0
    if client and model:
        for content_block in message.content:
            if isinstance(content_block, ThinkingBlock):
                reasoning_tokens += await count_tokens(
                    client, model, content_block.thinking
                )

    # cache-diagnostics: tag the assistant message with the upstream id so a
    # subsequent turn can pass it as `diagnostics.previous_message_id`.
    # The `diagnostics` response field itself is captured below onto the
    # ModelOutput metadata, not the assistant message. Only when the beta
    # is on.
    asst_metadata: dict[str, Any] = {}
    if cache_diagnostics:
        msg_id = getattr(message, "id", None)
        if msg_id:
            asst_metadata["message_id"] = msg_id

    # server-side refusal fallback: collect handoffs (in content order) so we
    # can surface the serving model and a structured metadata entry. on a
    # streaming mid-output decline `message.model` names the *requested* model,
    # so the serving model is the final handoff's `to` model.
    fallback_handoffs = [
        {"from": from_model, "to": to_model}
        for block in message.content
        if getattr(block, "type", None) == "fallback"
        for from_model, to_model in [_fallback_block_models(block)]
    ]
    serving_model = (
        fallback_handoffs[-1]["to"] or message.model
        if fallback_handoffs
        else message.model
    )

    # resolve choice
    stop_reason, pause_turn = message_stop_reason(message)
    choice = ChatCompletionChoice(
        message=ChatMessageAssistant(
            content=content,
            tool_calls=tool_calls,
            model=serving_model,
            source="generate",
            metadata=asst_metadata or None,
        ),
        stop_reason=stop_reason,
        stop_details=collect_stop_details(
            "anthropic", logger, lambda: message_stop_details(message)
        ),
    )

    # record server tool spans under the assistant message id for verbatim
    # replay on subsequent turns. when pause_turn, an in-flight span may still
    # be open (its result arrives in the continuation) -- leave it in the
    # recorder so it completes during the continuation parse.
    spans = span_recorder.take_spans(include_open=not pause_turn)
    if spans and choice.message.id is not None:
        record_server_tool_spans(choice.message.id, spans)

    # record the code execution container id so a follow-up request can name
    # it when this turn left container work pending
    if message.container is not None and choice.message.id is not None:
        assistant_internal().containers[choice.message.id] = message.container.id

    # return ModelOutput
    usage = message.usage.model_dump()
    input_tokens_cache_write = usage.get("cache_creation_input_tokens", None)
    input_tokens_cache_read = usage.get("cache_read_input_tokens", None)

    # When compaction occurs, the top-level usage excludes compaction iteration
    # tokens, so we aggregate the per-iteration usage for accuracy. Server-side
    # fallback also populates `iterations` (a `fallback_message` entry for the
    # serving attempt plus a `message` entry per declined attempt), but there
    # the top-level usage already describes the serving (billed) attempt and an
    # unbilled refused attempt must NOT be summed in — so detect fallback by
    # the `fallback_message` marker and use the top-level usage as-is.
    iterations = usage.get("iterations", None)
    is_fallback_iterations = isinstance(iterations, list) and any(
        isinstance(it, dict) and it.get("type") == "fallback_message"
        for it in iterations
    )
    if (
        isinstance(iterations, list)
        and len(iterations) > 0
        and not is_fallback_iterations
    ):
        # Aggregate tokens from all iterations
        input_tokens = sum(
            it.get("input_tokens", 0) for it in iterations if isinstance(it, dict)
        )
        output_tokens = sum(
            it.get("output_tokens", 0) for it in iterations if isinstance(it, dict)
        )
    else:
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens

    total_tokens = (
        input_tokens
        + (input_tokens_cache_write or 0)
        + (input_tokens_cache_read or 0)
        + output_tokens  # includes reasoning tokens
    )

    # Capture any undeclared fields on the Message (SDK uses extra="allow")
    # so callers can read response fields we don't model explicitly.
    extra_body = getattr(message, "model_extra", None) or {}
    metadata: dict[str, Any] | None = (
        {"extra_body": dict(extra_body)} if extra_body else None
    )

    # server-side refusal fallback: record a typed ModelFallback so log
    # analysis can detect a fallback without parsing assistant content. the
    # handoff chain and per-attempt `usage.iterations` are surfaced as
    # diagnostics on ModelFallback.metadata.
    fallback: ModelFallback | None = None
    requested_model = fallback_handoffs[0]["from"] if fallback_handoffs else None
    if requested_model and serving_model:
        fallback = ModelFallback(
            model=requested_model,
            fallback_model=serving_model,
            metadata={"handoffs": fallback_handoffs, "iterations": iterations},
        )

    # Cache diagnostics: surface the `diagnostics` response field as a
    # top-level metadata key (in addition to its automatic capture under
    # extra_body), and emit a one-time warning when a cache miss is named.
    # Routed through ModelOutput.metadata rather than the assistant message
    # because diagnostics is per-response, not part of the next-turn input.
    if cache_diagnostics:
        diagnostics = getattr(message, "diagnostics", None)
        if diagnostics is not None:
            diag_dict = (
                diagnostics.model_dump()
                if hasattr(diagnostics, "model_dump")
                else dict(diagnostics)
            )
            metadata = (metadata or {}) | {"diagnostics": diag_dict}
            reason = diag_dict.get("cache_miss_reason")
            reason_type = reason.get("type") if isinstance(reason, dict) else None
            if reason_type:
                warn_once(logger, _CACHE_MISS_WARNING.format(reason=reason_type))

    return (
        ModelOutput(
            model=serving_model,
            choices=[choice],
            usage=ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                input_tokens_cache_write=input_tokens_cache_write,
                input_tokens_cache_read=input_tokens_cache_read,
                reasoning_tokens=reasoning_tokens if reasoning_tokens > 0 else None,
            ),
            fallback=fallback,
            metadata=metadata,
        ),
        pause_turn,
    )


content_block_adapter = TypeAdapter[
    BetaCompactionBlock
    | BetaServerToolUseBlock
    | BetaBashCodeExecutionToolResultBlock
    | BetaTextEditorCodeExecutionToolResultBlock
    | BetaWebFetchToolResultBlock
    | ContentBlock,
](
    BetaCompactionBlock
    | BetaServerToolUseBlock
    | BetaBashCodeExecutionToolResultBlock
    | BetaTextEditorCodeExecutionToolResultBlock
    | BetaWebFetchToolResultBlock
    | ContentBlock,
)


def content_and_tool_calls_from_assistant_content_blocks(
    content_blocks_input: Sequence[
        BetaCompactionBlockParam
        | BetaServerToolUseBlockParam
        | BetaBashCodeExecutionToolResultBlockParam
        | BetaTextEditorCodeExecutionToolResultBlock
        | ContentBlockParam
        | ContentBlock
    ],
    tools: list[ToolInfo],
    pending_tool_uses: dict[str, ServerToolUseBlock | BetaServerToolUseBlock]
    | None = None,
    pending_mcp_tool_uses: dict[str, BetaMCPToolUseBlock] | None = None,
    span_recorder: _ServerToolSpanRecorder | None = None,
) -> tuple[list[Content], list[ToolCall] | None]:
    # when no span recorder is provided (e.g. parsing scaffold conversation
    # history via the agent bridge) record spans locally and register them in
    # the tool use id index at the end (gap-filling only -- see
    # index_server_tool_spans)
    local_span_recorder = span_recorder is None
    if span_recorder is None:
        span_recorder = _ServerToolSpanRecorder()

    # resolve params to blocks
    content_blocks: list[
        BetaCompactionBlock
        | BetaServerToolUseBlock
        | BetaBashCodeExecutionToolResultBlock
        | BetaTextEditorCodeExecutionToolResultBlock
        | BetaWebFetchToolResultBlock
        | BetaFallbackBlock
        | ContentBlock
    ] = []
    for block in content_blocks_input:
        if isinstance(block, dict):
            # server_tool_use blocks may come back without a 'caller' field
            # (e.g., from message history in multi-turn conversations).
            # BetaServerToolUseBlock requires 'caller', so add a default.
            if block.get("type") == "server_tool_use" and "caller" not in block:
                content_blocks.append(
                    BetaServerToolUseBlock(
                        **block, caller=BetaDirectCaller(type="direct")
                    )
                )
            elif block.get("type") == "fallback":  # type: ignore[comparison-overlap]
                # the fallback block is not in the content block union, so
                # validate it explicitly (e.g. echoed scaffold history via the
                # agent bridge arrives as a dict). tolerate `from_` — the
                # reserved-keyword `from` alias is mangled when a message is
                # dumped without by_alias (e.g. the sandbox bridge).
                fb = dict(block)
                if "from_" in fb and "from" not in fb:
                    fb["from"] = fb.pop("from_")
                # BetaFallbackBlock requires a server-side refusal `trigger`
                # (added in anthropic 0.110.0); scaffold-echoed history doesn't
                # carry it, so synthesize one. inspect never reads `trigger`.
                fb.setdefault("trigger", {"type": "refusal"})
                content_blocks.append(BetaFallbackBlock.model_validate(fb))
            else:
                content_blocks.append(content_block_adapter.validate_python(block))
        else:
            content_blocks.append(block)

    # extract content and tool calls
    content: list[Content] = []
    tool_calls: list[ToolCall] | None = None

    if pending_tool_uses is None:
        pending_tool_uses = dict()
    if pending_mcp_tool_uses is None:
        pending_mcp_tool_uses = dict()

    # server-side fallback: a declined attempt's content precedes the final
    # `fallback` handoff block. The API forbids replaying thinking and unpaired
    # client tool_use from the declined attempt, so drop them at conversion
    # time (the raw blocks remain in the ModelCall log for analysis). Text and
    # paired server tool blocks before the boundary are kept.
    last_fallback_index = -1
    for i, content_block in enumerate(content_blocks):
        if getattr(content_block, "type", None) == "fallback":
            last_fallback_index = i

    for index, content_block in enumerate(content_blocks):
        before_fallback_boundary = index < last_fallback_index
        if before_fallback_boundary and isinstance(
            content_block, (ThinkingBlock, RedactedThinkingBlock, ToolUseBlock)
        ):
            continue
        if content_block.type == "mcp_tool_use":  # type: ignore[comparison-overlap]
            tool_use_block = BetaMCPToolUseBlock.model_validate(
                content_block.model_dump()
            )
            pending_mcp_tool_uses[tool_use_block.id] = tool_use_block
        elif content_block.type == "mcp_tool_result":  # type: ignore[comparison-overlap]
            tool_result_block = BetaMCPToolResultBlock.model_validate(
                content_block.model_dump()
            )
            pending_mcp_tool_use = pending_mcp_tool_uses.pop(
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
        elif content_block.type == "web_fetch_tool_result":
            # confirm that there is a pending tool use
            pending_tool_use = pending_tool_uses.pop(content_block.tool_use_id, None)
            if pending_tool_use is None:
                raise RuntimeError(
                    "BetaWebFetchToolResultBlock without previous ServerToolUseBlock"
                )

            # record span block params for verbatim replay
            span_recorder.add_result(
                pending_tool_use,
                cast(
                    BetaWebFetchToolResultBlockParam,
                    content_block.model_dump(exclude_none=True),
                ),
                pending_tool_use.id,
            )

            # append content
            content.append(
                ContentToolUse(
                    tool_type="web_search",
                    id=pending_tool_use.id,
                    name="web_fetch",
                    arguments=to_json_str_safe(pending_tool_use.input),
                    result=to_json_tool_result_safe(content_block),
                )
            )

        elif (
            content_block.type == "bash_code_execution_tool_result"
            or content_block.type == "text_editor_code_execution_tool_result"
            or content_block.type == "code_execution_tool_result"
        ):
            # confirm that there is a pending tool use
            pending_tool_use = pending_tool_uses.pop(content_block.tool_use_id, None)
            if pending_tool_use is None:
                raise RuntimeError(
                    "CodeExecutionToolResultBlock without previous ServerToolUseBlock"
                )

            # record span block params for verbatim replay
            span_recorder.add_result(
                pending_tool_use,
                cast(
                    BetaBashCodeExecutionToolResultBlockParam
                    | BetaTextEditorCodeExecutionToolResultBlockParam
                    | CodeExecutionToolResultBlockParam,
                    content_block.model_dump(exclude_none=True),
                ),
                pending_tool_use.id,
            )

            # append to content
            content.append(
                ContentToolUse(
                    tool_type="code_execution",
                    id=pending_tool_use.id,
                    name=pending_tool_use.name,
                    arguments=to_json_str_safe(pending_tool_use.input),
                    result=to_json_tool_result_safe(content_block),
                )
            )
        elif content_block.type == "compaction":
            content.append(_content_data_for_compaction(content_block))

        elif content_block.type == "fallback":
            # server-side refusal fallback handoff marker. wrap as ContentData
            # (mirroring compaction) so it round-trips replay and the bridge.
            # NOTE: this must precede the TextBlock branch — the non-beta SDK
            # client parses the unknown block as a loose TextBlock.
            content.append(_content_data_for_fallback(content_block))

        elif isinstance(content_block, TextBlock):
            if content_block.text is None:
                continue
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
        elif isinstance(content_block, (ServerToolUseBlock, BetaServerToolUseBlock)):
            pending_tool_uses[content_block.id] = content_block
            span_recorder.add_use(content_block)
        elif isinstance(
            content_block, (WebSearchToolResultBlock, BetaWebSearchToolResultBlock)
        ):
            pending_tool_use = pending_tool_uses.pop(content_block.tool_use_id, None)
            if pending_tool_use is None:
                raise RuntimeError(
                    "WebSearchToolResultBlock without previous ServerToolUseBlock"
                )

            # record span block params for verbatim replay
            span_recorder.add_result(
                pending_tool_use,
                cast(
                    WebSearchToolResultBlockParam,
                    content_block.model_dump(exclude_none=True),
                ),
                pending_tool_use.id,
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

        elif isinstance(content_block, ThinkingBlock):
            # anthropic reasoning is now always a summary (save for Sonnet 3.7):
            # https://platform.claude.com/docs/en/build-with-claude/extended-thinking#differences-in-thinking-across-model-versions
            content.append(
                ContentReasoning(
                    summary=content_block.thinking,
                    reasoning=content_block.signature,
                    redacted=True,
                )
            )

            # reasoning won't round trip through bridges w/ simplistic handling
            # (e.g. OpenAI completions) so we also save for replay)
            assistant_internal().thinking_blocks[mm3_hash(content_block.signature)] = (
                cast(ThinkingBlockParam, content_block.model_dump(exclude_none=True))
            )

        elif isinstance(content_block, RedactedThinkingBlock):
            # redacted reasoning has no summary
            content.append(
                ContentReasoning(reasoning=content_block.data, redacted=True)
            )

            # reasoning won't round trip through bridges w/ simplistic handling
            # (e.g. OpenAI completions) so we also save for replay
            assistant_internal().thinking_blocks[mm3_hash(content_block.data)] = cast(
                RedactedThinkingBlockParam, content_block.model_dump(exclude_none=True)
            )

    # locally recorded spans (history re-parse) fill gaps in the tool use id
    # index (spans recorded at generate time are keyed by message id by our
    # caller and take precedence)
    if local_span_recorder:
        index_server_tool_spans(span_recorder.take_spans(include_open=True))

    return content, tool_calls


# deal with tool results that may have been created with
# model_construct b/c of the bridge
def to_json_tool_result_safe(result: Any) -> str:
    if isinstance(result, BaseModel):
        result = result.model_dump(exclude_none=True)
    return to_json_str_safe(result)


EDITS = "edits"
EDIT_TYPE = "type"
COMPACT_20260112 = "compact_20260112"
EXTRA_BODY = "extra_body"
CONTEXT_MANAGEMENT = "context_management"
MIN_COMPACTION_TOKENS = 50000  # Anthropic API minimum trigger value
FALLBACK_BETA = "server-side-fallback-2026-06-01"


def _add_edit_compaction(
    request: dict[str, Any], betas: list[str], has_1mm_context: bool = False
) -> None:
    """Add compaction edit to request without triggering new compaction.

    When messages already contain compaction blocks, we need to include
    context_management for the API to accept them. We set trigger just
    below the context window limit to prevent automatic compaction
    (user controls compaction via their own threshold).
    """
    # Determine max trigger based on context window
    if ("context-1m-2025-08-07" in betas) or has_1mm_context:
        max_trigger = 990_000  # Just below 1M context
    else:
        max_trigger = 190_000  # Just above default 150k trigger

    extra_body = request.setdefault(EXTRA_BODY, {})
    context_mgmt = extra_body.setdefault(CONTEXT_MANAGEMENT, {})
    context_mgmt.setdefault(EDITS, []).append(
        {
            EDIT_TYPE: COMPACT_20260112,
            "trigger": {"type": "input_tokens", "value": max_trigger},
        }
    )


def _request_has_edit_compaction(request: dict[str, Any]) -> bool:
    edits = request.get(EXTRA_BODY, {}).get(CONTEXT_MANAGEMENT, {}).get(EDITS, [])
    return isinstance(edits, list) and any(
        isinstance(e, dict) and e.get(EDIT_TYPE) == COMPACT_20260112 for e in edits
    )


def _input_has_compaction(input: list[ChatMessage]) -> bool:
    return any(
        [
            _message_has_compaction(m)
            for m in input
            if isinstance(m, ChatMessageAssistant)
        ]
    )


def _message_has_compaction(message: ChatMessageAssistant) -> bool:
    return _compaction_from_message(message) is not None


def _content_data_for_compaction(block: BetaCompactionBlock) -> ContentData:
    return ContentData(
        data={
            "compaction_metadata": {
                "type": "anthropic_compact",
                "content": block.content,
            }
        }
    )


def _compaction_from_content_data(
    content: ContentData,
) -> BetaCompactionBlockParam | None:
    compaction_metadata = content.data.get("compaction_metadata", None)
    if isinstance(compaction_metadata, dict):
        if compaction_metadata.get("type") == "anthropic_compact":
            compaction_content = compaction_metadata.get("content", None)
            if compaction_content is not None and not isinstance(
                compaction_content, str
            ):
                logger.warning(
                    f"Unexpected compaction content type: {type(compaction_content).__name__}"
                )
                compaction_content = None
            return BetaCompactionBlockParam(
                type="compaction",
                content=compaction_content,
            )

    return None


def _compaction_from_message(
    message: ChatMessageAssistant,
) -> BetaCompactionBlockParam | None:
    if isinstance(message.content, list):
        for c in message.content:
            if isinstance(c, ContentData):
                result = _compaction_from_content_data(c)
                if result is not None:
                    return result

    return None


def _is_compaction_content(content: Content) -> bool:
    """Check if content is a compaction block."""
    if isinstance(content, ContentData):
        return _compaction_from_content_data(content) is not None
    return False


def _fallback_block_models(block: Any) -> tuple[str | None, str | None]:
    """Extract (from_model, to_model) from a server-side fallback block.

    Handles both the typed BetaFallbackBlock (from the bridge dict path) and
    the lenient TextBlock the non-beta SDK client produces for an unknown
    `fallback` block (with `from`/`to` carried in `model_extra`).
    """

    def info_model(info: Any) -> str | None:
        if info is None:
            return None
        if isinstance(info, dict):
            return info.get("model")
        return getattr(info, "model", None)

    from_info = getattr(block, "from_", None)
    to_info = getattr(block, "to", None)
    extra = getattr(block, "model_extra", None) or {}
    if from_info is None:
        from_info = extra.get("from")
    if to_info is None:
        to_info = extra.get("to")
    return info_model(from_info), info_model(to_info)


def _content_data_for_fallback(block: Any) -> ContentData:
    from_model, to_model = _fallback_block_models(block)
    return ContentData(
        data={
            "fallback_metadata": {
                "type": "anthropic_fallback",
                "from": {"model": from_model},
                "to": {"model": to_model},
            }
        }
    )


def _fallback_from_content_data(
    content: ContentData,
) -> BetaFallbackBlockParam | None:
    fallback_metadata = content.data.get("fallback_metadata", None)
    if isinstance(fallback_metadata, dict):
        if fallback_metadata.get("type") == "anthropic_fallback":
            from_info = fallback_metadata.get("from")
            to_info = fallback_metadata.get("to")
            to_model = to_info.get("model") if isinstance(to_info, dict) else None
            param = BetaFallbackBlockParam(
                type="fallback",
                to=BetaFallbackInfoParam(model=to_model),  # type: ignore[typeddict-item]
            )
            # `from` is a reserved keyword — set via dict key
            from_model = from_info.get("model") if isinstance(from_info, dict) else None
            if from_model is not None:
                cast(dict[str, Any], param)["from"] = {"model": from_model}
            return param

    return None


def _fallback_from_content(content: Content) -> dict[str, Any] | None:
    if isinstance(content, ContentData):
        meta = content.data.get("fallback_metadata", None)
        if isinstance(meta, dict) and meta.get("type") == "anthropic_fallback":
            return meta
    return None


def _input_has_fallback(input: list[ChatMessage]) -> bool:
    return any(
        _fallback_from_content(c) is not None
        for m in input
        if isinstance(m, ChatMessageAssistant) and isinstance(m.content, list)
        for c in m.content
    )


def _warn_refusal_without_fallback(
    api: "AnthropicAPI", config: GenerateConfig, output: ModelOutput
) -> None:
    """Suggest fallback_models when a rescuable classifier refusal occurs.

    Fires only when fallback could actually have been used: fallback_models
    not configured, first-party non-batch API, and a Claude 5+ requested model
    (the `fallbacks` param is only accepted for models publishing
    allowed_fallback_models -- Opus 4.7/4.8 emit the same refusal stop_details
    but cannot fall back).
    """
    if config.fallback_models:
        return
    if api.is_bedrock() or api.is_vertex() or api.is_azure():
        return
    if normalized_batch_config(config.batch):
        return
    if not (api.is_claude_5() or api.is_claude_latest()):
        return
    # classifier refusal (stop_details.type == "refusal") distinguishes
    # rescuable safety-classifier declines from other content_filter stops
    choice = output.choices[0] if output.choices else None
    if choice is None or choice.stop_reason != "content_filter":
        return
    details = choice.stop_details
    if details is None or details.type != "refusal":
        return
    category = f" (category: {details.category})" if details.category else ""
    warn_once(
        logger,
        f"{output.model} declined this request with a safety classifier "
        f"refusal{category}. Such requests can usually be served by a "
        "fallback model — set the fallback_models generate config "
        "(e.g. --fallback-models claude-opus-4-8) to retry refused "
        "requests automatically. Learn more at "
        "https://inspect.aisi.org.uk/fallbacks.html.",
    )


def _strip_reasoning(message: ChatMessageAssistant) -> ChatMessageAssistant:
    """Strip reasoning blocks from a compacted assistant message.

    The compaction generate call may include reasoning (thinking) blocks
    that reflect the model's thinking about compaction, not the task itself.
    These should be removed so they don't waste input tokens on subsequent turns.
    """
    if not isinstance(message.content, list):
        return message
    stripped = [c for c in message.content if not isinstance(c, ContentReasoning)]
    if len(stripped) == len(message.content):
        return message  # nothing to strip
    return message.model_copy(update={"content": stripped})


async def _capture_compaction_from_stream(
    stream: AsyncMessageStream,
) -> tuple[Message, str | None]:
    """Consume a streaming response and capture content the SDK drops.

    The Anthropic SDK's streaming doesn't properly accumulate compaction_delta
    events into the final message snapshot. This function iterates through all
    streaming events, captures any compaction_delta content, and returns the
    final message with the compaction content properly set.

    It also captures the code execution `container` from the message_delta
    event: the SDK's non-beta stream accumulator drops it, so the snapshot
    always reports `container=None` and container continuations (which must
    echo the id back as the `container` request param) would fail. Remove
    once https://github.com/anthropics/anthropic-sdk-python/pull/1776 lands.

    Args:
        stream: The Anthropic AsyncMessageStream from messages.stream().

    Returns:
        A tuple of (message, compaction_content) where message is the final
        message snapshot with compaction blocks fixed up, and compaction_content
        is the raw content captured from compaction_delta events (or None).
    """
    compaction_content: str | None = None
    container: Container | None = None

    # Iterate through all streaming events to capture compaction_delta content
    async for event in stream:
        # WORKAROUND for an Anthropic python SDK bug: the non-beta stream
        # accumulator drops `message_delta.container`, so the final snapshot
        # always reports container=None even though the wire delivered the id
        # (breaking code execution container continuations). Capture it from
        # the raw event and patch the snapshot below. Remove this (and the
        # patch below) once the upstream fix lands:
        # https://github.com/anthropics/anthropic-sdk-python/pull/1776
        if event.type == "message_delta":
            container = getattr(event.delta, "container", None) or container
        if (
            hasattr(event, "delta")
            and getattr(event.delta, "type", None) == "compaction_delta"
        ):
            compaction_content = getattr(event.delta, "content", None)

    # Get the final message snapshot
    message = stream.current_message_snapshot
    # WORKAROUND (see above): patch the container the SDK snapshot dropped
    if message.container is None and container is not None:
        message.container = container

    # Fix up compaction blocks with captured content
    if compaction_content is not None:
        for block in message.content:
            if getattr(block, "type", None) == "compaction":
                setattr(block, "content", compaction_content)
                break

    return message, compaction_content


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


def message_stop_details(message: Message) -> StopDetails | None:
    """Extract refusal detail from an Anthropic `Message.stop_details` (Opus 4.7+).

    Anthropic reports a single named category (`cyber`/`bio`); it is mirrored into
    `categories` so callers can read the list uniformly across providers.
    """
    details = getattr(message, "stop_details", None)
    if details is None:
        return None
    category = getattr(details, "category", None)
    return StopDetails(
        type=getattr(details, "type", None),
        category=category,
        explanation=getattr(details, "explanation", None),
        categories=[StopCategory(category=category)] if category else [],
    )


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
        # lookup in assistant internal
        thinking_block_param = assistant_internal().thinking_blocks.get(
            mm3_hash(content.reasoning), None
        )
        if thinking_block_param is not None:
            return [thinking_block_param]
        else:
            # reconstruct reasoning
            if content.summary is not None:
                return [
                    ThinkingBlockParam(
                        type="thinking",
                        thinking=content.summary,
                        signature=content.reasoning,
                    )
                ]
            elif content.redacted and content.signature is not None:
                return [
                    RedactedThinkingBlockParam(
                        type="redacted_thinking", data=content.signature
                    )
                ]

        # if it's not in there then this is reasoning that is coming from another
        # system (e.g. in an agent handoff) so we turn it into normal text
        return [TextBlockParam(type="text", text=content.text)]

    elif isinstance(content, ContentToolUse):
        # Check if result was cleared during compaction
        result_cleared = is_result_cleared(content)

        # Try to use cached blocks, creating copies if result needs to be cleared
        # (web_search/web_fetch/code_execution are resolved against recorded
        # server tool spans in assistant_message_block_params before reaching
        # here, so a non-mcp ContentToolUse below is from another system)
        if content.id in assistant_internal().server_mcp_tool_uses:
            mcp_use, mcp_result = assistant_internal().server_mcp_tool_uses[content.id]
            if result_cleared:
                # Create a copy to avoid mutating the cached version
                mcp_result = cast(
                    BetaRequestMCPToolResultBlockParam,
                    {**mcp_result, "content": TOOL_RESULT_REMOVED},
                )
            return [mcp_use, mcp_result]

        # Fall through to reconstruction if not in cache
        if content.tool_type == "web_search":
            # we might be parsing an openai web search result so defend ourselves accordingly
            # note that if this is a native anthropic web_search or web_fetch it will have
            # been handled by replaying its recorded server tool span. therefore, this is
            # a web_search from another system which we need to normalize to the
            # anthropic schema
            if result_cleared:
                result_content: WebSearchToolResultBlockParamContentParam = (
                    WebSearchToolRequestErrorParam(
                        type="web_search_tool_result_error", error_code="unavailable"
                    )
                )
            else:
                try:
                    result_content = (
                        web_search_result_block_param_adapter.validate_json(
                            content.result
                        )
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
            # Handle cleared results gracefully
            mcp_result_content: str | Iterable[BetaTextBlockParam]
            if result_cleared:
                mcp_result_content = content.result
            else:
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
        elif content.tool_type == "code_execution":
            # if this is a native anthropic code execution it will have been handled
            # by replaying its recorded server tool span. therefore, this is a code
            # execution from another system which we need to normalize to the
            # anthropic schema (i.e. we can't just parse its arguments and result
            # or rely on its name to match one of our tools)
            return [
                BetaServerToolUseBlockParam(
                    type="server_tool_use",
                    id=content.id,
                    name="bash_code_execution",
                    input={"input": content.arguments},
                ),
                BetaBashCodeExecutionToolResultBlockParam(
                    type="bash_code_execution_tool_result",
                    tool_use_id=content.id,
                    content=BetaBashCodeExecutionResultBlockParam(
                        type="bash_code_execution_result",
                        return_code=0,
                        stdout=content.result,
                        stderr=content.error or "",
                        content=[],
                    ),
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

    elif isinstance(content, ContentData):
        compaction_param = _compaction_from_content_data(content)
        if compaction_param:
            return [compaction_param]
        fallback_param = _fallback_from_content_data(content)
        if fallback_param:
            return [fallback_param]
        raise RuntimeError(f"Unexpected data block: {content.data}")

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
        estimated_tokens = int(max(1, len(text) / 4))
        return estimated_tokens


def pad_tool_messages_for_token_counting(
    messages: list[MessageParam],
) -> list[MessageParam]:
    """Pad tool messages to satisfy Anthropic's API validation for token counting.

    Anthropic's count_tokens API validates message structure and requires:
    - Every tool_use block must have a corresponding tool_result in the next message
    - Every tool_result block must have a corresponding tool_use in the previous message

    When counting tokens for individual messages (e.g., for caching in compaction),
    we may have orphaned tool_use or tool_result blocks. This function pads with
    minimal fake paired items to satisfy API validation.

    This slightly overcounts tokens but that's acceptable for compaction triggering.
    """
    if not messages:
        return messages

    result: list[MessageParam] = []

    for i, msg in enumerate(messages):
        # Check for tool_result blocks without preceding tool_use
        if msg["role"] == "user":
            content = msg.get("content", [])
            if isinstance(content, list):
                tool_result_ids: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_result_ids.append(block.get("tool_use_id", ""))

                if tool_result_ids:
                    # Check if previous message has corresponding tool_use blocks
                    prev_tool_use_ids: set[str] = set()
                    if result and result[-1]["role"] == "assistant":
                        prev_content = result[-1].get("content", [])
                        if isinstance(prev_content, list):
                            for block in prev_content:
                                if (
                                    isinstance(block, dict)
                                    and block.get("type") == "tool_use"
                                ):
                                    prev_tool_use_ids.add(block.get("id", ""))

                    # Add fake assistant message with tool_use for orphaned results
                    orphaned_ids = [
                        tid for tid in tool_result_ids if tid not in prev_tool_use_ids
                    ]
                    if orphaned_ids:
                        fake_tool_uses = [
                            ToolUseBlockParam(
                                type="tool_use",
                                id=tid,
                                name="placeholder",
                                input={},
                            )
                            for tid in orphaned_ids
                        ]
                        result.append(
                            MessageParam(role="assistant", content=fake_tool_uses)
                        )

        result.append(msg)

        # Check for tool_use blocks without following tool_result
        if msg["role"] == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                tool_use_ids: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_use_ids.append(block.get("id", ""))

                if tool_use_ids:
                    # Check if next message has corresponding tool_result blocks
                    next_tool_result_ids: set[str] = set()
                    if i + 1 < len(messages) and messages[i + 1]["role"] == "user":
                        next_content = messages[i + 1].get("content", [])
                        if isinstance(next_content, list):
                            for block in next_content:
                                if (
                                    isinstance(block, dict)
                                    and block.get("type") == "tool_result"
                                ):
                                    next_tool_result_ids.add(
                                        block.get("tool_use_id", "")
                                    )

                    # Add fake user message with tool_result for orphaned uses
                    orphaned_ids = [
                        tid for tid in tool_use_ids if tid not in next_tool_result_ids
                    ]
                    if orphaned_ids:
                        fake_tool_results = [
                            ToolResultBlockParam(
                                type="tool_result",
                                tool_use_id=tid,
                                content="",
                            )
                            for tid in orphaned_ids
                        ]
                        result.append(
                            MessageParam(role="user", content=fake_tool_results)
                        )

    return result


def neutralize_thinking_for_token_counting(
    messages: list[MessageParam],
) -> list[MessageParam]:
    """Replace thinking/redacted_thinking blocks with text for token counting.

    Anthropic's count_tokens API validates thinking blocks the same way generate
    does, and a block whose signature is empty or altered is rejected several
    ways depending on its text: empty text + empty signature -> "each thinking
    block must contain thinking"; non-empty text + empty signature -> "Invalid
    signature in thinking block"; and any thinking/redacted_thinking block in the
    *latest* assistant message must match the original response's signature or it
    "cannot be modified". An empty signature is the common thread across the
    reported failures.

    None of these invariants hold here. Compaction counts message *subsets*, so
    an older assistant turn becomes the "latest" one and gets the strict signature
    check it escaped in generate; and those blocks may carry empty summary text
    (Claude 4.7+ default `display: "omitted"`) or be reconstructed on a fresh
    process where the verbatim-replay cache is empty (leaving an empty signature).
    For a token estimate we don't need valid signatures — replacing every thinking
    block with equivalent text keeps the approximate token weight while sidestepping
    all of these validations. Redacted blocks carry no readable text to substitute,
    so they're dropped.

    This can slightly undercount reasoning tokens (a summary is shorter than the
    reasoning it stands in for; a dropped redacted block counts as zero), which is
    acceptable: compaction calibrates against generate's real `usage.input_tokens`
    baseline and this priced count typically covers only the delta since that
    baseline, and the compaction threshold has iteration headroom.

    Mirrors `pad_tool_messages_for_token_counting`: a count-time-only fixup for
    Anthropic's message-structure validation.
    """
    result: list[MessageParam] = []
    for msg in messages:
        content = msg.get("content")
        if msg["role"] != "assistant" or not isinstance(content, list):
            result.append(msg)
            continue

        neutralized: list[Any] = []
        changed = False
        for block in content:
            block_type = block.get("type") if isinstance(block, dict) else None
            if block_type == "thinking":
                changed = True
                thinking = block.get("thinking") or ""
                if thinking:
                    neutralized.append(TextBlockParam(type="text", text=thinking))
            elif block_type == "redacted_thinking":
                changed = True
            else:
                neutralized.append(block)

        if not changed:
            result.append(msg)
            continue

        # never emit an empty assistant message (the API rejects it)
        if not neutralized:
            neutralized = [TextBlockParam(type="text", text=NO_CONTENT)]
        result.append(MessageParam(role="assistant", content=neutralized))

    return result


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
    return media_type in [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
    ]


def anthropic_extra_body_fields() -> list[str]:
    return ["metadata", "service_tier"]
