from typing import Any

from mcp.client.session import ClientSession
from mcp.shared.context import RequestContext
from mcp.types import (
    INTERNAL_ERROR,
    CreateMessageRequestParams,
    CreateMessageResult,
    EmbeddedResource,
    ErrorData,
    ImageContent,
    TextContent,
    TextResourceContents,
)
from mcp.types import (
    StopReason as MCPStopReason,
)

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.error import exception_message
from inspect_ai._util.url import data_uri_mime_type, data_uri_to_base64


async def sampling_fn(
    context: RequestContext[ClientSession, Any],
    params: CreateMessageRequestParams,
) -> CreateMessageResult | ErrorData:
    from inspect_ai.model._chat_message import (
        ChatMessage,
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageUser,
    )
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model import get_model

    try:
        # build message list
        messages: list[ChatMessage] = []
        if params.systemPrompt:
            messages.append(ChatMessageSystem(content=params.systemPrompt))

        for message in params.messages:
            if message.role == "assistant":
                messages.append(
                    ChatMessageAssistant(content=[as_inspect_content(message.content)])
                )
            elif message.role == "user":
                messages.append(
                    ChatMessageUser(content=[as_inspect_content(message.content)])
                )

        # sample w/ requested params
        output = await get_model().generate(
            messages,
            config=GenerateConfig(
                temperature=params.temperature,
                max_tokens=params.maxTokens,
                stop_seqs=params.stopSequences,
            ),
        )

        # convert stop reason
        stop_reason: MCPStopReason = (
            "maxTokens" if output.stop_reason == "max_tokens" else "endTurn"
        )

        # return first compatible content
        if isinstance(output.message.content, str):
            return CreateMessageResult(
                role="assistant",
                content=TextContent(type="text", text=output.message.content),
                model=output.model,
                stopReason=stop_reason,
            )
        else:
            for content in output.message.content:
                if isinstance(content, ContentText | ContentImage):
                    return CreateMessageResult(
                        role="assistant",
                        content=as_mcp_content(content),
                        model=output.model,
                        stopReason=stop_reason,
                    )

            # if we get this far then no valid content was returned
            return ErrorData(
                code=INTERNAL_ERROR, message="No text or image content was generated."
            )

    except Exception as ex:
        return ErrorData(code=INTERNAL_ERROR, message=exception_message(ex))


def as_inspect_content(
    content: TextContent | ImageContent | EmbeddedResource,
) -> Content:
    if isinstance(content, TextContent):
        return ContentText(text=content.text)
    elif isinstance(content, ImageContent):
        return ContentImage(
            image=f"data:image/{content.mimeType};base64,{content.data}"
        )
    elif isinstance(content.resource, TextResourceContents):
        return ContentText(text=content.resource.text)
    else:
        raise ValueError(f"Unexpected content: {content}")


def as_mcp_content(content: ContentText | ContentImage) -> TextContent | ImageContent:
    if isinstance(content, ContentText):
        return TextContent(type="text", text=content.text)
    else:
        return ImageContent(
            type="image",
            mimeType=data_uri_mime_type(content.image) or "image/png",
            data=data_uri_to_base64(content.image),
        )
