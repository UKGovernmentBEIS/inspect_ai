import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Literal, Sequence

import anyio
from mcp.types import (
    INTERNAL_ERROR,
    AudioContent,
    CreateMessageRequestParams,
    CreateMessageResult,
    EmbeddedResource,
    ErrorData,
    ImageContent,
    ResourceLink,
    SamplingMessageContentBlock,
    TextContent,
    TextResourceContents,
)
from mcp.types import (
    StopReason as MCPStopReason,
)

from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentImage,
    ContentText,
)
from inspect_ai._util.error import exception_message
from inspect_ai._util.url import data_uri_mime_type, data_uri_to_base64
from inspect_ai.util._limit import (
    LimitExceededError,
    enclosing_limit_error,
    limit_error_scope,
)

from ._compat import (
    content_mime_type,
    create_message_result,
    image_content,
    params_max_tokens,
    params_stop_sequences,
    params_system_prompt,
)


@dataclass
class _ToolCall:
    """A tool call in flight on a client session."""

    scope: anyio.CancelScope
    limit_error: LimitExceededError | None = None


# The tool calls in flight on each client session, so a sampling request on
# the session can hand them a limit error.
_session_tool_calls: "weakref.WeakKeyDictionary[Any, list[_ToolCall]]" = (
    weakref.WeakKeyDictionary()
)


@contextmanager
def raise_sampling_limit_error(session: Any) -> Iterator[None]:
    """Raise a limit exceeded by a sampling request during a tool call.

    Sampling requests run in the session's task, where a limit error cannot
    reach the scope that owns the limit. When one exceeds a limit, the tool
    calls in flight on the session stop waiting for the server and raise the
    error in place of their own result or error, so the tool executor can
    pass it on.

    Args:
       session: The client session the tool call is made on.
    """
    call = _ToolCall(scope=anyio.CancelScope())
    calls = _session_tool_calls.setdefault(session, [])
    calls.append(call)
    try:
        try:
            with call.scope:
                yield
        except Exception:
            if call.limit_error is not None:
                raise call.limit_error
            raise
        if call.limit_error is not None:
            raise call.limit_error
    finally:
        calls.remove(call)
        if not calls:
            _session_tool_calls.pop(session, None)


def _record_sampling_limit_error(session: Any, limit_error: LimitExceededError) -> None:
    """Hand `limit_error` to the tool calls in flight on `session` and stop them."""
    for call in _session_tool_calls.get(session, []):
        if call.limit_error is None:
            call.limit_error = limit_error
            call.scope.cancel()


def _pending_sampling_limit_error(session: Any) -> LimitExceededError | None:
    for call in _session_tool_calls.get(session, []):
        if call.limit_error is not None:
            return call.limit_error
    return None


async def sampling_fn(
    # RequestContext[ClientSession, Any] on mcp 1.x, ClientRequestContext on
    # 2.x — typed as Any to satisfy both SamplingFnT protocols (both carry
    # the client `session`)
    context: Any,
    params: CreateMessageRequestParams,
) -> CreateMessageResult | ErrorData:
    from inspect_ai.log._samples import sample_active
    from inspect_ai.model._chat_message import (
        ChatMessage,
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageUser,
    )
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model import get_model

    # once a limit is exceeded, refuse further requests from the tool call
    session = getattr(context, "session", None)
    pending = _pending_sampling_limit_error(session) if session is not None else None
    if pending is not None:
        return ErrorData(code=INTERNAL_ERROR, message=pending.message)

    try:
        # build message list
        messages: list[ChatMessage] = []
        system_prompt = params_system_prompt(params)
        if system_prompt:
            messages.append(ChatMessageSystem(content=system_prompt))

        for message in params.messages:
            if message.role == "assistant":
                messages.append(
                    ChatMessageAssistant(
                        content=as_inspect_content_list(message.content)
                    )
                )
            elif message.role == "user":
                messages.append(
                    ChatMessageUser(content=as_inspect_content_list(message.content))
                )

        # sample w/ requested params
        output = await get_model().generate(
            messages,
            config=GenerateConfig(
                temperature=params.temperature,
                max_tokens=params_max_tokens(params),
                stop_seqs=params_stop_sequences(params),
            ),
        )

        # convert stop reason
        stop_reason: MCPStopReason = (
            "maxTokens" if output.stop_reason == "max_tokens" else "endTurn"
        )

        # return first compatible content
        if isinstance(output.message.content, str):
            return create_message_result(
                content=TextContent(type="text", text=output.message.content),
                model=output.model,
                stop_reason=stop_reason,
            )
        else:
            for content in output.message.content:
                if isinstance(content, ContentText | ContentImage):
                    return create_message_result(
                        content=as_mcp_content(content),
                        model=output.model,
                        stop_reason=stop_reason,
                    )

            # if we get this far then no valid content was returned
            return ErrorData(
                code=INTERNAL_ERROR, message="No text or image content was generated."
            )

    except Exception as ex:
        # This includes LimitExceededError and ModelRefusalError: the mcp
        # dispatcher converts anything raised here into an INTERNAL_ERROR
        # response anyway, so re-raising would not reach the sample runner.
        # A sample limit ends the sample now; any limit is also raised by
        # the tool call (see raise_sampling_limit_error).
        limit_error = enclosing_limit_error(ex)
        if limit_error is not None:
            if limit_error_scope(limit_error) == "sample":
                active = sample_active()
                if active is not None:
                    active.limit_exceeded(limit_error)
            if session is not None:
                _record_sampling_limit_error(session, limit_error)
        return ErrorData(code=INTERNAL_ERROR, message=exception_message(ex))


def as_inspect_content_list(
    content: SamplingMessageContentBlock | Sequence[SamplingMessageContentBlock],
) -> list[Content]:
    if isinstance(content, Sequence):
        return [as_inspect_content(c) for c in content]
    else:
        return [as_inspect_content(content)]


def as_inspect_content(
    content: SamplingMessageContentBlock,
) -> ContentText | ContentImage | ContentAudio:
    if isinstance(content, TextContent):
        return ContentText(text=content.text)
    elif isinstance(content, ImageContent):
        return ContentImage(
            image=f"data:{content_mime_type(content)};base64,{content.data}"
        )
    elif isinstance(content, AudioContent):
        return ContentAudio(
            audio=f"data:{content_mime_type(content)};base64,{content.data}",
            format=_get_audio_format(content_mime_type(content)),
        )
    elif isinstance(content, ResourceLink):
        return ContentText(text=f"{content.description} ({content.uri})")
    elif isinstance(content, EmbeddedResource) and isinstance(
        content.resource, TextResourceContents
    ):
        return ContentText(text=content.resource.text)
    # TODO:  ToolResultContent, ToolUseContent,
    else:
        raise ValueError(f"Unexpected content: {content}")


def as_mcp_content(content: ContentText | ContentImage) -> TextContent | ImageContent:
    if isinstance(content, ContentText):
        return TextContent(type="text", text=content.text)
    else:
        return image_content(
            mime_type=data_uri_mime_type(content.image) or "image/png",
            data=data_uri_to_base64(content.image),
        )


def _get_audio_format(mime_type: str) -> Literal["wav", "mp3"]:
    """Helper function to determine audio format from MIME type."""
    if mime_type in ("audio/wav", "audio/x-wav"):
        return "wav"
    elif mime_type == "audio/mpeg":
        return "mp3"
    else:
        raise ValueError(f"Unsupported audio mime type: {mime_type}")
