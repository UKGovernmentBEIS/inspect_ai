import functools

from inspect_ai._util._async import tg_collect
from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.content import Content, ContentAudio, ContentImage, ContentVideo
from inspect_ai._util.images import file_as_data_uri
from inspect_ai._util.url import is_data_uri
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessage
from inspect_ai.solver import TaskState


async def states_with_base64_content(states: list[TaskState]) -> list[TaskState]:
    return await tg_collect(
        [functools.partial(state_with_base64_content, state) for state in states]
    )


async def state_with_base64_content(state: TaskState) -> TaskState:
    state.messages = await messages_with_base64_content(state.messages)
    return state


def state_without_base64_content(state: TaskState) -> TaskState:
    state.messages = messages_without_base64_content(state.messages)
    return state


async def samples_with_base64_content(samples: list[Sample]) -> list[Sample]:
    return await tg_collect(
        [functools.partial(sample_with_base64_content, sample) for sample in samples]
    )


async def sample_with_base64_content(sample: Sample) -> Sample:
    if isinstance(sample.input, list):
        return sample.model_copy(
            update={"input": await messages_with_base64_content(sample.input)}
        )
    else:
        return sample


def sample_without_base64_content(sample: Sample) -> Sample:
    if isinstance(sample.input, list):
        return sample.model_copy(
            update={"input": messages_without_base64_content(sample.input)}
        )
    else:
        return sample


async def messages_with_base64_content(
    messages: list[ChatMessage],
) -> list[ChatMessage]:
    return await tg_collect(
        [
            functools.partial(message_with_base64_content, message)
            for message in messages
        ]
    )


def messages_without_base64_content(messages: list[ChatMessage]) -> list[ChatMessage]:
    return [message_without_base64_content(message) for message in messages]


async def message_with_base64_content(message: ChatMessage) -> ChatMessage:
    if not isinstance(message.content, str):
        return message.model_copy(
            update=dict(
                content=[
                    await chat_content_with_base64_content(content)
                    for content in message.content
                ]
            )
        )

    else:
        return message


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


async def chat_content_with_base64_content(content: Content) -> Content:
    if isinstance(content, ContentImage):
        return ContentImage(
            image=await file_as_data_uri(content.image),
            detail=content.detail,
        )
    elif isinstance(content, ContentAudio):
        return ContentAudio(
            audio=await file_as_data_uri(content.audio), format=content.format
        )
    elif isinstance(content, ContentVideo):
        return ContentVideo(
            video=await file_as_data_uri(content.video), format=content.format
        )
    else:
        return content


def chat_content_without_base64_content(content: Content) -> Content:
    if isinstance(content, ContentImage) and is_data_uri(content.image):
        return ContentImage(image=BASE_64_DATA_REMOVED, detail=content.detail)
    elif isinstance(content, ContentAudio) and is_data_uri(content.audio):
        return ContentAudio(audio=BASE_64_DATA_REMOVED, format="mp3")
    elif isinstance(content, ContentVideo) and is_data_uri(content.video):
        return ContentVideo(video=BASE_64_DATA_REMOVED, format="mp4")
    else:
        return content
