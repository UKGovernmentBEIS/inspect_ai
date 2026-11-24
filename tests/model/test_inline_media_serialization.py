import ast
from pathlib import Path
from typing import Any, cast

import pytest

from inspect_ai._util.content import (
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.images import UnresolvedMediaError
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    get_model,
)
from inspect_ai.model._openai import openai_chat_completion_part
from inspect_ai.model._openai_responses import (
    _openai_input_items_from_chat_message_assistant,
    _openai_responses_content_param,
    content_from_response_input_content_param,
    openai_responses_inputs,
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


@pytest.mark.parametrize(
    "content",
    [
        ContentImage(image="/tmp/runtime-selected.png"),
        ContentAudio(audio="/tmp/runtime-selected.mp3", format="mp3"),
        ContentVideo(video="/tmp/runtime-selected.mp4", format="mp4"),
        ContentDocument(document="/tmp/runtime-selected.pdf"),
    ],
)
async def test_model_boundary_rejects_non_inline_media(
    content: ContentImage | ContentAudio | ContentVideo | ContentDocument,
) -> None:
    messages: list[ChatMessage] = [ChatMessageUser(content=[content])]

    with pytest.raises(UnresolvedMediaError, match="materialized"):
        await get_model("mockllm/model").generate(messages)


async def test_model_boundary_accepts_mime_less_image_data_uri() -> None:
    messages: list[ChatMessage] = [
        ChatMessageUser(content=[ContentImage(image="data:;base64,iVBORw0KGgo=")])
    ]

    await get_model("mockllm/model").generate(messages)


@pytest.mark.parametrize(
    "content",
    [
        ContentImage(image="data:;base64,PHN2Zy8+"),
        ContentAudio(audio="data:;base64,AAAA", format="mp3"),
        ContentAudio(audio="data:;base64,AAAA", format="wav"),
        ContentVideo(video="data:;base64,AAAA", format="mp4"),
        ContentVideo(video="data:;base64,AAAA", format="mpeg"),
        ContentVideo(video="data:;base64,AAAA", format="mov"),
        ContentDocument(document="data:;base64,AAAA", mime_type="application/pdf"),
    ],
)
async def test_model_boundary_accepts_mime_less_media(
    content: ContentImage | ContentAudio | ContentVideo | ContentDocument,
) -> None:
    messages: list[ChatMessage] = [ChatMessageUser(content=[content])]

    await get_model("mockllm/model").generate(messages)


async def test_model_boundary_error_identifies_media_location() -> None:
    reference = "https://example.com/" + ("a" * 70) + "SECRET_TAIL"
    messages: list[ChatMessage] = [
        ChatMessageUser(content="first"),
        ChatMessageUser(
            content=[ContentText(text="second"), ContentImage(image=reference)]
        ),
    ]

    with pytest.raises(UnresolvedMediaError) as error:
        await get_model("mockllm/model").generate(messages)

    error_message = str(error.value)
    assert "message index 1" in error_message
    assert "content index 1" in error_message
    assert "image content" in error_message
    assert "example.com" not in error_message
    assert "SECRET_TAIL" not in error_message


@pytest.mark.parametrize("operation", ["count_tokens", "compact"])
async def test_all_model_entry_points_reject_non_inline_media(operation: str) -> None:
    model = get_model("mockllm/model")
    messages: list[ChatMessage] = [
        ChatMessageUser(content=[ContentImage(image="/tmp/secret.png")])
    ]

    with pytest.raises(UnresolvedMediaError, match="message index 0"):
        if operation == "count_tokens":
            await model.count_tokens(messages)
        else:
            await model.compact(messages, [])


@pytest.mark.parametrize(
    "file_data",
    [
        "/tmp/host-only-secret.txt",
        "https://example.com/report.pdf",
        "JVBERi0xLjQ=",
    ],
)
def test_responses_non_uri_file_data_is_not_normalized(file_data: str) -> None:
    content = content_from_response_input_content_param(
        cast(
            Any,
            {"type": "input_file", "file_data": file_data, "filename": "secret.txt"},
        )
    )

    assert isinstance(content, ContentDocument)
    assert content.document == file_data


def test_responses_typed_file_data_is_preserved() -> None:
    uri = "data:text/plain;base64,aGVsbG8="
    content = content_from_response_input_content_param(
        cast(
            Any,
            {"type": "input_file", "file_data": uri, "filename": "note.txt"},
        )
    )

    assert isinstance(content, ContentDocument)
    assert content.document == uri


def test_model_provider_modules_do_not_import_media_authority_helpers() -> None:
    forbidden = {"file_as_data", "file_as_data_uri", "materialize_media"}
    model_dir = Path(__file__).parents[2] / "src" / "inspect_ai" / "model"
    violations: list[str] = []

    for path in model_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "inspect_ai._util.images"
            ):
                imported = forbidden.intersection(alias.name for alias in node.names)
                if imported:
                    violations.append(
                        f"{path.relative_to(model_dir)}: {sorted(imported)}"
                    )

    assert violations == []


@pytest.mark.parametrize(
    "content",
    [
        ContentAudio(audio="data:image/png;base64,AAAA", format="mp3"),
        ContentVideo(video="data:audio/mpeg;base64,AAAA", format="mp4"),
    ],
)
async def test_model_boundary_rejects_incompatible_media_mime_type(
    content: ContentAudio | ContentVideo,
) -> None:
    with pytest.raises(ValueError, match="incompatible MIME type"):
        await get_model("mockllm/model").generate([ChatMessageUser(content=[content])])


async def test_model_boundary_rejects_media_hidden_in_agent_message() -> None:
    agent_message: dict[str, Any] = {
        "type": "agent_message",
        "author": "subagent",
        "recipient": "parent",
        "content": [{"type": "input_image", "image_url": "https://example.com/secret"}],
    }
    message = ChatMessageUser(
        content=[
            ContentText(
                text="Agent message from subagent",
                internal={"agent_message": agent_message},
            )
        ]
    )

    with pytest.raises(ValueError, match="input_image.*cannot be replayed"):
        await get_model("mockllm/model").generate([message])
    with pytest.raises(ValueError, match="input_image.*cannot be replayed"):
        await openai_responses_inputs([message])


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


async def test_provider_serializers_type_mime_less_media() -> None:
    image = cast(
        Any,
        await image_block_param("data:;base64,/9j/4AAQ", mime_type_hint="image/jpeg"),
    )
    assert image["source"]["media_type"] == "image/jpeg"

    audio = cast(
        Any,
        await openai_chat_completion_part(
            ContentAudio(audio="data:;base64,AAAA", format="mp3")
        ),
    )
    assert audio["input_audio"]["data"] == "AAAA"

    video = cast(
        Any,
        await _openai_responses_content_param(
            ContentVideo(video="data:;base64,AAAA", format="mov")
        ),
    )
    assert video["file_data"] == "data:video/quicktime;base64,AAAA"

    document = cast(
        Any,
        await mistral_conversation_content_chunk(
            ContentDocument(document="data:;base64,AAAA", mime_type="application/pdf")
        ),
    )
    assert document.document_url == "data:application/pdf;base64,AAAA"


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
