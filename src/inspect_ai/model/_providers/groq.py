import json
import os
from copy import copy
from functools import partial
from logging import getLogger
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterable,
    List,
    Literal,
    NamedTuple,
    Optional,
    cast,
)

from groq import (
    DEFAULT_TIMEOUT as GROQ_DEFAULT_TIMEOUT,
)
from groq import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    AsyncStream,
)
from groq.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionChunk,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)
from groq.types.chat.chat_completion import Choice as GroqChoice
from groq.types.chat.chat_completion_message import ChatCompletionMessage
from groq.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)
from groq.types.chat.chat_completion_message_tool_call import (
    Function as GroqToolCallFunction,
)
from groq.types.completion_usage import CompletionUsage
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai._util.constants import (
    BASE_64_DATA_REMOVED,
    DEFAULT_MAX_TOKENS,
)
from inspect_ai._util.content import Content, ContentReasoning, ContentText
from inspect_ai._util.http import (
    is_retryable_http_status,
    parse_retry_after_from_exception,
)
from inspect_ai._util.http_defaults import (
    DEFAULT_REQUEST_TIMEOUT,
    default_async_client,
    default_limits,
    default_timeout,
)
from inspect_ai._util.images import inline_media_data_uri
from inspect_ai._util.logger import warn_once
from inspect_ai.log._samples import set_active_model_event_call
from inspect_ai.model._reasoning import (
    clamp_reasoning_effort_to_low_medium_high,
    reasoning_to_think_tag,
)
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo
from inspect_ai.util._json import json_schema_dump

from .._call_tools import parse_tool_call
from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI, RetryDecision
from .._model_call import ModelCall, as_error_response
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    as_stop_reason,
    collect_stop_details,
)
from .._openai import (
    classify_error_body,
    http_status_from_error_code,
    openai_stop_details,
)
from .._stream import (
    StreamReasoningEvent,
    StreamTextEvent,
    StreamToolCallEvent,
    model_stream_requested,
    report_model_stream_delta,
    report_model_stream_progress,
    report_model_stream_start,
)
from .util import (
    environment_prerequisite_error,
    model_base_url,
    normalize_stream_arg,
)
from .util.hooks import HttpxHooks

logger = getLogger(__name__)

GROQ_API_KEY = "GROQ_API_KEY"


class GroqStreamError(Exception):
    """The server stopped a chat-completions stream early (`x_groq.error`).

    Classified as transient by `should_retry`: the canonical instance
    ("over capacity") is the same condition a non-streamed request surfaces
    as a retryable 429/503, and auto-streaming enabled by a display-only
    `on_stream` callback must not turn a retried condition into a
    permanently failed sample.
    """


class GroqErrorInfo(NamedTuple):
    """The `message`/`type`/`code` fields of a Groq error body."""

    message: str
    type: str | None
    code: str | int | None


def groq_error_info(ex: APIError) -> GroqErrorInfo:
    """Read the error fields from a Groq SDK exception.

    A status error's body is the full response payload (`{"error": {...}}`).
    An error payload delivered in the stream body (HTTP 200 already sent) is
    raised by the SDK as a plain `APIError` whose body is the inner error
    object itself, or a bare string when the payload's `error` was not an
    object. Unlike the OpenAI SDK, `groq.APIError` exposes no `code`/`type`
    attributes, so both shapes are read here.
    """
    error: object = ex.body
    if isinstance(error, dict) and isinstance(error.get("error"), dict):
        error = error["error"]
    if isinstance(error, str) and error:
        # a bare string payload is the message itself (the SDK's own message
        # for this shape is a generic placeholder)
        return GroqErrorInfo(message=error, type=None, code=None)
    if not isinstance(error, dict):
        return GroqErrorInfo(message=ex.message, type=None, code=None)
    message = error.get("message")
    error_type = error.get("type")
    code = error.get("code")
    return GroqErrorInfo(
        message=str(message) if message is not None else ex.message,
        type=str(error_type) if error_type is not None else None,
        code=code if isinstance(code, str | int) else None,
    )


GROQ_TRANSIENT_ERROR_NAMES = frozenset({"serviceunavailable", "overcapacity"})
"""Groq's own transient `type`/`code` spellings (normalized for `classify_error_body`)."""


