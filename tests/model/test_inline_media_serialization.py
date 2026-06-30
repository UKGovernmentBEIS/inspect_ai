from typing import Any, cast

import pytest

from inspect_ai._util.content import ContentDocument, ContentImage
from inspect_ai._util.images import UnresolvedMediaError
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool
from inspect_ai.model._openai import openai_chat_completion_part
from inspect_ai.model._openai_responses import (
    _openai_input_items_from_chat_message_assistant,
    _openai_responses_content_param,
)
from inspect_ai.model._providers._openai_computer_use import computer_call_output
from inspect_ai.model._providers.anthropic import image_block_param
from inspect_ai.model._providers.bedrock import converse_contents
from inspect_ai.model._providers.google import chat_content_to_part
from inspect_ai.model._providers.mistral import mistral_content_chunk
from inspect_ai.model._providers.mistral_conversation import (
    mistral_content_chunk as mistral_conversation_content_chunk,
)

IMAGE_DATA_URI = "data:image/png;base64,iVBORw0KGgo="


async def test_provider_serializers_reject_non_inline_media() -> None:
    image = ContentImage(image="/tmp/runtime-selected.png")

    serializers = [
        lambda: openai_chat_completion_part(image),
        lambda: _openai_responses_content_param(image),
        lambda: image_block_param(image.image),
        lambda: chat_content_to_part(cast(Any, None), image),
        lambda: mistral_content_chunk(image),
        lambda: converse_contents([image]),
    ]

    for serialize in serializers:
        with pytest.raises(UnresolvedMediaError, match="materialized"):
            await serialize()


async def test_provider_serializers_accept_inline_media() -> None:
    image = ContentImage(image=IMAGE_DATA_URI)

    await openai_chat_completion_part(image)
    await _openai_responses_content_param(image)
    await image_block_param(image.image)
    await chat_content_to_part(cast(Any, None), image)
    await mistral_content_chunk(image)
    await converse_contents([image])


async def test_provider_serializers_reject_non_inline_documents() -> None:
    document = ContentDocument(document="/tmp/runtime-selected.pdf")

    serializers = [
        lambda: openai_chat_completion_part(document),
        lambda: _openai_responses_content_param(document),
        lambda: chat_content_to_part(cast(Any, None), document),
        lambda: mistral_conversation_content_chunk(document),
    ]

    for serialize in serializers:
        with pytest.raises(UnresolvedMediaError, match="materialized"):
            await serialize()


def test_openai_responses_assistant_replay_rejects_non_inline_image() -> None:
    message = ChatMessageAssistant(
        content=[ContentImage(image="https://example.com/runtime.png")]
    )

    with pytest.raises(UnresolvedMediaError, match="materialized"):
        _openai_input_items_from_chat_message_assistant(message)


def test_openai_computer_output_rejects_non_inline_screenshot() -> None:
    message = ChatMessageTool(
        content=[ContentImage(image="/tmp/runtime-screenshot.png")],
        tool_call_id="tool-call",
        function="computer",
    )

    with pytest.raises(UnresolvedMediaError, match="materialized"):
        computer_call_output(message, "computer-call")
