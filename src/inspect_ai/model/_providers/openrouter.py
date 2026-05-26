import json
from collections.abc import Mapping
from logging import getLogger
from typing import Any, cast

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
)
from pydantic import JsonValue
from typing_extensions import NotRequired, TypedDict, override

from inspect_ai._util.content import ContentReasoning
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai.model import _openrouter_reasoning
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model import RetryDecision
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
from inspect_ai.model._openai import (
    CompletionsReasoningContent,
    OpenAIResponseError,
    chat_choices_from_openai,
    openai_chat_message,
)
from inspect_ai.model._reasoning import (
    reasoning_to_think_tag,
)
from inspect_ai.tool import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI

OPENROUTER_API_KEY = "OPENROUTER_API_KEY"
OPENROUTER_APP_ATTRIBUTION_HEADERS = {
    "HTTP-Referer": "https://inspect.aisi.org.uk/",
    "X-OpenRouter-Title": "Inspect AI",
}

logger = getLogger(__name__)

OPENROUTER_REASONING_DETAILS_SIGNATURE = (
    _openrouter_reasoning.OPENROUTER_REASONING_DETAILS_SIGNATURE
)
openrouter_reasoning_details_to_reasoning = (
    _openrouter_reasoning.openrouter_reasoning_details_to_reasoning
)
reasoning_to_openrouter_reasoning_details = (
    _openrouter_reasoning.reasoning_to_openrouter_reasoning_details
)


class ErrorResponse(TypedDict):
    code: int
    message: str
    metadata: NotRequired[dict[str, Any]]


class OpenRouterError(Exception):
    def __init__(self, response: ErrorResponse) -> None:
        self.response = response

    @property
    def message(self) -> str:
        return f"Error {self.response['code']} - {self.response['message']}"

    def __str__(self) -> str:
        return (
            self.message + ("\n" + json.dumps(self.response["metadata"], indent=2))
            if "metadata" in self.response
            else ""
        )


def _apply_app_attribution_headers(model_args: dict[str, Any]) -> None:
    default_headers = model_args.get("default_headers")
    if default_headers is None:
        model_args["default_headers"] = OPENROUTER_APP_ATTRIBUTION_HEADERS.copy()
        return

    if not isinstance(default_headers, Mapping):
        raise PrerequisiteError("default_headers must be a mapping")

    merged_headers = OPENROUTER_APP_ATTRIBUTION_HEADERS | dict(default_headers)
    if "X-Title" in default_headers and "X-OpenRouter-Title" not in default_headers:
        merged_headers.pop("X-OpenRouter-Title", None)
    model_args["default_headers"] = merged_headers


