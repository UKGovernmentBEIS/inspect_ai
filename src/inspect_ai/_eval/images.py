import asyncio

from inspect_ai._util.images import image_as_data_uri
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessage, ChatMessageUser, Content, ContentImage


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
        )
    else:
        return sample


async def messages_with_base64_images(messages: list[ChatMessage]) -> list[ChatMessage]:
    return await asyncio.gather(
        *[message_with_base64_image(message) for message in messages]
    )


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
