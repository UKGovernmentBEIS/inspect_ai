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
    result = model.model_dump(mode="json", exclude_none=True)

    # Fix Score objects that get incorrectly serialized
    def fix_scores(obj: Any) -> Any:
        if isinstance(obj, dict):
            # Check if this looks like a Score object (has 'history' but no 'value')
            if (
                "history" in obj
                and "value" not in obj
                and isinstance(obj["history"], list)
            ):
                # This is a Score object that wasn't properly serialized
                # Extract the value from the latest history entry
                history = obj["history"]
                if history:
                    latest = history[-1]
                    if isinstance(latest, dict) and "value" in latest:
                        # Reconstruct the score with backward-compatible fields
                        obj["value"] = latest["value"]
                        obj["answer"] = latest.get("answer")
                        obj["explanation"] = latest.get("explanation")
                        obj["metadata"] = latest.get("metadata", {})

            # Recursively fix nested objects
            return {k: fix_scores(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [fix_scores(item) for item in obj]
        else:
            return obj

    return cast(dict[str, JsonValue], fix_scores(result))


def list_as_str(x: JsonValue) -> str:
    return ",".join([str(e) for e in (x if isinstance(x, list) else [x])])


def remove_namespace(x: JsonValue) -> JsonValue:
    if isinstance(x, str):
        parts = x.split("/", maxsplit=1)
        if len(parts) == 1:
            return parts[0]
        else:
            return parts[1]
    else:
        return x


def score_values(x: JsonValue) -> dict[str, JsonValue]:
    scores = cast(dict[str, Any], x)
    result = {}
    for k, v in scores.items():
        if hasattr(v, "value"):
            # v is a Score object, access the value property
            result[k] = v.value
        elif isinstance(v, dict) and "value" in v:
            # v is a dictionary (old format or raw data)
            result[k] = v["value"]
        else:
            # Fallback: treat v as the value itself
            result[k] = v
    return result


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
