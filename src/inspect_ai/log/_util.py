from inspect_ai._util.content import (
    ContentAudio,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentVideo,
)
from inspect_ai.model._chat_message import ChatMessage


def text_inputs(inputs: str | list[ChatMessage]) -> str | list[ChatMessage]:
    # Clean the input of any images
    if isinstance(inputs, list):
        input: list[ChatMessage] = []
        for message in inputs:
            if not isinstance(message.content, str):
                filtered_content: list[
                    ContentText
                    | ContentReasoning
                    | ContentImage
                    | ContentAudio
                    | ContentVideo
                ] = []
                for content in message.content:
                    if content.type == "text":
                        filtered_content.append(content)
                    else:
                        filtered_content.append(
                            ContentText(text=f"({content.type.capitalize()})")
                        )
                message.content = filtered_content
                input.append(message)
            else:
                input.append(message)

        return input
    else:
        return inputs
