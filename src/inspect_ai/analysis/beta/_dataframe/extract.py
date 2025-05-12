import hashlib
import uuid
from typing import Any, cast

import shortuuid
from pydantic import BaseModel, JsonValue

from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)


def model_to_record(model: BaseModel) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], model.model_dump(mode="json", exclude_none=True))


def list_as_str(x: JsonValue) -> str:
    return ",".join([str(e) for e in (x if isinstance(x, list) else [x])])


def score_values(x: JsonValue) -> dict[str, JsonValue]:
    scores = cast(dict[str, Any], x)
    return {k: v["value"] for k, v in scores.items()}


def auto_id(base: str, index: str) -> str:
    seed = f"{base}_{index}"
    hash_bytes = hashlib.md5(seed.encode("utf-8")).digest()
    long_uuid = uuid.UUID(bytes=hash_bytes)
    return shortuuid.encode(long_uuid)


def messages_as_str(messages: str | list[ChatMessage]) -> str:
    if isinstance(messages, str):
        messages = [ChatMessageUser(content=messages)]
    return "\n\n".join([message_as_str(message) for message in messages])


def message_as_str(message: ChatMessage) -> str:
    transcript: list[str] = []
    role = message.role
    content = message.text.strip() if message.text else ""

    # assistant messages with tool calls
    if isinstance(message, ChatMessageAssistant) and message.tool_calls is not None:
        entry = f"{role}:\n{content}\n"

        for tool in message.tool_calls:
            func_name = tool.function
            args = tool.arguments

            if isinstance(args, dict):
                args_text = "\n".join(f"{k}: {v}" for k, v in args.items())
                entry += f"\nTool Call: {func_name}\nArguments:\n{args_text}"
            else:
                entry += f"\nTool Call: {func_name}\nArguments: {args}"

        transcript.append(entry)

    # tool responses with errors
    elif isinstance(message, ChatMessageTool) and message.error is not None:
        func_name = message.function or "unknown"
        entry = f"{role}:\n{content}\n\nError in tool call '{func_name}':\n{message.error.message}\n"
        transcript.append(entry)

    # normal messages
    else:
        transcript.append(f"{role}:\n{content}\n")

    return "\n".join(transcript)
