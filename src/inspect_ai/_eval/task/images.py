import asyncio

from inspect_ai._util.constants import BASE_64_DATA_REMOVED
from inspect_ai._util.images import image_as_data_uri
from inspect_ai._util.url import is_data_uri
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessage, ChatMessageUser, Content, ContentImage
from inspect_ai.solver import TaskState


async def states_with_base64_images(states: list[TaskState]) -> list[TaskState]:
    return await asyncio.gather(*[state_with_base64_images(state) for state in states])


async def state_with_base64_images(state: TaskState) -> TaskState:
    state.messages = await messages_with_base64_images(state.messages)
    return state


def state_without_base64_images(state: TaskState) -> TaskState:
    state.messages = messages_without_base64_images(state.messages)
    return state


async def samples_with_base64_images(samples: list[Sample]) -> list[Sample]:
    return await asyncio.gather(
        *[sample_with_base64_images(sample) for sample in samples]
    )


async def sample_with_base64_images(sample: Sample) -> Sample:
    if isinstance(sample.input, list):
        return Sample(
            input=await messages_with_base64_images(sample.input),
            target=sample.target,
            id=sample.id,
            metadata=sample.metadata,
            files=sample.files,
            choices=sample.choices,
        )
    else:
        return sample


def sample_without_base64_images(sample: Sample) -> Sample:
    if isinstance(sample.input, list):
        return Sample(
            input=messages_without_base64_images(sample.input),
            target=sample.target,
            id=sample.id,
            metadata=sample.metadata,
            files=sample.files,
            choices=sample.choices,
        )
    else:
        return sample


async def messages_with_base64_images(messages: list[ChatMessage]) -> list[ChatMessage]:
    return await asyncio.gather(
        *[message_with_base64_image(message) for message in messages]
    )


def messages_without_base64_images(messages: list[ChatMessage]) -> list[ChatMessage]:
    return [message_without_base64_image(message) for message in messages]


async def message_with_base64_image(message: ChatMessage) -> ChatMessage:
    if isinstance(message, ChatMessageUser) and not isinstance(message.content, str):
        return ChatMessageUser(
            content=[
                await chat_content_with_base64_image(content)
                for content in message.content
            ],
            source=message.source,
        )
    else:
        return message


def message_without_base64_image(message: ChatMessage) -> ChatMessage:
    if isinstance(message, ChatMessageUser) and not isinstance(message.content, str):
        return ChatMessageUser(
            content=[
                chat_content_without_base64_image(content)
                for content in message.content
            ],
            source=message.source,
        )
    else:
        return message


async def chat_content_with_base64_image(content: Content) -> Content:
    if isinstance(content, ContentImage):
        if isinstance(content.image, str):
            return ContentImage(image=await image_as_data_uri(content.image))
        else:
            return ContentImage(
                image=await image_as_data_uri(content.image.url),
                detail=content.image.detail,
            )
    else:
        return content


def chat_content_without_base64_image(content: Content) -> Content:
    if isinstance(content, ContentImage) and is_data_uri(content.image):
        return ContentImage(image=BASE_64_DATA_REMOVED, detail=content.detail)
    else:
        return content
