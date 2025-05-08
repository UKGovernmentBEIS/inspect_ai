import hashlib
import uuid
from typing import Any, cast

import shortuuid
from pydantic import BaseModel, JsonValue

from inspect_ai._util.json import jsonable_python


def model_to_record(model: BaseModel) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], jsonable_python(model))


def list_as_str(x: JsonValue) -> str:
    return ",".join([str(e) for e in (x if isinstance(x, list) else [x])])


def score_values(x: JsonValue) -> dict[str, JsonValue]:
    scores = cast(dict[str, Any], x)
    return {k: v["value"] for k, v in scores.items()}


def input_as_str(x: JsonValue) -> str:
    if isinstance(x, str):
        return x
    else:
        return messages_as_str(x)


def messages_as_str(x: JsonValue) -> str:
    if isinstance(x, list):
        messages = cast(list[dict[str, Any]], x)
        return "\n\n".join([message_as_str(message) for message in messages])
    else:
        raise ValueError(f"Unexpected type for messages: {type(x)}")


def message_as_str(message: dict[str, Any]) -> str:
    return f"{message['role']}:\n{content_as_str(message['content'])}"


def content_as_str(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    else:
        return "\n".join([c["text"] if c["type"] == "text" else "" for c in content])


def auto_id(base: str, index: str) -> str:
    seed = f"{base}_{index}"
    hash_bytes = hashlib.md5(seed.encode("utf-8")).digest()
    long_uuid = uuid.UUID(bytes=hash_bytes)
    return shortuuid.encode(long_uuid)
