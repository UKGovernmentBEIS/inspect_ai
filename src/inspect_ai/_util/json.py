from typing import (
    Any,
    Literal,
    cast,
)

import jsonpatch
from pydantic import BaseModel, Field, JsonValue
from pydantic_core import to_jsonable_python


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
                    index: Any = (
                        int(decoded_path) if decoded_path.isnumeric() else decoded_path
                    )
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