def groq_classify_stream_error(ex: APIError) -> RetryDecision:
    """Classify an error payload delivered mid-stream (a plain `APIError`).

    The SDK raises it without a status code, so the body is read instead: the
    shared `code`/`type` rules (`classify_error_body`) extended with Groq's
    own spellings, then the message for the "over capacity" condition (see
    `GroqStreamError` for why that must retry). A numeric HTTP status in
    `code` is authoritative: when it is non-retryable (400/404/413/...) the
    message is not consulted. Anything unrecognized stays unretried.
    """
    info = groq_error_info(ex)
    decision = classify_error_body(info.code, info.type, GROQ_TRANSIENT_ERROR_NAMES)
    if decision is not None:
        return decision
    if (
        http_status_from_error_code(info.code) is None
        and "over capacity" in info.message.lower()
    ):
        return RetryDecision.transient()
    return RetryDecision.no()


class GroqAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        config: GenerateConfig = GenerateConfig(),
        streaming: bool | Literal["auto"] = "auto",
        **model_args: Any,
    ):
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[GROQ_API_KEY],
            config=config,
        )

        # record streaming preference (unset/"auto" streams when the caller
        # passes on_stream to generate; an explicit True/False overrides)
        self.streaming: bool | None = normalize_stream_arg(streaming, "streaming")

        if not self.api_key:
            self.api_key = os.environ.get(GROQ_API_KEY)
        if not self.api_key:
            raise environment_prerequisite_error("Groq", GROQ_API_KEY)

        self.model_args = model_args
        self.initialize()

    def _create_client(self) -> AsyncGroq:
        model_args = dict(self.model_args)
        if "http_client" not in model_args:
            # Raise the connect deadline but keep the SDK's tighter request
            # budget and this provider's uncapped pool, unless an operator
            # overrides them. The SDK's read, write and pool deadlines are one
            # shared value.
            timeout = default_timeout(
                request_timeout=GROQ_DEFAULT_TIMEOUT.read or DEFAULT_REQUEST_TIMEOUT
            )
            model_args.setdefault("timeout", timeout)
            model_args["http_client"] = default_async_client(
                timeout=timeout, limits=default_limits(max_connections=None)
            )
        return AsyncGroq(
            api_key=self.api_key,
            base_url=model_base_url(self.base_url, "GROQ_BASE_URL"),
            **model_args,
        )

    def initialize(self) -> None:
        super().initialize()
        self.client = self._create_client()
        self._http_hooks = HttpxHooks(self.client._client, api=self)

    @override
    async def aclose(self) -> None:
        await self.client.close()

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput | Exception, ModelCall]:
        # allocate request_id (so we can see it from ModelCall)
        request_id = self._http_hooks.start_request()

        messages = await as_groq_chat_messages(input)

        params = self.completion_params(config)
        if tools:
            params["tools"] = chat_tools(tools)
            params["tool_choice"] = (
                chat_tool_choice(tool_choice) if tool_choice else "auto"
            )
            if config.parallel_tool_calls is not None:
                params["parallel_tool_calls"] = config.parallel_tool_calls

        # resolve streaming and mutate the request accordingly before the
        # ModelCall snapshot, so the logged request matches the wire request
        streaming = self.resolve_streaming(config)
        request = dict(
            messages=messages,
            model=self.model_name,
            extra_headers={HttpxHooks.REQUEST_ID_HEADER: request_id}
            | (config.extra_headers or {}),
            **params,
        )
        if streaming:
            request["stream"] = True

        model_call = set_active_model_event_call(
            request=request,
            filter=model_call_filter,
        )

        try:
            if streaming:
                async with cast(
                    AsyncStream[ChatCompletionChunk],
                    await self.client.chat.completions.create(**request),
                ) as chunk_stream:
                    completion = await groq_completion_from_stream(chunk_stream)
            else:
                completion = cast(
                    ChatCompletion,
                    await self.client.chat.completions.create(**request),
                )

            model_call.set_response(
                completion.model_dump(), self._http_hooks.end_request(request_id)
            )

            # a streamed response should carry usage on its final chunk —
            # warn rather than under-count silently if it does not
            if streaming and completion.usage is None:
                warn_once(
                    logger,
                    f"groq model '{self.model_name}' reported no token usage "
                    "for a streamed response; pass -M streaming=false if you "
                    "require usage reporting.",
                )

            # extract metadata
            metadata: dict[str, Any] = {
                "id": completion.id,
                "system_fingerprint": completion.system_fingerprint,
                "created": completion.created,
            }
            if completion.usage:
                metadata = metadata | {
                    "queue_time": completion.usage.queue_time,
                    "prompt_time": completion.usage.prompt_time,
                    "completion_time": completion.usage.completion_time,
                    "total_time": completion.usage.total_time,
                }
            if completion.choices[0].message.executed_tools:
                metadata["executed_tools"] = [
                    tool.model_dump()
                    for tool in completion.choices[0].message.executed_tools
                ]

            # extract output
            choices = self._chat_choices_from_response(completion, tools)
            output = ModelOutput(
                model=completion.model,
                choices=choices,
                usage=(
                    ModelUsage(
                        input_tokens=completion.usage.prompt_tokens,
                        output_tokens=completion.usage.completion_tokens,
                        total_tokens=completion.usage.total_tokens,
                    )
                    if completion.usage
                    else None
                ),
                metadata=metadata,
            )

            # return
            return output, model_call
        except APIStatusError as ex:
            model_call.set_error(
                as_error_response(ex.body), self._http_hooks.end_request(request_id)
            )
            return self.handle_bad_request(ex), model_call
        except APIError as ex:
            # an error payload delivered in the stream body (HTTP 200 already
            # sent) arrives as a plain APIError: convert a recognized
            # bad-request condition, otherwise re-raise so should_retry can
            # classify it; connection/validation errors keep their own semantics
            model_call.set_error(
                as_error_response(ex.body), self._http_hooks.end_request(request_id)
            )
            if isinstance(ex, APIConnectionError | APIResponseValidationError):
                raise
            converted = self.handle_bad_request(ex)
            if not isinstance(converted, ModelOutput):
                raise
            return converted, model_call

    def completion_params(self, config: GenerateConfig) -> Dict[str, Any]:
        params: dict[str, Any] = {}
        if config.temperature is not None:
            params["temperature"] = config.temperature
        if config.max_tokens is not None:
            params["max_tokens"] = config.max_tokens
        if config.top_p is not None:
            params["top_p"] = config.top_p
        if config.stop_seqs:
            params["stop"] = config.stop_seqs
        if config.presence_penalty is not None:
            params["presence_penalty"] = config.presence_penalty
        if config.frequency_penalty is not None:
            params["frequency_penalty"] = config.frequency_penalty
        if config.seed is not None:
            params["seed"] = config.seed
        if config.num_choices is not None:
            params["n"] = config.num_choices
        if config.reasoning_effort is not None:
            # Groq's API accepts low/medium/high; clamp the extended effort
            # values (minimal/xhigh/max) so requests aren't rejected.
            clamped = clamp_reasoning_effort_to_low_medium_high(config.reasoning_effort)
            if clamped is not None:
                params["reasoning_effort"] = clamped
        if config.response_schema is not None:
            json_schema_dict: dict[str, Any] = dict(
                name=config.response_schema.name,
                schema=json_schema_dump(config.response_schema.json_schema),
            )
            if config.response_schema.description is not None:
                json_schema_dict["description"] = config.response_schema.description
            if config.response_schema.strict is not None:
                json_schema_dict["strict"] = config.response_schema.strict
            params["response_format"] = dict(
                type="json_schema", json_schema=json_schema_dict
            )
        return params

    def resolve_streaming(self, config: GenerateConfig) -> bool:
        """Whether to use the streaming API for this generate call.

        An explicit `streaming` model arg wins; when unset ("auto"), stream
        when the caller passed `on_stream` to `Model.generate()`. A
        display-only `on_stream` request must not risk degrading results, so
        auto mode declines requests the stream accumulator is (or may be)
        lossy for — those carrying a `response_schema` (structured output
        under streaming is unverified for Groq) and compound models (which
        execute tools server-side and report them via `executed_tools`,
        not carried by the accumulator). An explicit `streaming=true` opt-in
        still streams. There is no non-streamed retry when the server
        rejects a streamed request (see the note on
        `OpenAICompatibleAPI.resolve_stream`); `-M streaming=false` opts out.
        """
        if self.streaming is not None:
            return self.streaming
        return (
            model_stream_requested()
            and config.response_schema is None
            and "compound" not in self.model_name.lower()
        )

    def _chat_choices_from_response(
        self, response: Any, tools: list[ToolInfo]
    ) -> List[ChatCompletionChoice]:
        choices = list(response.choices)
        choices.sort(key=lambda c: c.index)
        return [
            ChatCompletionChoice(
                message=chat_message_assistant(self.model_name, choice.message, tools),
                stop_reason=as_stop_reason(choice.finish_reason),
                stop_details=collect_stop_details(
                    "groq", logger, partial(openai_stop_details, choice)
                ),
            )
            for choice in choices
        ]

    @override
    def should_retry(self, ex: Exception) -> bool | RetryDecision:
        if isinstance(ex, APIStatusError):
            if not is_retryable_http_status(ex.status_code):
                return RetryDecision.no()
            retry_after = parse_retry_after_from_exception(ex)
            if ex.status_code == 429:
                return RetryDecision.rate_limit(retry_after=retry_after)
            return RetryDecision.transient(retry_after=retry_after)
        if isinstance(ex, APITimeoutError):
            return RetryDecision.transient()
        if isinstance(ex, GroqStreamError):
            return RetryDecision.transient()
        if isinstance(ex, APIError) and not isinstance(
            ex, APIConnectionError | APIResponseValidationError
        ):
            return groq_classify_stream_error(ex)
        return RetryDecision.no()

    @override
    def connection_key(self) -> str:
        """Scope adaptive concurrency per (key, model).

        A pool shared across models lets the faster model's signals push the
        adaptive limit past the slower model's actual ceiling (cram-down).
        Per-model scoping avoids that, at the cost of slight over-fragmentation
        when models actually share an upstream rate-limit budget.
        """
        return f"{self.initial_api_key}:{self.model_name}"

    @override
    def is_auth_failure(self, ex: Exception) -> bool:
        if isinstance(ex, APIStatusError):
            return ex.status_code == 401
        return False

    @override
    def collapse_user_messages(self) -> bool:
        return False

    @override
    def collapse_assistant_messages(self) -> bool:
        return False

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        Groq model names don't map directly to HuggingFace format.
        Return the raw model name and rely on fuzzy matching in get_model_info().
        """
        return self.model_name

    @override
    def max_tokens(self) -> Optional[int]:
        return DEFAULT_MAX_TOKENS

    def handle_bad_request(self, ex: APIError) -> ModelOutput | Exception:
        """Convert a context-length rejection into `model_length` output.

        Accepts the `APIError` base: a status error is only checked when it
        is a 400, and an error payload delivered mid-stream (a plain
        `APIError` with no status, see `groq_error_info`) is checked the same
        way since the SDK could not infer a `BadRequestError` for it. Returns
        the exception unchanged when it is not a recognized rejection.
        """
        if isinstance(ex, APIStatusError) and ex.status_code != 400:
            return ex
        info = groq_error_info(ex)
        if (
            info.code == "context_length_exceeded"
            or "reduce the length" in info.message
        ):
            return ModelOutput.from_content(
                model=self.model_name,
                content=info.message,
                stop_reason="model_length",
            )
        return ex


class _StreamToolCall(NamedTuple):
    """Accumulated state for one streamed tool call."""

    id: str | None
    function: str | None
    arguments: list[str]


class _StreamChoice:
    """Accumulated state for one streamed choice."""

    def __init__(self) -> None:
        self.content: list[str] = []
        self.reasoning: list[str] = []
        self.tool_calls: dict[int, _StreamToolCall] = {}
        self.finish_reason: str | None = None


async def groq_completion_from_stream(
    stream: AsyncIterator[ChatCompletionChunk],
) -> ChatCompletion:
    """Consume a Groq chat-completions chunk stream into a final completion.

    Reports each chunk once to the model layer's stream observer
    (`inspect_ai.model._stream`), which fans out to the caller's `on_stream`
    callback and the pending event's progress record. Accumulates all
    choices, but reports content deltas from the first choice only —
    interleaving multiple choices' fragments into the single delta stream
    would corrupt accumulating consumers.

    Usage arrives on the final chunk (under `x_groq` and/or the chunk-level
    `usage` field), carrying the same timing metadata (queue/prompt/completion
    time) as a non-streamed response. A chunk carrying `x_groq.error` (the
    server stopped the stream early) raises `GroqStreamError` (retried as
    transient) rather than returning a truncated completion. Content deltas
    are gated on `model_stream_requested()` (see `report_model_stream_delta`);
    the usage/heartbeat progress channel runs regardless.
    """
    report_model_stream_start()
    completion_id: str | None = None
    created: int | None = None
    model: str | None = None
    system_fingerprint: str | None = None
    usage: CompletionUsage | None = None
    choices: dict[int, _StreamChoice] = {}

    async for chunk in stream:
        completion_id = completion_id or chunk.id
        created = created if created is not None else chunk.created
        model = model or chunk.model
        system_fingerprint = system_fingerprint or chunk.system_fingerprint
        # the SDK raises only for top-level `error` payloads (as a plain
        # APIError, classified by GroqAPI.should_retry); a chunk-level
        # x_groq.error means the server stopped the stream early — fail rather
        # than return a silently truncated completion
        if chunk.x_groq is not None and chunk.x_groq.error:
            raise GroqStreamError(
                f"Streaming response stopped early: {chunk.x_groq.error}"
            )
        chunk_usage = chunk.usage or (chunk.x_groq.usage if chunk.x_groq else None)
        if chunk_usage is not None:
            usage = chunk_usage
            report_model_stream_progress(chunk_usage.completion_tokens)

        # report deltas from the first choice only, and only when an
        # on_stream consumer is present (see report_model_stream_delta) —
        # accumulation into the completion always runs
        deltas_requested = model_stream_requested()
        reported = False
        for chunk_choice in chunk.choices:
            choice = choices.setdefault(chunk_choice.index, _StreamChoice())
            if chunk_choice.finish_reason is not None:
                choice.finish_reason = chunk_choice.finish_reason
            delta = chunk_choice.delta
            if delta is None:
                continue
            report = chunk_choice.index == 0 and deltas_requested
            if delta.reasoning:
                choice.reasoning.append(delta.reasoning)
                if report:
                    await report_model_stream_delta(
                        StreamReasoningEvent(reasoning=delta.reasoning)
                    )
                    reported = True
            if delta.content:
                choice.content.append(delta.content)
                if report:
                    await report_model_stream_delta(StreamTextEvent(text=delta.content))
                    reported = True
            for tool_call in delta.tool_calls or []:
                function = tool_call.function
                arguments = (function.arguments if function is not None else None) or ""
                # id/function arrive only on a call's first fragment; remember
                # them by index so continuation fragments are attributed
                info = choice.tool_calls.get(
                    tool_call.index, _StreamToolCall(None, None, [])
                )
                info = _StreamToolCall(
                    id=tool_call.id or info.id,
                    function=(function.name if function is not None else None)
                    or info.function,
                    arguments=info.arguments,
                )
                if arguments:
                    info.arguments.append(arguments)
                choice.tool_calls[tool_call.index] = info
                if report:
                    await report_model_stream_delta(
                        StreamToolCallEvent(
                            id=info.id, function=info.function, arguments=arguments
                        )
                    )
                    reported = True
        if not reported and chunk_usage is None:
            report_model_stream_progress()

    if completion_id is None or model is None:
        raise RuntimeError("Streaming response ended without delivering any chunks.")
    if not choices:
        raise RuntimeError("Streaming response ended without delivering any choices.")

    return ChatCompletion(
        id=completion_id,
        created=created or 0,
        model=model,
        object="chat.completion",
        system_fingerprint=system_fingerprint,
        usage=usage,
        choices=[
            # model_construct: chunk finish reasons include values (e.g.
            # "content_filter") that the non-streaming Choice literal omits;
            # validation would reject them where passthrough keeps the stop
            # reason mapping intact
            GroqChoice.model_construct(
                index=index,
                finish_reason=cast(Any, choice.finish_reason),
                logprobs=None,
                message=ChatCompletionMessage(
                    role="assistant",
                    content="".join(choice.content) if choice.content else None,
                    reasoning="".join(choice.reasoning) if choice.reasoning else None,
                    tool_calls=[
                        ChatCompletionMessageToolCall(
                            id=tool_call.id or f"tool_call_{index}_{call_index}",
                            type="function",
                            function=GroqToolCallFunction(
                                name=tool_call.function or "",
                                arguments="".join(tool_call.arguments),
                            ),
                        )
                        for call_index, tool_call in sorted(choice.tool_calls.items())
                    ]
                    or None,
                ),
            )
            for index, choice in sorted(choices.items())
        ],
    )


async def as_groq_chat_messages(
    messages: list[ChatMessage],
) -> list[ChatCompletionMessageParam]:
    return [await groq_chat_message(message) for message in messages]


async def groq_chat_message(message: ChatMessage) -> ChatCompletionMessageParam:
    if isinstance(message, ChatMessageSystem):
        return ChatCompletionSystemMessageParam(role="system", content=message.text)

    elif isinstance(message, ChatMessageUser):
        content: str | Iterable[ChatCompletionContentPartParam] = (
            message.content
            if isinstance(message.content, str)
            else [await as_chat_completion_part(content) for content in message.content]
        )
        return ChatCompletionUserMessageParam(role="user", content=content)

    elif isinstance(message, ChatMessageAssistant):
        # emulate reasoning
        if isinstance(message.content, list):
            content = "\n".join(
                [
                    c.text if isinstance(c, ContentText) else reasoning_to_think_tag(c)
                    for c in message.content
                    if isinstance(c, ContentText | ContentReasoning)
                ]
            )
        else:
            content = message.content

        return ChatCompletionAssistantMessageParam(
            role="assistant",
            content=content,
            tool_calls=[
                ChatCompletionMessageToolCallParam(
                    id=call.id,
                    type="function",
                    function={
                        "name": call.function,
                        "arguments": json.dumps(call.arguments),
                    },
                )
                for call in (message.tool_calls or [])
            ],
        )
    elif isinstance(message, ChatMessageTool):
        return ChatCompletionToolMessageParam(
            role="tool",
            content=message.text,
            tool_call_id=str(message.tool_call_id),
        )


async def as_chat_completion_part(
    content: Content,
) -> ChatCompletionContentPartParam:
    if content.type == "text":
        return ChatCompletionContentPartTextParam(type="text", text=content.text)
    elif content.type == "image":
        image_url = inline_media_data_uri(content.image, "image")
        detail = content.detail

        return ChatCompletionContentPartImageParam(
            type="image_url",
            image_url=dict(
                url=image_url, detail="high" if detail == "original" else detail
            ),
        )
    else:
        raise RuntimeError("Groq models do not support audio or video inputs.")


def chat_tools(tools: List[ToolInfo]) -> List[Dict[str, Any]]:
    return [{"type": "function", "function": json_schema_dump(tool)} for tool in tools]


def chat_tool_choice(tool_choice: ToolChoice) -> str | Dict[str, Any]:
    if isinstance(tool_choice, ToolFunction):
        return {"type": "function", "function": {"name": tool_choice.name}}
    elif tool_choice == "any":
        return "required"
    else:
        return tool_choice


def chat_tool_calls(message: Any, tools: list[ToolInfo]) -> Optional[List[ToolCall]]:
    if hasattr(message, "tool_calls") and message.tool_calls:
        return [
            parse_tool_call(call.id, call.function.name, call.function.arguments, tools)
            for call in message.tool_calls
        ]
    return None


def chat_message_assistant(
    model: str, message: Any, tools: list[ToolInfo]
) -> ChatMessageAssistant:
    reasoning = getattr(message, "reasoning", None)
    if reasoning is not None:
        content: str | list[Content] = [
            ContentReasoning(reasoning=str(reasoning)),
            ContentText(text=message.content or ""),
        ]
    else:
        content = message.content or ""

    return ChatMessageAssistant(
        content=content,
        model=model,
        source="generate",
        tool_calls=chat_tool_calls(message, tools),
    )


def model_call_filter(key: JsonValue | None, value: JsonValue) -> JsonValue:
    # remove base64 encoded images
    if key == "image_url" and isinstance(value, dict):
        value = copy(value)
        value.update(url=BASE_64_DATA_REMOVED)
    return value