class OpenRouterAPI(OpenAICompatibleAPI):
    """OpenAI-compatible client for the OpenRouter inference router.

    For `openrouter/anthropic/*` models, Anthropic prompt caching is enabled
    by default: this provider inserts per-block `cache_control: {"type":
    "ephemeral"}` markers on the last system block, the last tool definition,
    and a rolling pair of message-level breakpoints (mirroring the placement
    used by the direct Anthropic provider). The markers are accepted by
    OpenRouter across Anthropic-direct, Bedrock, and Vertex routing. Set
    `cache_prompt=False` in `GenerateConfig` to disable. Cache writes returned
    by the upstream provider are surfaced as `ModelUsage.input_tokens_cache_write`.
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        emulate_tools: bool = False,
        **model_args: Any,
    ) -> None:
        # collect known model args that we forward to generate
        def collect_model_arg(name: str) -> Any | None:
            nonlocal model_args
            value = model_args.get(name, None)
            if value is not None:
                model_args.pop(name)
            return value

        # models arg
        self.models = collect_model_arg("models")
        if self.models is not None:
            if not isinstance(self.models, list):
                raise PrerequisiteError("models must be a list of strings")

        # providers arg
        self.provider = collect_model_arg("provider")
        if self.provider is not None:
            if not isinstance(self.provider, dict):
                raise PrerequisiteError("provider must be a dict")

        # transforms arg
        self.transforms = collect_model_arg("transforms")
        if self.transforms is not None:
            if not isinstance(self.transforms, list):
                raise PrerequisiteError("transforms must be a list of strings")

        self.reasoning_enabled = collect_model_arg("reasoning_enabled")
        if self.reasoning_enabled is not None:
            if not isinstance(self.reasoning_enabled, bool):
                raise PrerequisiteError("reasoning_enabled must be a boolean")

        self.app_attribution = collect_model_arg("app_attribution")
        if self.app_attribution is None:
            self.app_attribution = True
        if not isinstance(self.app_attribution, bool):
            raise PrerequisiteError("app_attribution must be a boolean")
        if self.app_attribution:
            _apply_app_attribution_headers(model_args)

        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="OpenRouter",
            service_base_url="https://openrouter.ai/api/v1",
            emulate_tools=emulate_tools,
            **model_args,
        )

    @override
    def collapse_system_messages(self) -> bool:
        # Several OpenRouter inference providers (e.g. AkashML, Parasail)
        # reject requests that contain more than one system message or any
        # system message at a non-zero index, even though the OpenAI Chat
        # Completions API itself is permissive. Coalesce adjacent system
        # messages so the canonical request has a single leading system
        # message regardless of which provider OpenRouter selects.
        return True

    @override
    def should_retry(self, ex: BaseException) -> bool | RetryDecision:
        # Defer to the OpenAI-compatible base classifier (which handles 429 →
        # rate_limit and 5xx/timeouts → transient with header extraction).
        # OpenRouter additionally surfaces malformed-JSON responses; treat
        # those as transient (parsing flake, not a quota issue).
        decision = super().should_retry(ex)
        if isinstance(decision, RetryDecision):
            if decision.retry:
                return decision
        elif decision:
            return RetryDecision.transient()
        if isinstance(ex, json.JSONDecodeError):
            return RetryDecision.transient()
        return RetryDecision.no()

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        OpenRouter model names may include provider prefixes like
        'together/meta-llama/Llama-3.1-8B'. For inference providers (together,
        fireworks, etc.), the prefix is stripped. For first-party providers
        (anthropic, openai, etc.), the full name is preserved.

        OpenRouter also supports suffixes like :free, :extended, :nitro,
        :thinking, :online which are stripped for database lookup.
        """
        from ._first_party import FIRST_PARTY_PROVIDERS

        name = self.service_model_name()

        # Strip OpenRouter suffixes (:free, :extended, :nitro, :thinking, :online)
        if ":" in name:
            name = name.split(":")[0]

        parts = name.split("/")
        if len(parts) >= 2:
            first_part = parts[0].lower()
            # If first part is a known first-party provider, keep the full name
            if first_part in FIRST_PARTY_PROVIDERS:
                return name
            # Otherwise strip the inference provider prefix (e.g., together/)
            if len(parts) >= 3:
                return "/".join(parts[1:])
        return name

    @override
    def chat_choices_from_completion(
        self, completion: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        # extract reasoning details
        def extract_reasoning_details(
            content: CompletionsReasoningContent,
        ) -> ContentReasoning | None:
            if content.source == "reasoning_details":
                if isinstance(content.reasoning, list):
                    return openrouter_reasoning_details_to_reasoning(
                        cast(list[dict[str, Any]], content.reasoning)
                    )
                else:
                    logger.warning(
                        f"Unexpected type for openrouter reasoning details: f{type(content.reasoning)}"
                    )
                    return None
            else:
                return None

        return chat_choices_from_openai(completion, tools, extract_reasoning_details)

    @override
    async def messages_to_openai(
        self, input: list[ChatMessage]
    ) -> list[ChatCompletionMessageParam]:
        # For Gemini-family models, do not replay stored reasoning_details
        # back to OpenRouter. Gemini's openai-compat translation produces
        # reasoning_details whose `id` field is missing or stale relative to
        # the new tool_calls[].id on sequential function-call retries; the
        # upstream Gemini provider then rejects with HTTP 200 + body
        # {code:400, message:"Provider returned error"} (raw upstream error:
        # "function call ... missing a thought_signature"). Falling through
        # to the `<think>` tag path keeps assistant CoT visible to the model
        # without triggering signature validation. Non-Gemini providers
        # (Anthropic / Grok / OpenAI reasoning models) retain reasoning
        # replay since they require it for correct CoT continuation.
        _strip_reasoning_details = "gemini" in self.model_name.lower()

        # convert reasoning_details to an extra body parameter
        def handle_reasoning_details(
            content: ContentReasoning,
        ) -> dict[str, JsonValue] | str:
            if _strip_reasoning_details:
                return reasoning_to_think_tag(content)
            details = reasoning_to_openrouter_reasoning_details(content)
            if details is not None:
                return details
            else:
                return reasoning_to_think_tag(content)

        return [
            await openai_chat_message(message, "system", handle_reasoning_details)
            for message in input
        ]

    @override
    def on_response(self, response: dict[str, Any]) -> None:
        """Handle documented OpenRouter error conditions.

        https://openrouter.ai/docs/api-reference/errors
        """
        # check if open-router yielded an error (raise explicit
        # OpenAIResponseError for cases where we should retry)
        error: ErrorResponse | None = response.get("error", None)
        if error is not None:
            if error["code"] == 429:
                raise OpenAIResponseError("rate_limit_exceeded", error["message"])
            elif error["code"] in [408, 500, 502, 504]:
                raise OpenAIResponseError("server_error", error["message"])
            else:
                raise OpenRouterError(error)

        # check for an empty response (which they document can occur on
        # startup). for this we'll return a "server_error" which will
        # trigger a retry w/ exponential backoff
        elif response.get("choices", None) is None:
            raise OpenAIResponseError(
                "server_error",
                "Model is warming up, please retry again after waiting for warmup.",
            )

    @override
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # Delegate to the OpenAI-compatible base and post-process usage to
        # surface Anthropic-style cache_creation_input_tokens (which OpenRouter
        # passes through for Anthropic-routed models but the base does not parse).
        result = await super().generate(input, tools, tool_choice, config)
        if isinstance(result, tuple):
            output, call = result
            if isinstance(output, ModelOutput):
                _apply_cache_creation_usage(output, call)
        return result

    @override
    async def _generate_completion(
        self, request: dict[str, Any], config: GenerateConfig
    ) -> ChatCompletion:
        # Inject Anthropic per-block cache_control markers when routing to
        # an anthropic/* model. OpenRouter forwards these markers to all
        # Anthropic-compatible backends (Anthropic-direct, Bedrock, Vertex).
        if self._cache_prompt_enabled(config):
            _add_anthropic_cache_markers(request)
        return await super()._generate_completion(request, config)

    def _cache_prompt_enabled(self, config: GenerateConfig) -> bool:
        # service_model_name() does case-sensitive prefix-strip against
        # self.service ("OpenRouter"), so it does NOT remove the lowercase
        # "openrouter/" prefix from user-supplied model names. Strip manually.
        name = self.service_model_name().removeprefix("openrouter/")
        if not name.startswith("anthropic/"):
            return False
        # Matches direct anthropic provider: only explicit False disables;
        # None, True, and "auto" all enable.
        if config.cache_prompt is False:
            return False
        # Mirror the legacy-Claude gate from the direct anthropic provider.
        bare = name.split(":", 1)[0]
        if "claude-3-sonnet" in bare or "claude-2" in bare or "claude-instant" in bare:
            return False
        return True

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        # default params
        params = super().completion_params(config, tools)

        # remove reasoning_effort it is exists
        if "reasoning_effort" in params:
            del params["reasoning_effort"]

        # provide openrouter standard reasoning options
        # https://openrouter.ai/docs/use-cases/reasoning-tokens
        reasoning: dict[str, str | int] | None = None
        if (
            config.reasoning_effort is not None
            or config.reasoning_tokens is not None
            or self.reasoning_enabled is not None
        ):
            reasoning = dict()
            # openrouter supports one of max_tokens or effort, prefer effort.
            # OpenRouter accepts minimal/low/medium/high/xhigh (per
            # https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
            # but not `max`; map it to `xhigh` (their highest tier, ratio 0.95).
            if config.reasoning_effort is not None:
                effort: str = config.reasoning_effort
                if effort == "max":
                    effort = "xhigh"
                reasoning["effort"] = effort
                if config.reasoning_tokens is not None:
                    warn_once(
                        logger,
                        "You can only specify `reasoning_effort` or `reasoning_tokens`, not both. Ignoring `reasoning_tokens`.",
                    )
            elif config.reasoning_tokens is not None:
                reasoning["max_tokens"] = config.reasoning_tokens
            if self.reasoning_enabled is not None:
                # enabled=false will disable reasoning on hybrid models
                reasoning["enabled"] = self.reasoning_enabled

        # pass args if specifed
        EXTRA_BODY = "extra_body"
        if self.models or self.provider or self.transforms or reasoning:
            params[EXTRA_BODY] = params.get(EXTRA_BODY, {})
            if self.models:
                params[EXTRA_BODY]["models"] = self.models
            if self.provider:
                params[EXTRA_BODY]["provider"] = self.provider
            if self.transforms:
                params[EXTRA_BODY]["transforms"] = self.transforms
            if reasoning:
                params[EXTRA_BODY]["reasoning"] = reasoning

        return params


def _ephemeral() -> dict[str, str]:
    return {"type": "ephemeral"}


def _add_anthropic_cache_markers(request: dict[str, Any]) -> None:
    """Insert Anthropic per-block cache_control markers in an OpenAI-format request.

    Mirrors the breakpoint placement used by inspect_ai's direct anthropic
    provider: last system block, last tool definition, and the penultimate
    content block of the last message (with fallback to the last block of the
    previous message when the last message has fewer than 2 blocks). Anthropic
    enforces a maximum of 4 cache_control breakpoints per request; this scheme
    uses at most 3.

    Note: the OpenAI-compatible base snapshots the ModelCall request before
    _generate_completion runs, so cache_control markers will NOT appear in the
    request as logged to ``.eval`` files even when they are sent on the wire.
    Verify caching via the returned usage line (CW/CR > 0) or the OpenRouter
    dashboard's Generation viewer, not the Inspect log.
    """
    messages = request.get("messages")
    if isinstance(messages, list) and messages:
        # mark the last system message's last content block (string-content
        # system messages are safe to convert to list form)
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "system":
                _mark_last_content_block(msg)
                break

        # mark a rolling pair of message-level breakpoints. auto-cache marks the
        # last block; this gives lookback a fallback when the final block changes.
        # In the fallback branch we deliberately do NOT convert string-content
        # to list form (mirroring anthropic.py:1208-1211): the previous message
        # may be a role:"tool" message whose string content must stay a string
        # for upstream tool_result translation.
        last = messages[-1]
        if isinstance(last, dict):
            last_content = last.get("content")
            if isinstance(last_content, list) and len(last_content) >= 2:
                last_content[-2]["cache_control"] = _ephemeral()
            elif len(messages) >= 2:
                prev = messages[-2]
                if isinstance(prev, dict):
                    prev_content = prev.get("content")
                    if isinstance(prev_content, list) and prev_content:
                        last_block = prev_content[-1]
                        if isinstance(last_block, dict):
                            last_block["cache_control"] = _ephemeral()

    # mark the last tool definition (cache_control at the top of the tool dict,
    # alongside "type": "function" — empirically verified against OpenRouter;
    # nesting inside tool["function"] is silently tokenized as schema content).
    tools = request.get("tools")
    if isinstance(tools, list) and tools:
        last_tool = tools[-1]
        if isinstance(last_tool, dict):
            last_tool["cache_control"] = _ephemeral()


def _mark_last_content_block(msg: dict[str, Any]) -> None:
    """Mark the last content block of a message with cache_control.

    If content is a plain string, convert to a single-block list so we can
    attach the marker. Only safe for system messages — see caller.
    """
    content = msg.get("content")
    if isinstance(content, list) and content:
        last_block = content[-1]
        if isinstance(last_block, dict):
            last_block["cache_control"] = _ephemeral()
    elif isinstance(content, str) and content:
        msg["content"] = [
            {"type": "text", "text": content, "cache_control": _ephemeral()}
        ]


def _apply_cache_creation_usage(output: ModelOutput, call: ModelCall | None) -> None:
    """Surface Anthropic's cache_creation_input_tokens in ModelUsage.

    OpenRouter passes this field through on the raw response usage object for
    Anthropic-routed models; the OpenAI-compatible base does not parse it.
    Mirrors the input_tokens accounting convention used by the base for cache
    reads: the count is subtracted from input_tokens so the usage line reads
    `input + cache_write + cache_read = total tokens charged this turn`.
    """
    if call is None or output.usage is None:
        return
    raw = call.response if isinstance(call.response, dict) else None
    usage = raw.get("usage") if raw else None
    if not isinstance(usage, dict):
        return
    # Prefer Anthropic-native key for future-proofing; fall back to the
    # OpenAI-extension shape that OpenRouter currently uses in practice.
    cw = usage.get("cache_creation_input_tokens")
    if not isinstance(cw, int) or cw <= 0:
        ptd = usage.get("prompt_tokens_details")
        cw = ptd.get("cache_write_tokens") if isinstance(ptd, dict) else None
    if not isinstance(cw, int) or cw <= 0:
        return
    # Guard against double-application (e.g. if a future base parses cache
    # writes natively): only set when the field hasn't been populated yet.
    if output.usage.input_tokens_cache_write is not None:
        return
    output.usage.input_tokens_cache_write = cw
    output.usage.input_tokens = max(0, output.usage.input_tokens - cw)
