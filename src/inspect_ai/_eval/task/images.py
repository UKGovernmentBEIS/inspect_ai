from dataclasses import dataclass
from typing import Sequence, TypeAlias

from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentVideo,
)
from inspect_ai._util.images import MediaKind, materialize_media
from inspect_ai._util.url import is_data_uri
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessage
from inspect_ai.solver import TaskState


@dataclass(frozen=True)
class AuthorizedMediaRef:
    message_index: int
    content_index: int
    kind: MediaKind
    reference: str


TaskInputMediaPlan: TypeAlias = dict[int | str, tuple[AuthorizedMediaRef, ...]]


def capture_task_input_media(samples: Sequence[Sample]) -> TaskInputMediaPlan:
    """Capture exact non-inline media references authorized before task execution."""
    plan: TaskInputMediaPlan = {}

    for sample in samples:
        if sample.id is None:
            raise ValueError(
                "Sample ids must be assigned before capturing input media."
            )
        if isinstance(sample.input, str):
            continue

        refs: list[AuthorizedMediaRef] = []
        for message_index, message in enumerate(sample.input):
            if isinstance(message.content, str):
                continue
            for content_index, content in enumerate(message.content):
                media = _media_reference(content)
                if media is None or is_data_uri(media[1]):
                    continue
                refs.append(
                    AuthorizedMediaRef(
                        message_index=message_index,
                        content_index=content_index,
                        kind=media[0],
                        reference=media[1],
                    )
                )
        if refs:
            plan[sample.id] = tuple(refs)

    return plan


async def materialize_sample_input(sample: Sample, plan: TaskInputMediaPlan) -> Sample:
    """Materialize only media references captured for this exact sample input."""
    if isinstance(sample.input, str) or sample.id is None:
        return sample

    authorized = {
        (ref.message_index, ref.content_index): (ref.kind, ref.reference)
        for ref in plan.get(sample.id, ())
    }
    messages: list[ChatMessage] = []
    for message_index, message in enumerate(sample.input):
        if isinstance(message.content, str):
            messages.append(message)
            continue

        contents: list[Content] = []
        for content_index, content in enumerate(message.content):
            media = _media_reference(content)
            expected = authorized.get((message_index, content_index))
            if media is not None and expected == media and not is_data_uri(media[1]):
                contents.append(
                    _content_with_reference(
                        content,
                        await materialize_media(
                            media[1], mime_type=_media_mime_type(content)
                        ),
                    )
                )
            else:
                contents.append(content)
        messages.append(message.model_copy(update={"content": contents}))

    return sample.model_copy(update={"input": messages})


def sample_without_base64_content(sample: Sample) -> Sample:
    if isinstance(sample.input, list):
        return sample.model_copy(
            update={"input": messages_without_base64_content(sample.input)}
        )
    else:
        return sample


def messages_without_base64_content(messages: list[ChatMessage]) -> list[ChatMessage]:
    return [message_without_base64_content(message) for message in messages]


def message_without_base64_content(message: ChatMessage) -> ChatMessage:
    if not isinstance(message.content, str):
        return message.model_copy(
            update=dict(
                content=[
                    chat_content_without_base64_content(content)
                    for content in message.content
                ]
            )
        )

    else:
        return message


def _media_reference(content: Content) -> tuple[MediaKind, str] | None:
    if isinstance(content, ContentImage):
        return "image", content.image
    elif isinstance(content, ContentAudio):
        return "audio", content.audio
    elif isinstance(content, ContentVideo):
        return "video", content.video
    elif isinstance(content, ContentDocument):
        return "document", content.document
    else:
        return None


def _content_with_reference(content: Content, reference: str) -> Content:
    if isinstance(content, ContentImage):
        return content.model_copy(update={"image": reference})
    elif isinstance(content, ContentAudio):
        return content.model_copy(update={"audio": reference})
    elif isinstance(content, ContentVideo):
        return content.model_copy(update={"video": reference})
    elif isinstance(content, ContentDocument):
        return content.model_copy(update={"document": reference})
    else:
        return content


def _media_mime_type(content: Content) -> str | None:
    if isinstance(content, ContentAudio):
        return "audio/mpeg" if content.format == "mp3" else "audio/wav"
    elif isinstance(content, ContentVideo):
        return {
            "mp4": "video/mp4",
            "mpeg": "video/mpeg",
            "mov": "video/quicktime",
        }[content.format]
    elif isinstance(content, ContentDocument):
        return content.mime_type
    else:
        return None


def state_without_base64_content(state: TaskState) -> TaskState:
    state.messages = messages_without_base64_content(state.messages)
    return state


def chat_content_without_base64_content(content: Content) -> Content:
    if isinstance(content, ContentImage) and is_data_uri(content.image):
        return ContentImage(image=BASE_64_DATA_REMOVED, detail=content.detail)
    elif isinstance(content, ContentAudio) and is_data_uri(content.audio):
        return ContentAudio(audio=BASE_64_DATA_REMOVED, format=content.format)
    elif isinstance(content, ContentVideo) and is_data_uri(content.video):
        return ContentVideo(video=BASE_64_DATA_REMOVED, format=content.format)
    elif isinstance(content, ContentDocument) and is_data_uri(content.document):
        return ContentDocument(
            document=BASE_64_DATA_REMOVED,
            filename=content.filename,
            mime_type=content.mime_type,
        )
    else:
        return content
