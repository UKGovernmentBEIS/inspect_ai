from typing import Callable

from inspect_ai._util.content import Content, ContentImage
from inspect_ai._util.file import filesystem
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec

from .._dataset import Dataset


def resolve_sample_files(dataset: Dataset) -> None:
    """Resolve relative file paths to absolute (using the input file path)"""
    # bail if the dataset has no location
    if not dataset.location:
        return

    # filesystem and parent for resolving paths
    fs = filesystem(dataset.location)
    parent_dir = fs.sep.join(dataset.location.split(fs.sep)[:-1])

    # resolve file locations
    def resolve_file(file: str) -> str:
        # try/except (and ignore) to tolerate 'paths' that are actually
        # file contents (so will trip OS name too long constraints)
        try:
            target_file = f"{parent_dir}{fs.sep}{file}"
            if fs.exists(target_file):
                return target_file
            else:
                return file
        except OSError:
            return file

    # for each sample
    for sample in dataset:
        # check for sandbox config file
        if sample.sandbox and sample.sandbox.config is not None:
            sample.sandbox = SandboxEnvironmentSpec(
                sample.sandbox.type, resolve_file(sample.sandbox.config)
            )

        # check for files
        if sample.files is not None:
            for path in sample.files.keys():
                sample.files[path] = resolve_file(sample.files[path])

        # check for image paths
        if not isinstance(sample.input, str):
            sample.input = messages_with_resolved_images(sample.input, resolve_file)


def messages_with_resolved_images(
    messages: list[ChatMessage], resolver: Callable[[str], str]
) -> list[ChatMessage]:
    return [message_with_resolved_image(message, resolver) for message in messages]


def message_with_resolved_image(
    message: ChatMessage, resolver: Callable[[str], str]
) -> ChatMessage:
    if isinstance(message, ChatMessageUser) and not isinstance(message.content, str):
        return ChatMessageUser(
            content=[
                chat_content_with_resolved_image(content, resolver)
                for content in message.content
            ],
            source=message.source,
        )
    else:
        return message


def chat_content_with_resolved_image(
    content: Content, resolver: Callable[[str], str]
) -> Content:
    if isinstance(content, ContentImage):
        if isinstance(content.image, str):
            return ContentImage(image=resolver(content.image))
        else:
            return ContentImage(
                image=resolver(content.image),
                detail=content.image.detail,
            )
    else:
        return content
