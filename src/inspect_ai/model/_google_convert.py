"""Conversion functions for Google GenAI models."""

import base64
from typing import TYPE_CHECKING, Any, Literal, Sequence, Union

from shortuuid import uuid

from inspect_ai._util.content import (
    Content as InspectContent,
)
from inspect_ai._util.content import (
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.images import as_data_uri
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.providers import validate_google_client
from inspect_ai.tool import ToolCall

if TYPE_CHECKING:
    from google.genai.types import Content, ContentDict, GenerateContentResponse, Part


async def messages_from_google(
    contents: "Sequence[Content | ContentDict]",
    system_instruction: str | None = None,
    model: str | None = None,
) -> list[ChatMessage]:
    """Convert Google GenAI Content list into Inspect messages.

    Args:
        contents: Google GenAI Content objects or dicts that can be converted.
        system_instruction: Optional system instruction string.
        model: Optional model name to tag assistant messages with.

    Returns:
        List of Inspect ChatMessage objects.
    """
    validate_google_client("messages_from_google()")

    from google.genai.types import Content

    messages: list[ChatMessage] = []

    # Add system instruction as first message if provided
    if system_instruction:
        messages.append(ChatMessageSystem(content=system_instruction))

    # Convert each Content to ChatMessage (may produce multiple messages per Content)
    for content in contents:
        # Convert dict to Content if needed
        if isinstance(content, dict):
            content = Content.model_validate(content)

        message_list = await chat_message_from_google_content(content, model)
        messages.extend(message_list)  # Flatten: extend instead of append

    return messages


async def model_output_from_google(
    response: Union["GenerateContentResponse", dict[str, Any]],
    model: str | None = None,
) -> ModelOutput:
    """Convert Google GenerateContentResponse into Inspect ModelOutput.

    Args:
        response: Google GenerateContentResponse object or dict that can be converted.
        model: Optional model name override.

    Returns:
        Inspect ModelOutput object.

    Raises:
        ValidationError: If the dict can't be converted into a GenerateContentResponse.
    """
    validate_google_client("model_output_from_google()")

    from google.genai.types import GenerateContentResponse

    from inspect_ai.model._providers.google import (
        completion_choices_from_candidates,
        usage_metadata_to_model_usage,
    )

    # Convert dict to GenerateContentResponse if needed
    if isinstance(response, dict):
        response = GenerateContentResponse.model_validate(response)

    # Determine model name
    model_name = model or response.model_version or "unknown"

    # Create ModelOutput
    return ModelOutput(
        model=model_name,
        choices=completion_choices_from_candidates(model_name, response),
        usage=usage_metadata_to_model_usage(response.usage_metadata),
    )


async def chat_message_from_google_content(
    content: "Content", model: str | None = None
) -> list[ChatMessage]:
    """Convert a single Google Content to ChatMessage list.

    A single Content may produce multiple messages if it contains mixed
    user text and function responses.

    Args:
        content: Google GenAI Content object.
        model: Optional model name for assistant messages.

    Returns:
        List of ChatMessage objects (typically one, but can be multiple for mixed content).
    """
    if content.role == "model":
        # Assistant message
        message_content = await content_from_google_parts(content.parts or [])
        tool_calls = await tool_calls_from_google_parts(content.parts or [])

        return [
            ChatMessageAssistant(
                content=message_content if message_content else "",
                tool_calls=tool_calls if tool_calls else None,
                model=model,
                source="generate",
            )
        ]
    elif content.role == "tool":
        # Official SDK pattern: separate Content with role='tool' for function responses
        return [await tool_message_from_parts(content.parts or [])]
    elif content.role == "user":
        # Handle mixed content: can have both text parts and function responses
        parts = content.parts or []
        messages: list[ChatMessage] = []
        pending_content: list[InspectContent] = []

        for part in parts:
            if part.function_response is not None:
                # Flush pending content as user message first
                if pending_content:
                    messages.append(ChatMessageUser(content=pending_content))
                    pending_content = []
                # Add tool message
                messages.append(await tool_message_from_parts([part]))
            else:
                # Accumulate non-function-response content
                part_content = await content_from_google_parts([part])
                pending_content.extend(part_content)

        # Flush remaining content as user message
        if pending_content:
            messages.append(ChatMessageUser(content=pending_content))

        return messages if messages else [ChatMessageUser(content="")]
    else:
        raise ValueError(f"Unknown role in Google Content: {content.role}")


async def content_from_google_parts(
    parts: "list[Part]",
) -> list[InspectContent]:
    """Convert Google Parts to Inspect Content list.

    Args:
        parts: List of Google Part objects.

    Returns:
        List of Inspect Content objects.
    """
    content: list[InspectContent] = []
    working_reasoning_block: ContentReasoning | None = None

    for part in parts:
        # Skip function_call and function_response (handled separately)
        if part.function_call is not None or part.function_response is not None:
            continue

        # Handle text content
        if part.text is not None:
            if part.thought:
                # Unencrypted reasoning block
                working_reasoning_block = ContentReasoning(
                    reasoning=part.text,
                    redacted=False,
                )
                content.append(working_reasoning_block)
            elif part.thought_signature is not None:
                # Text with encrypted signature
                if working_reasoning_block is not None:
                    # Attach signature to previous reasoning block
                    working_reasoning_block.summary = working_reasoning_block.reasoning
                    working_reasoning_block.reasoning = base64.b64encode(
                        part.thought_signature
                    ).decode()
                    working_reasoning_block.redacted = True
                    working_reasoning_block = None
                else:
                    # Standalone encrypted reasoning
                    content.append(
                        ContentReasoning(
                            reasoning=base64.b64encode(part.thought_signature).decode(),
                            redacted=True,
                        )
                    )
                # Add the text content
                content.append(ContentText(text=part.text))
            else:
                # Regular text
                content.append(ContentText(text=part.text))
                working_reasoning_block = None

        # Handle thought_signature without text
        elif part.thought_signature is not None:
            if working_reasoning_block is not None:
                # Attach to previous reasoning block
                working_reasoning_block.summary = working_reasoning_block.reasoning
                working_reasoning_block.reasoning = base64.b64encode(
                    part.thought_signature
                ).decode()
                working_reasoning_block.redacted = True
                working_reasoning_block = None
            else:
                # Standalone encrypted reasoning
                content.append(
                    ContentReasoning(
                        reasoning=base64.b64encode(part.thought_signature).decode(),
                        redacted=True,
                    )
                )

        # Handle inline data (images)
        elif part.inline_data and part.inline_data.mime_type and part.inline_data.data:
            content.append(
                ContentImage(
                    image=as_data_uri(
                        part.inline_data.mime_type,
                        part.inline_data.data.decode("utf-8"),
                    )
                )
            )
            working_reasoning_block = None

        # Handle file data (audio, video, documents)
        elif part.file_data is not None:
            mime_type = part.file_data.mime_type
            uri = part.file_data.file_uri

            if uri:
                if mime_type and "audio" in mime_type:
                    # Extract format from mime type (e.g., "audio/mp3" -> "mp3")
                    audio_format: Literal["mp3", "wav"] = "mp3"  # default
                    if "wav" in mime_type:
                        audio_format = "wav"
                    content.append(ContentAudio(audio=uri, format=audio_format))
                elif mime_type and "video" in mime_type:
                    # Extract format from mime type (e.g., "video/mp4" -> "mp4")
                    video_format: Literal["mp4", "mpeg", "mov"] = "mp4"  # default
                    if "mpeg" in mime_type:
                        video_format = "mpeg"
                    elif "mov" in mime_type or "quicktime" in mime_type:
                        video_format = "mov"
                    content.append(ContentVideo(video=uri, format=video_format))
                else:
                    # Assume document
                    content.append(
                        ContentDocument(
                            document=uri,
                            mime_type=mime_type or "application/octet-stream",
                        )
                    )

            working_reasoning_block = None

    return content


async def tool_calls_from_google_parts(parts: "list[Part]") -> list[ToolCall] | None:
    """Extract ToolCall list from Google Parts.

    Args:
        parts: List of Google Part objects.

    Returns:
        List of ToolCall objects, or None if no tool calls found.
    """
    tool_calls: list[ToolCall] = []

    for part in parts:
        if part.function_call is not None and part.function_call.name:
            tool_calls.append(
                ToolCall(
                    id=f"{part.function_call.name}_{uuid()}",
                    function=part.function_call.name,
                    arguments=part.function_call.args or {},
                    type="function",
                )
            )

    return tool_calls if tool_calls else None


async def tool_message_from_parts(parts: "list[Part]") -> ChatMessageTool:
    """Create ChatMessageTool from Parts with function_response.

    Args:
        parts: List of Google Part objects containing function_response.

    Returns:
        ChatMessageTool object.
    """
    # Find the first function_response part
    for part in parts:
        if part.function_response is not None:
            function_name = part.function_response.name
            response_content = part.function_response.response

            # Extract text from response dict
            if isinstance(response_content, dict):
                text = response_content.get("content", str(response_content))
            else:
                text = str(response_content)

            return ChatMessageTool(
                function=function_name,
                content=text,
                tool_call_id=f"{function_name}_{uuid()}",
            )

    # Shouldn't happen if caller checks properly
    raise ValueError("No function_response found in parts")
