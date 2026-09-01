import functools
import inspect
import json
import os
from logging import getLogger
from typing import Any, AsyncIterator, Literal, NamedTuple

from mistralai.client import Mistral
from mistralai.client.errors import SDKError
from mistralai.client.models import (
    AssistantMessage as MistralAssistantMessage,
)
from mistralai.client.models import (
    ChatCompletionChoice as MistralChatCompletionChoice,
)
from mistralai.client.models import (
    CompletionChunk,
    CompletionEvent,
    ContentChunk,
    DocumentURLChunk,
    FileChunk,
    FunctionCall,
    FunctionName,
    ImageURL,
    ImageURLChunk,
    ReferenceChunk,
    TextChunk,
    ThinkChunk,
    UsageInfo,
)
from mistralai.client.models import Function as MistralFunction
from mistralai.client.models import (
    JSONSchema as MistralJSONSchema,
)
from mistralai.client.models import (
    ResponseFormat as MistralResponseFormat,
)
from mistralai.client.models import SystemMessage as MistralSystemMessage
from mistralai.client.models import Tool as MistralTool
from mistralai.client.models import ToolCall as MistralToolCall
from mistralai.client.models import (
    ToolChoice as MistralToolChoice,
)
from mistralai.client.models import ToolMessage as MistralToolMessage
from mistralai.client.models import UserMessage as MistralUserMessage
from mistralai.client.models.chatcompletionresponse import (
    ChatCompletionResponse as MistralChatCompletionResponse,
)
from shortuuid import uuid
from typing_extensions import override

from inspect_ai._util.constants import NO_CONTENT
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.http import is_retryable_http_status
from inspect_ai._util.images import inline_media_data_uri, provider_image_data_uri
from inspect_ai._util.logger import warn_once
from inspect_ai.log._samples import set_active_model_event_call
from inspect_ai.model._reasoning import parse_content_with_reasoning
from inspect_ai.tool import ToolCall, ToolChoice, ToolFunction, ToolInfo
from inspect_ai.util._json import json_schema_dump

from ..._util.http_defaults import default_async_client
from ..._util.httpx import httpx_classify_retry
from .._call_tools import parse_tool_call
from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
)
from .._generate_config import GenerateConfig
from .._model import ModelAPI, RetryDecision
from .._model_call import ModelCall, as_error_response
from .._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
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
from .mistral_conversation import (
    mistral_conversation_generate,
    mistral_reasoning_effort,
)
from .util import (
    environment_prerequisite_error,
    model_base_url,
    normalize_stream_arg,
    require_azure_base_url,
    resolve_api_key,
    sample_cache_affinity_key,
)
from .util.hooks import HttpxHooks

logger = getLogger(__name__)

AZURE_MISTRAL_API_KEY = "AZURE_MISTRAL_API_KEY"
AZUREAI_MISTRAL_API_KEY = "AZUREAI_MISTRAL_API_KEY"
MISTRAL_API_KEY = "MISTRAL_API_KEY"


AZURE_MISTRAL_BASE_URL_VARS = ["AZUREAI_MISTRAL_BASE_URL", "AZURE_MISTRAL_BASE_URL"]


@functools.cache
def _sdk_supports_prompt_cache_key() -> bool:
    """Whether the installed mistralai SDK accepts `prompt_cache_key`.

    The parameter postdates our minimum supported version (2.0.1) and
    `complete_async` rejects unknown kwargs, so probe rather than pass blind.
    """
    from mistralai.client.chat import Chat

    return "prompt_cache_key" in inspect.signature(Chat.complete_async).parameters


class MistralAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        conversation_api: bool | None = None,
        streaming: bool | Literal["auto"] = "auto",
        **model_args: Any,
    ):
        # extract any service prefix from model name
        parts = model_name.split("/")
        if len(parts) > 1:
            self.service: str | None = parts[0]
        else:
            self.service = None

        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[
                MISTRAL_API_KEY,
                AZURE_MISTRAL_API_KEY,
                AZUREAI_MISTRAL_API_KEY,
            ],
            config=config,
        )

        # track use of conversation api
        if conversation_api is not None:
            self.conversation_api = conversation_api
        elif "voxtral" in self.model_family().lower():  # no audio in conversation api
            self.conversation_api = False
        else:
            self.conversation_api = True

        # record streaming preference (unset/"auto" streams when the caller
        # passes on_stream to generate; an explicit True/False overrides).
        # only the chat-completions path streams — see resolve_streaming
        self.streaming: bool | None = normalize_stream_arg(streaming, "streaming")

        # resolve api_key
        if not self.api_key:
            if self.is_azure():
                self.api_key = resolve_api_key(
                    [AZUREAI_MISTRAL_API_KEY, AZURE_MISTRAL_API_KEY]
                )
            else:
                self.api_key = os.environ.get(MISTRAL_API_KEY, None)

            if not self.api_key:
                raise environment_prerequisite_error(
                    "Mistral", [MISTRAL_API_KEY, AZUREAI_MISTRAL_API_KEY]
                )

        if not self.base_url:
            if self.is_azure():
                self.base_url = require_azure_base_url(
                    self.base_url, AZURE_MISTRAL_BASE_URL_VARS, "Mistral"
                )
            else:
                self.base_url = model_base_url(base_url, "MISTRAL_BASE_URL")

        if self.base_url:
            model_args["server_url"] = self.base_url

        self.model_args = model_args

    def is_azure(self) -> bool:
        return self.service == "azure"

    def _http_default_args(self) -> dict[str, Any]:
        """Model args with the shared HTTP defaults filled in.

        The SDK's own client applies a flat 5s to every phase, which is both a
        connect deadline a blocked loop outlasts and a request budget far too
        short for a generation.
        """
        model_args = dict(self.model_args)
        model_args.setdefault("async_client", default_async_client())
        return model_args

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        # create client
        with Mistral(api_key=self.api_key, **self._http_default_args()) as client:
            # create time tracker
            http_hooks = HttpxHooks(client.sdk_configuration.async_client, api=self)

            # use the conversation api if requested (this path does not yet
            # support streaming — an on_stream caller degrades gracefully to
            # no events; set conversation_api=false to stream)
            if self.conversation_api:
                if self.streaming is True:
                    warn_once(
                        logger,
                        f"mistral model '{self.model_name}': streaming=true has "
                        "no effect on the Conversation API (it does not support "
                        "streaming); pass -M conversation_api=false to stream.",
                    )
                return await mistral_conversation_generate(
                    client=client,
                    http_hooks=http_hooks,
                    model=self.service_model_name(),
                    input=input,
                    tools=tools,
                    tool_choice=tool_choice,
                    config=config,
                    handle_bad_request=self.handle_bad_request,
                )

            # build request
            request_id = http_hooks.start_request()
            request: dict[str, Any] = dict(
                model=self.service_model_name(),
                messages=await mistral_chat_messages(input),
                tools=mistral_chat_tools(tools) if len(tools) > 0 else None,
                tool_choice=(
                    mistral_chat_tool_choice(tool_choice) if len(tools) > 0 else None
                ),
                http_headers={HttpxHooks.REQUEST_ID_HEADER: request_id}
                | (config.extra_headers or {}),
            )
            prompt_cache_key = sample_cache_affinity_key()
            if prompt_cache_key is not None and _sdk_supports_prompt_cache_key():
                request["prompt_cache_key"] = prompt_cache_key
            if config.reasoning_effort is not None:
                request["reasoning_effort"] = mistral_reasoning_effort(
                    config.reasoning_effort
                )
            if config.temperature is not None:
                request["temperature"] = config.temperature
            if config.top_p is not None:
                request["top_p"] = config.top_p
            if config.max_tokens is not None:
                request["max_tokens"] = config.max_tokens
            if config.seed is not None:
                request["random_seed"] = config.seed
            if config.response_schema is not None:
                request["response_format"] = MistralResponseFormat(
                    type="json_schema",
                    json_schema=MistralJSONSchema(
                        name=config.response_schema.name,
                        description=config.response_schema.description,
                        schema_definition=config.response_schema.json_schema.model_dump(
                            exclude_none=True
                        ),
                        strict=config.response_schema.strict,
                    ),
                )

            # resolve streaming and mutate the request accordingly before the
            # ModelCall snapshot, so the logged request matches the wire request
            streaming = self.resolve_streaming(config)
            if streaming:
                request["stream"] = True

            # prepare request for inclusion in model call
            req = request.copy()
            req.update(messages=[message.model_dump() for message in req["messages"]])
            if req.get("tools", None) is not None:
                req["tools"] = [tool.model_dump() for tool in req["tools"]]

            model_call = set_active_model_event_call(req, None)

            # send request
            try:
                if streaming:
                    async with await client.chat.stream_async(**request) as events:
                        completion = await mistral_completion_from_stream(events)
                else:
                    completion = await client.chat.complete_async(**request)

                if completion is None:
                    raise RuntimeError(
                        "Mistral model did not return a response from generate."
                    )

                model_call.set_response(
                    completion.model_dump(), http_hooks.end_request(request_id)
                )
            except SDKError as ex:
                model_call.set_error(
                    as_error_response(ex.body), http_hooks.end_request(request_id)
                )
                if ex.status_code == 400:
                    return self.handle_bad_request(ex), model_call
                else:
                    raise ex

            # return model output (w/ tool calls if they exist)
            choices = await completion_choices_from_response(completion, tools)
            return ModelOutput(
                model=completion.model,
                choices=choices,
                usage=ModelUsage(
                    input_tokens=completion.usage.prompt_tokens or 0,
                    output_tokens=(
                        completion.usage.completion_tokens
                        if completion.usage.completion_tokens
                        else (completion.usage.total_tokens or 0)
                        - (completion.usage.prompt_tokens or 0)
                    ),
                    total_tokens=completion.usage.total_tokens or 0,
                ),
            ), model_call

    def resolve_streaming(self, config: GenerateConfig) -> bool:
        """Whether to use the streaming API for this generate call.

        Applies only to the chat-completions path (the conversation API path
        never streams). An explicit `streaming` model arg wins; when unset
        ("auto"), stream when the caller passed `on_stream` to
        `Model.generate()`. Auto mode declines to stream requests carrying a
        `response_schema`: structured output under streaming is unverified
        for Mistral, and a display-only `on_stream` request must not risk
        degrading results (an explicit `streaming=true` opt-in still
        streams).
        """
        if self.streaming is not None:
            return self.streaming
        return model_stream_requested() and config.response_schema is None

    def service_model_name(self) -> str:
        """Model name without any service prefix."""
        return self.model_name.replace(f"{self.service}/", "", 1)

    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup."""
        return f"mistral/{self.service_model_name()}"

    @override
    def should_retry(self, ex: Exception) -> bool | RetryDecision:
        if isinstance(ex, SDKError):
            if not is_retryable_http_status(ex.status_code):
                return RetryDecision.no()
            if ex.status_code == 429:
                return RetryDecision.rate_limit()
            return RetryDecision.transient()
        decision = httpx_classify_retry(ex)
        return decision if decision is not None else RetryDecision.no()

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
        if isinstance(ex, SDKError):
            return ex.status_code == 401
        return False

    def handle_bad_request(self, ex: SDKError) -> ModelOutput | Exception:
        body = json.loads(ex.body)
        content = body.get("message", ex.body)
        body_lower = ex.body.lower()
        if "maximum context length" in body_lower or "input too large" in body_lower:
            return ModelOutput.from_content(
                model=self.service_model_name(),
                content=content,
                stop_reason="model_length",
            )
        else:
            return ex


class _StreamToolCall(NamedTuple):
    """Accumulated state for one streamed tool call."""

    id: str | None
    function: str | None
    arguments: list[str]


class _StreamChoice:
    """Accumulated state for one streamed choice."""

    def __init__(self) -> None:
        self.content: list[str | ContentChunk] = []
        self.tool_calls: dict[int, _StreamToolCall] = {}
        self.finish_reason: str | None = None


async def mistral_completion_from_stream(
    events: AsyncIterator[CompletionEvent],
) -> MistralChatCompletionResponse:
    """Consume a Mistral chat-completions event stream into a final completion.

    Reports each chunk once to the model layer's stream observer
    (`inspect_ai.model._stream`), which fans out to the caller's `on_stream`
    callback and the pending event's progress record. Accumulates all
    choices, but reports content deltas from the first choice only —
    interleaving multiple choices' fragments into the single delta stream
    would corrupt accumulating consumers. Content deltas are gated on
    `model_stream_requested()` (see `report_model_stream_delta`); the
    usage/heartbeat progress channel runs regardless.
    """
    report_model_stream_start()
    completion_id: str | None = None
    created: int | None = None
    model: str | None = None
    usage: UsageInfo | None = None
    choices: dict[int, _StreamChoice] = {}

    async for event in events:
        chunk: CompletionChunk = event.data
        completion_id = completion_id or chunk.id
        created = created if created is not None else chunk.created
        model = model or chunk.model
        if chunk.usage is not None:
            usage = chunk.usage
            report_model_stream_progress(chunk.usage.completion_tokens)

        # report deltas from the first choice only, and only when an
        # on_stream consumer is present (see report_model_stream_delta) —
        # accumulation into the completion always runs
        deltas_requested = model_stream_requested()
        reported = False
        for chunk_choice in chunk.choices:
            choice = choices.setdefault(chunk_choice.index, _StreamChoice())
            if isinstance(chunk_choice.finish_reason, str):
                choice.finish_reason = chunk_choice.finish_reason
            delta = chunk_choice.delta
            report = chunk_choice.index == 0 and deltas_requested
            content = delta.content
            if isinstance(content, str) and content:
                choice.content.append(content)
                if report:
                    await report_model_stream_delta(StreamTextEvent(text=content))
                    reported = True
            elif isinstance(content, list):
                for piece in content:
                    choice.content.append(piece)
                    if not report:
                        continue
                    if isinstance(piece, TextChunk) and piece.text:
                        await report_model_stream_delta(
                            StreamTextEvent(text=piece.text)
                        )
                        reported = True
                    elif isinstance(piece, ThinkChunk):
                        reasoning = "".join(
                            t.text for t in piece.thinking if isinstance(t, TextChunk)
                        )
                        if reasoning:
                            await report_model_stream_delta(
                                StreamReasoningEvent(reasoning=reasoning)
                            )
                            reported = True
            for tool_call in delta.tool_calls or []:
                arguments = tool_call.function.arguments
                fragment = (
                    arguments
                    if isinstance(arguments, str)
                    else json.dumps(arguments)
                    if arguments
                    else ""
                )
                # id/function may arrive only on a call's first fragment;
                # remember them by slot so continuation fragments are
                # attributed (the SDK defaults an absent id to "null")
                tool_call_id = (
                    tool_call.id if tool_call.id and tool_call.id != "null" else None
                )
                # the SDK defaults an absent index to 0, so only a
                # server-provided index keys the slot; without one an id
                # starts a new call and bare fragments extend the latest
                if "index" in tool_call.model_fields_set and isinstance(
                    tool_call.index, int
                ):
                    index = tool_call.index
                elif tool_call_id is not None or not choice.tool_calls:
                    index = max(choice.tool_calls) + 1 if choice.tool_calls else 0
                else:
                    index = max(choice.tool_calls)
                info = choice.tool_calls.get(index, _StreamToolCall(None, None, []))
                info = _StreamToolCall(
                    id=tool_call_id or info.id,
                    function=tool_call.function.name or info.function,
                    arguments=info.arguments,
                )
                if fragment:
                    info.arguments.append(fragment)
                choice.tool_calls[index] = info
                if report:
                    await report_model_stream_delta(
                        StreamToolCallEvent(
                            id=info.id, function=info.function, arguments=fragment
                        )
                    )
                    reported = True
        if not reported and chunk.usage is None:
            report_model_stream_progress()

    if completion_id is None or model is None:
        raise RuntimeError("Streaming response ended without delivering any chunks.")

    # a streamed response may end without a usage chunk; usage is a required
    # response field so fabricate zeros, but warn rather than under-count
    # silently
    if usage is None:
        warn_once(
            logger,
            f"mistral model '{model}' reported no token usage for a streamed "
            "response; pass -M streaming=false if you require usage reporting.",
        )
        usage = UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    return MistralChatCompletionResponse(
        id=completion_id,
        object="chat.completion",
        model=model,
        usage=usage,
        created=created or 0,
        choices=[
            MistralChatCompletionChoice(
                index=index,
                message=MistralAssistantMessage(
                    content=_merge_stream_content(choice.content),
                    tool_calls=[
                        MistralToolCall(
                            id=tool_call.id,
                            type="function",
                            index=call_index,
                            function=FunctionCall(
                                name=tool_call.function or "",
                                arguments="".join(tool_call.arguments),
                            ),
                        )
                        for call_index, tool_call in sorted(choice.tool_calls.items())
                    ]
                    or None,
                ),
                finish_reason=choice.finish_reason or "stop",  # type: ignore[arg-type]
            )
            for index, choice in sorted(choices.items())
        ],
    )


def _merge_stream_content(
    pieces: list[str | ContentChunk],
) -> str | list[ContentChunk] | None:
    """Join accumulated content fragments into non-streaming response shape.

    All-string fragments join into one string (the common case). Otherwise
    strings become `TextChunk`s and consecutive same-type text/think chunk
    fragments merge into a single chunk, matching how a non-streamed response
    represents each contiguous run of content.
    """
    if not pieces:
        return None
    if all(isinstance(piece, str) for piece in pieces):
        return "".join(piece for piece in pieces if isinstance(piece, str))
    merged: list[ContentChunk] = []
    for piece in pieces:
        chunk: ContentChunk = TextChunk(text=piece) if isinstance(piece, str) else piece
        last = merged[-1] if merged else None
        if isinstance(chunk, TextChunk) and isinstance(last, TextChunk):
            merged[-1] = TextChunk(text=last.text + chunk.text)
        elif isinstance(chunk, ThinkChunk) and isinstance(last, ThinkChunk):
            merged[-1] = ThinkChunk(
                thinking=[
                    TextChunk(
                        text="".join(
                            t.text
                            for think in (last, chunk)
                            for t in think.thinking
                            if isinstance(t, TextChunk)
                        )
                    )
                ]
            )
        else:
            merged.append(chunk)
    return merged


def mistral_model_call(
    request: dict[str, Any], response: MistralChatCompletionResponse | None
) -> ModelCall:
    request = request.copy()
    request.update(messages=[message.model_dump() for message in request["messages"]])
    if request.get("tools", None) is not None:
        request["tools"] = [tool.model_dump() for tool in request["tools"]]
    return ModelCall.create(
        request=request, response=response.model_dump() if response else {}
    )


def mistral_chat_tools(tools: list[ToolInfo]) -> list[MistralTool]:
    return [
        MistralTool(
            type="function",
            function=mistral_function(tool),
        )
        for tool in tools
    ]


def mistral_function(tool: ToolInfo) -> MistralFunction:
    return MistralFunction(
        name=tool.name,
        description=tool.description,
        parameters=json_schema_dump(tool.parameters, exclude={"additionalProperties"}),
    )


def mistral_chat_tool_choice(
    tool_choice: ToolChoice,
) -> str | dict[str, Any]:
    if isinstance(tool_choice, ToolFunction):
        return MistralToolChoice(
            type="function", function=FunctionName(name=tool_choice.name)
        ).model_dump()
    elif tool_choice == "any":
        return "any"
    elif tool_choice == "auto":
        return "auto"
    elif tool_choice == "none":
        return "none"


MistralMessage = (
    MistralSystemMessage
    | MistralUserMessage
    | MistralAssistantMessage
    | MistralToolMessage
)


async def mistral_chat_messages(messages: list[ChatMessage]) -> list[MistralMessage]:
    mistral_messages = [await mistral_chat_message(message) for message in messages]
    mistral_messages = functools.reduce(mistral_message_reducer, mistral_messages, [])
    return mistral_messages


def mistral_message_reducer(
    messages: list[MistralMessage],
    message: MistralMessage,
) -> list[MistralMessage]:
    if (
        len(messages) > 0
        and isinstance(messages[-1], MistralToolMessage)
        and isinstance(message, MistralUserMessage)
    ):
        messages[-1] = fold_user_message_into_tool_message(messages[-1], message)
    else:
        messages.append(message)
    return messages


def fold_user_message_into_tool_message(
    tool: MistralToolMessage, user: MistralUserMessage
) -> MistralToolMessage:
    def normalise_content(
        content: str | list[ContentChunk] | None,
    ) -> list[ContentChunk]:
        return (
            []
            if content is None
            else [TextChunk(text=content)]
            if isinstance(content, str)
            else content
        )

    # normalise tool and user content
    tool_content = normalise_content(tool.content)
    user_content = normalise_content(user.content)

    # return tool message w/ tool and user content combined
    return MistralToolMessage(
        content=tool_content + user_content,
        tool_call_id=tool.tool_call_id,
        name=tool.name,
        role=tool.role,
    )


async def mistral_chat_message(
    message: ChatMessage,
) -> MistralMessage:
    if message.role == "assistant" and message.tool_calls:
        return MistralAssistantMessage(
            role=message.role,
            content=await mistral_message_content(message.content),
            tool_calls=[mistral_tool_call(call) for call in message.tool_calls],
        )
    elif message.role == "tool":
        return MistralToolMessage(
            role=message.role,
            tool_call_id=message.tool_call_id,
            name=message.function,
            content=(
                f"Error: {message.error.message}" if message.error else message.text
            ),
        )
    elif message.role == "user":
        return MistralUserMessage(
            content=await mistral_message_content(message.content)
        )
    elif message.role == "system":
        return MistralSystemMessage(
            content=mistral_system_message_content(message.content)
        )
    elif message.role == "assistant":
        return MistralAssistantMessage(
            content=await mistral_message_content(message.content)
        )


async def mistral_message_content(
    content: str | list[Content],
) -> str | list[ContentChunk]:
    if isinstance(content, str):
        return content or NO_CONTENT
    else:
        return [await mistral_content_chunk(c) for c in content]


def mistral_system_message_content(
    content: str | list[Content],
) -> str | list[TextChunk | ThinkChunk]:
    if isinstance(content, str):
        return content or NO_CONTENT
    else:
        message_content: list[TextChunk | ThinkChunk] = []
        for c in content:
            if isinstance(c, ContentText):
                message_content.append(TextChunk(text=c.text))
            elif isinstance(c, ContentReasoning):
                message_content.append(
                    ThinkChunk(thinking=[TextChunk(text=c.reasoning)])
                )
        return message_content


async def mistral_content_chunk(content: Content) -> ContentChunk:
    if isinstance(content, ContentText):
        return TextChunk(text=content.text or NO_CONTENT)
    elif isinstance(content, ContentImage):
        image_url = inline_media_data_uri(content.image, "image")

        # return chunk
        return ImageURLChunk(
            image_url=ImageURL(
                url=image_url,
                detail="high" if content.detail == "original" else content.detail,
            )
        )
    elif isinstance(content, ContentReasoning):
        return ThinkChunk(thinking=[TextChunk(text=content.reasoning)])
    else:
        raise RuntimeError(
            "Mistral models do not support audio, video, and document inputs."
        )


def mistral_tool_call(tool_call: ToolCall) -> MistralToolCall:
    return MistralToolCall(
        id=tool_call.id, function=mistral_function_call(tool_call), type="function"
    )


def mistral_function_call(tool_call: ToolCall) -> FunctionCall:
    return FunctionCall(
        name=tool_call.function, arguments=json.dumps(tool_call.arguments)
    )


def chat_tool_calls(
    tool_calls: list[MistralToolCall], tools: list[ToolInfo]
) -> list[ToolCall]:
    return [chat_tool_call(tool, tools) for tool in tool_calls]


def chat_tool_call(tool_call: MistralToolCall, tools: list[ToolInfo]) -> ToolCall:
    id = tool_call.id or f"{tool_call.function.name}_{uuid()}"
    if isinstance(tool_call.function.arguments, str):
        return parse_tool_call(
            id, tool_call.function.name, tool_call.function.arguments, tools
        )
    else:
        return ToolCall(id, tool_call.function.name, tool_call.function.arguments)


async def completion_choice(
    model: str, choice: MistralChatCompletionChoice, tools: list[ToolInfo]
) -> ChatCompletionChoice:
    message = choice.message
    if message:
        completion = await completion_content(message.content or "")
        return ChatCompletionChoice(
            message=ChatMessageAssistant(
                content=completion,
                tool_calls=chat_tool_calls(message.tool_calls, tools)
                if message.tool_calls
                else None,
                model=model,
                source="generate",
            ),
            stop_reason=(
                choice_stop_reason(choice)
                if choice.finish_reason is not None
                else "unknown"
            ),
        )
    else:
        raise ValueError(
            f"Mistral did not return a message in Completion Choice: {choice.model_dump_json(indent=2, exclude_none=True)}"
        )


async def completion_content(
    content: str | list[ContentChunk],
) -> str | list[Content]:
    if isinstance(content, str):
        return content
    else:
        completion: list[Content] = []
        for chunk in content:
            completion.extend(await completion_content_chunks(chunk))
        return completion


async def completion_content_chunks(content: ContentChunk) -> list[Content]:
    if isinstance(content, ReferenceChunk):
        raise TypeError("ReferenceChunk content is not supported by Inspect.")
    elif isinstance(content, TextChunk):
        content_text, reasoning = parse_content_with_reasoning(content.text)
        if reasoning:
            return [
                ContentReasoning(reasoning=reasoning.reasoning),
                ContentText(text=content_text),
            ]
        else:
            return [ContentText(text=content.text)]
    elif isinstance(content, DocumentURLChunk):
        return [ContentText(text=content.document_url)]
    elif isinstance(content, FileChunk):
        return [ContentText(text=f"file: {content.file_id}")]
    elif isinstance(content, ImageURLChunk):
        if isinstance(content.image_url, str):
            return [
                ContentImage(image=await provider_image_data_uri(content.image_url))
            ]
        else:
            detail: Literal["auto", "low", "high"]
            match content.image_url.detail:
                case "low":
                    detail = "low"
                case "high":
                    detail = "high"
                case _:
                    detail = "auto"
            return [
                ContentImage(
                    image=await provider_image_data_uri(content.image_url.url),
                    detail=detail,
                )
            ]
    elif isinstance(content, ThinkChunk):
        return [
            ContentReasoning(
                reasoning="\n".join(
                    t.text for t in content.thinking if isinstance(t, TextChunk)
                )
            )
        ]
    else:
        raise TypeError(f"{type(content)} content is not supported by Inspect.")


async def completion_choices_from_response(
    response: MistralChatCompletionResponse, tools: list[ToolInfo]
) -> list[ChatCompletionChoice]:
    if response.choices is None:
        return []
    else:
        choices: list[ChatCompletionChoice] = []
        for choice in response.choices:
            choices.append(await completion_choice(response.model, choice, tools))
        return choices


# Note: Mistral chat completions carry no response-level refusal category or
# explanation, so there is no ChatCompletionChoice.stop_details to populate here.
def choice_stop_reason(choice: MistralChatCompletionChoice) -> StopReason:
    match choice.finish_reason:
        case "stop":
            return "stop"
        case "length":
            return "max_tokens"
        case "model_length":
            return "model_length"
        case "tool_calls":
            return "tool_calls"
        case _:
            return "unknown"
