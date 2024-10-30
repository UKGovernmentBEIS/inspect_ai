import re
from typing import Any, Literal, cast

import jsonpatch
from pydantic import BaseModel, Field, JsonValue
from pydantic_core import to_jsonable_python

JSONType = Literal["string", "integer", "number", "boolean", "array", "object", "null"]

PythonType = Literal["str", "int", "float", "bool", "list", "dict", "None"]


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


def json_type_to_python_type(json_type: str) -> PythonType:
    match json_type:
        case "string":
            return "str"
        case "integer":
            return "int"
        case "number":
            return "float"
        case "boolean":
            return "bool"
        case "array":
            return "list"
        case "object":
            return "dict"
        case "null":
            return "None"
        case _:
            raise ValueError(
                f"Unsupported type: {json_type} for JSON to Python conversion."
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
                    index: Any = int(path) if path.isnumeric() else path
                    replaced = replaced[index]
                json_change.replaced = replaced
            changes.append(json_change)
        return changes
    else:
        return None


def synthesize_comparable(
    changes: list[JsonChange],
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    """
    Renders a view displaying a list of state changes.

    Args:
        changes: The list of changes to be displayed.

    Returns:
        Tuple containing the before and after objects
    """
    before: dict[str, JsonValue] = {}
    after: dict[str, JsonValue] = {}

    for change in changes:
        if change.op == "add":
            # 'Fill in' arrays with empty strings to ensure there is no unnecessary diff
            initialize_arrays(before, change.path)
            initialize_arrays(after, change.path)
            set_path(after, change.path, change.value)
        elif change.op == "copy":
            set_path(before, change.path, change.value)
            set_path(after, change.path, change.value)
        elif change.op == "move":
            if change.from_ is None:
                raise ValueError("'from_' field is required for move operation")
            set_path(before, change.from_, change.value)
            set_path(after, change.path, change.value)
        elif change.op == "remove":
            set_path(before, change.path, change.value)
        elif change.op == "replace":
            set_path(before, change.path, change.replaced)
            set_path(after, change.path, change.value)
        elif change.op == "test":
            pass

    return before, after


JsonCollection = list[JsonValue] | dict[str, JsonValue]


def set_path(target: dict[str, JsonValue], path: str, value: JsonValue) -> None:
    keys = parse_path(path)
    current: JsonCollection = target

    for i in range(len(keys) - 1):
        key = keys[i]

        if key not in current:
            target_value: JsonValue = [] if is_array_index(keys[i + 1]) else {}
            if isinstance(current, dict):
                current[key] = target_value
            else:
                current[int(key)] = target_value

        if isinstance(current, dict):
            current = cast(JsonCollection, current[key])
        else:
            current = cast(JsonCollection, current[int(key)])

    last_key = keys[-1]
    if isinstance(current, dict):
        current[last_key] = value
    else:
        array_key = int(last_key)
        if array_key > (len(current) - 1):
            current.append(value)
        else:
            current[int(last_key)] = value


def initialize_arrays(target: dict[str, JsonValue], path: str) -> None:
    keys = parse_path(path)
    current: JsonCollection = target

    for i in range(len(keys) - 1):
        key = keys[i]
        next_key = keys[i + 1]

        if is_array_index(next_key):
            if isinstance(current, dict):
                existing = current.get(key)
            else:
                existing = current[int(key)] if current else None
            target_value = initialize_array(
                cast(list[JsonValue], existing) if existing is not None else None,
                next_key,
            )
            if isinstance(current, dict):
                current[key] = target_value
            else:
                if current:
                    current[int(key)] = target_value
                else:
                    current.append(target_value)
        else:
            if isinstance(current, dict):
                existing = current.get(key)
            else:
                existing = current[int(key)] if current else None
            target_object_value = initialize_object(
                cast(dict[str, JsonValue], existing) if existing is not None else None
            )
            if isinstance(current, dict):
                current[key] = target_object_value
            else:
                if current:
                    current[int(key)] = target_object_value
                else:
                    current.append(target_object_value)

        if isinstance(current, dict):
            current = cast(JsonCollection, current[key])
        else:
            current = cast(JsonCollection, current[int(key)])

    last_key = keys[-1]
    if is_array_index(last_key):
        initialize_array(cast(list[JsonValue], current), last_key)


def initialize_array(current: list[JsonValue] | None, next_key: str) -> list[JsonValue]:
    current = [] if current is None else current
    next_key_index = int(next_key)
    while len(current) < next_key_index:
        current.append("")
    return current


def initialize_object(current: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    return current if current is not None else {}


def parse_path(path: str) -> list[str]:
    keys = [key for key in path.split("/") if key]
    if not keys:
        raise ValueError("Path cannot be empty")
    return keys


_ARRAY_INDEX_PATTERN = re.compile(r"^\d+$")


def is_array_index(key: str) -> bool:
    return bool(_ARRAY_INDEX_PATTERN.match(key))
