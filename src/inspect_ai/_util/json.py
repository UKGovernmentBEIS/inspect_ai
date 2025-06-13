from typing import (
    Any,
    Literal,
    cast,
)

import jsonpatch
from pydantic import BaseModel, Field, JsonValue
from pydantic_core import PydanticSerializationError, to_json, to_jsonable_python

JSONType = Literal["string", "integer", "number", "boolean", "array", "object", "null"]
"""Valid types within JSON schema."""


def jsonable_python(x: Any) -> Any:
    return to_jsonable_python(x, exclude_none=True, fallback=lambda _x: None)


def jsonable_dict(x: Any) -> dict[str, JsonValue]:
    x = to_jsonable_python(x, exclude_none=True, fallback=lambda _x: None)
    if isinstance(x, dict):
        return x
    else:
        raise TypeError(
            f"jsonable_dict must be passed an object with fields (type passed was {type(x)})"
        )


def to_json_safe(x: Any) -> bytes:
    def clean_utf8_json(obj: Any) -> Any:
        if isinstance(obj, str):
            return obj.encode("utf-8", errors="replace").decode("utf-8")
        elif isinstance(obj, dict):
            return {k: clean_utf8_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_utf8_json(item) for item in obj]
        return obj

    try:
        return to_json(value=x, indent=2, exclude_none=True, fallback=lambda _x: None)
    except PydanticSerializationError as ex:
        if "surrogates not allowed" in str(ex):
            cleaned = clean_utf8_json(x)
            return to_json(cleaned)
        raise


def to_json_str_safe(x: Any) -> str:
    return to_json_safe(x).decode()


def python_type_to_json_type(python_type: str | None) -> JSONType:
    match python_type:
        case "str":
            return "string"
        case "int":
            return "integer"
        case "float":
            return "number"
        case "bool":
            return "boolean"
        case "list":
            return "array"
        case "dict":
            return "object"
        case "None":
            return "null"
        # treat 'unknown' as string as anything can be converted to string
        case None:
            return "string"
        case _:
            raise ValueError(
                f"Unsupported type: {python_type} for Python to JSON conversion."
            )


class JsonChange(BaseModel):
    """Describes a change to data using JSON Patch format."""

    op: Literal["remove", "add", "replace", "move", "test", "copy"]
    """Change operation."""

    path: str
    """Path within object that was changed (uses / to delimit levels)."""

    from_: str | None = Field(default=None, alias="from")
    """Location from which data was moved or copied."""

    value: JsonValue = Field(default=None, exclude=False)
    """Changed value."""

    replaced: JsonValue = Field(default=None, exclude=False)
    """Replaced value."""

    model_config = {"populate_by_name": True}


def json_changes(
    before: dict[str, Any], after: dict[str, Any]
) -> list[JsonChange] | None:
    patch = jsonpatch.make_patch(before, after)
    if patch:
        changes: list[JsonChange] = []
        for change in cast(list[Any], patch):
            json_change = JsonChange(**change)
            if json_change.op == "replace":
                paths = json_change.path.split("/")[1:]
                replaced = before
                for path in paths:
                    decoded_path = decode_json_pointer_segment(path)
                    if isinstance(replaced, list):
                        if not decoded_path.isnumeric():
                            raise ValueError(
                                f"Invalid JSON Pointer segment for list: {decoded_path}"
                            )
                        index = int(decoded_path)
                    else:
                        index = decoded_path
                    replaced = replaced[index]
                json_change.replaced = replaced
            changes.append(json_change)
        return changes
    else:
        return None


def decode_json_pointer_segment(segment: str) -> str:
    """Decode a single JSON Pointer segment."""
    # JSON points encode ~ and / because they are special characters
    # this decodes these values (https://www.rfc-editor.org/rfc/rfc6901)
    return segment.replace("~1", "/").replace("~0", "~")
