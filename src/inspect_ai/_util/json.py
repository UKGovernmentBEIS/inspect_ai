import json
import re
from collections.abc import Iterator
from copy import deepcopy
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Mapping,
    TypeAlias,
)

import jsonpatch

if TYPE_CHECKING:
    from ijson import IncompleteJSONError  # type: ignore[import-untyped]
    from ijson.backends.python import UnexpectedSymbol  # type: ignore[import-untyped]
from jsonpointer import (  # type: ignore  # jsonpointer is already a dependency of jsonpatch
    JsonPointerException,
    resolve_pointer,
)
from pydantic import BaseModel, Field, JsonValue
from pydantic_core import PydanticSerializationError, to_json, to_jsonable_python

# Pre-compile regex to quickly find paths ending in an index for json_changes (e.g., /items/0)
_ARRAY_INDEX_RE = re.compile(r"^(.*)/(\d+)$")


def is_ijson_nan_inf_error(
    ex: "ValueError | IncompleteJSONError | UnexpectedSymbol",
) -> bool:
    """Check if an ijson exception is due to NaN/Inf values.

    ijson doesn't support NaN and Inf which are valid in Python's JSON
    (and supported by pydantic). This helper identifies these errors so
    callers can fall back to standard json.load.

    Args:
        ex: Exception from ijson parsing (ValueError, IncompleteJSONError,
            or UnexpectedSymbol).

    Returns:
        True if the exception is due to NaN/Inf parsing issues.
    """
    error_msg = str(ex).lower()
    return (
        "invalid json character" in error_msg
        or "invalid char in json text" in error_msg
        or "unexpected symbol" in error_msg
    )


def load_json_exclude(f: Any, exclude_fields: set[str]) -> dict[str, Any]:
    """Load a JSON object from a file, skipping excluded top-level fields.

    Uses ijson for streaming parse so excluded fields (e.g. large ``events``
    arrays) are never materialised.  Falls back to ``json.load`` when ijson
    encounters NaN/Inf values it cannot handle.
    """
    import ijson  # type: ignore
    from ijson import IncompleteJSONError
    from ijson.backends.python import (  # type: ignore[import-untyped]
        UnexpectedSymbol,
    )

    try:
        parser = ijson.parse(f, use_float=True)
        _, event, _ = next(parser)
        if event != "start_map":
            raise ValueError(f"Expected start_map event at root, got: {event}")

        data: dict[str, Any] = {}
        for _, event, value in parser:
            if event == "end_map":
                break
            if event != "map_key":
                raise ValueError(f"Expected map_key event, got: {event}")
            key = value
            if key in exclude_fields:
                _skip_json_value(parser)
            else:
                _, next_event, next_value = next(parser)
                data[key] = _build_json_value(next_event, next_value, parser)
    except (
        ValueError,
        IncompleteJSONError,
        UnexpectedSymbol,
    ) as ex:
        if is_ijson_nan_inf_error(ex):
            f.seek(0)
            data = json.load(f)
            for field in exclude_fields:
                data.pop(field, None)
        else:
            raise
    return data


def _skip_json_value(parser: Iterator[tuple[str, str, Any]]) -> None:
    """Skip the next JSON value from an ijson parse stream without materializing it."""
    _, event, _ = next(parser)
    if event in ("null", "boolean", "number", "string"):
        return
    depth = 1
    for _, event, _ in parser:
        if event in ("start_map", "start_array"):
            depth += 1
        elif event in ("end_map", "end_array"):
            depth -= 1
            if depth == 0:
                return
    raise ValueError("Truncated JSON: unexpected end of stream while skipping value")


def _build_json_value(
    event: str, value: Any, parser: Iterator[tuple[str, str, Any]]
) -> Any:
    """Build a Python value from an ijson parse stream."""
    if event in ("null", "boolean", "number", "string"):
        return value
    elif event == "start_array":
        arr: list[Any] = []
        for _, ev, val in parser:
            if ev == "end_array":
                return arr
            arr.append(_build_json_value(ev, val, parser))
        raise ValueError("Unterminated JSON array")
    elif event == "start_map":
        obj: dict[str, Any] = {}
        for _, ev, val in parser:
            if ev == "end_map":
                return obj
            if ev != "map_key":
                raise ValueError(f"Expected map_key event, got: {ev}")
            key = val
            _, next_ev, next_val = next(parser)
            obj[key] = _build_json_value(next_ev, next_val, parser)
        raise ValueError("Unterminated JSON object")
    raise ValueError(f"Unexpected ijson event: {event}")


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


_IncEx: TypeAlias = (
    set[int] | set[str] | Mapping[int, "_IncEx | bool"] | Mapping[str, "_IncEx | bool"]
)


def to_json_safe(
    x: Any,
    exclude: _IncEx | None = None,
) -> bytes:
    normalized = jsonable_python(x)

    def clean_utf8_json(obj: Any) -> Any:
        if isinstance(obj, str):
            return obj.encode("utf-8", errors="backslashreplace").decode("utf-8")
        elif isinstance(obj, dict):
            return {k: clean_utf8_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_utf8_json(item) for item in obj]
        return obj

    try:
        return to_json(
            value=normalized,
            indent=2,
            exclude_none=True,
            fallback=lambda _x: None,
            exclude=exclude,
        )
    except PydanticSerializationError as ex:
        if "surrogates not allowed" in str(ex):
            cleaned = clean_utf8_json(normalized)
            return to_json(
                cleaned, indent=2, exclude_none=True, fallback=lambda _x: None
            )
        raise


def to_json_str_safe(x: Any) -> str:
    return to_json_safe(x).decode("utf-8")


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


def _get_tracked_containers(patch_list: list[dict[str, Any]]) -> set[str]:
    """Identifies which array paths need state tracking for json_changes.

    We only need to track the state of an array if it undergoes structural changes (add/remove) AND contains a 'replace' operation later in the patch list.
    """
    # Find all arrays being structurally modified (add/remove)
    structural_containers = set()
    for op in patch_list:
        if op["op"] in ("add", "remove"):
            if match := _ARRAY_INDEX_RE.match(op["path"]):
                structural_containers.add(match.group(1))

    # Filter down to only those that actually impact a 'replace' op
    tracked = set()
    if structural_containers:
        for op in patch_list:
            if op["op"] == "replace":
                for container in structural_containers:
                    if op["path"].startswith(container + "/"):
                        tracked.add(container)
                        break
    return tracked


def _get_active_container(
    path: str, tracked_paths: set[str]
) -> tuple[str | None, str | None]:
    """Checks if a specific path belongs to a tracked container for json_changes.

    Returns:
        (container, relative_path_without_slash) e.g., ("/items", "0")
    """
    if not tracked_paths:
        return None, None

    # Find the most specific (longest) matching container to handle nested arrays
    best_match: str | None = None
    for container in tracked_paths:
        if path.startswith(container + "/"):
            if best_match is None or len(container) > len(best_match):
                best_match = container

    if best_match is not None:
        # Return container and the path relative to it (stripping the slash)
        return best_match, path[len(best_match) + 1 :]

    return None, None


def _apply_fast_list_op(target: list[Any], op: dict[str, Any], rel_path: str) -> None:
    """Mutates a list in-place to apply a JSON patch operation efficiently.

    This function optimises the "hot path" by using native Python list methods (.insert, .pop) for simple index operations, avoiding the significant overhead of the jsonpatch library. It falls back to the library for complex paths.

    Args:
        target: The list to mutate.
        op: The patch operation dictionary containing 'op' and 'value'.
        rel_path: The relative path within the list (e.g., "0", "15", "-").
    """
    # Fast path: Simple index (e.g. "0", "15", "-")
    # We check for '/' to ensure it's not a nested path like "0/id"
    if "/" not in rel_path:
        if op["op"] == "add":
            idx = len(target) if rel_path == "-" else int(rel_path)
            target.insert(idx, op["value"])
        elif op["op"] == "remove":
            target.pop(int(rel_path))
    else:
        # Slow path: Complex/Nested path (e.g., "0/details/id")
        # Prepend '/' because jsonpatch requires pointers to start with /
        target[:] = jsonpatch.apply_patch(target, [{**op, "path": "/" + rel_path}])  # type: ignore


def json_changes(
    before: dict[str, Any] | list[Any], after: dict[str, Any] | list[Any]
) -> list[JsonChange] | None:
    """Calculates JSON changes including the 'replaced' value for replace operations.

    Standard JSON Patch does not include the value that was overwritten during a 'replace' operation. This function calculates that value.

    Optimisation Strategy:
        Looking up the 'replaced' value is trivial for static paths. However, if
        an array has items inserted/removed, the indices shift. To resolve the
        correct 'replaced' value, we normally need to apply patches sequentially.

        Instead of deepcopying the entire document (slow), this function identifies
        only the specific arrays that shift and creates small "shadow" copies of
        them. It applies patches to these shadow arrays to track the correct
        indices, whilst ignoring the rest of the document.

    Args:
        before: The original dictionary.
        after: The modified dictionary.

    Returns:
        A list of JsonChange objects (which mimic JSON patch ops but include the 'replaced' field), or None if there are no changes.
    """
    patch_list = list(jsonpatch.make_patch(before, after))
    if not patch_list:
        return None

    # Identify which arrays need isolated tracking
    tracked_paths = _get_tracked_containers(patch_list)

    # Create shadow copies of ONLY those arrays
    # resolve_pointer handles traversing 'before' to find the sub-list.
    shadow_state = {
        path: deepcopy(resolve_pointer(before, path)) for path in tracked_paths
    }

    changes: list[JsonChange] = []

    for op in patch_list:
        container, rel_path = _get_active_container(op["path"], tracked_paths)

        # Calculate the 'replaced' value if this is a 'replace' op
        replaced_val = None
        if op["op"] == "replace":
            source = shadow_state[container] if container else before

            # Ensure lookup_path has a leading slash for resolve_pointer
            if container:
                assert rel_path is not None  # Shouldn't be since container is set
                lookup_path = "/" + rel_path
            else:
                lookup_path = op["path"]

            try:
                replaced_val = resolve_pointer(source, lookup_path)
            except JsonPointerException:
                # Usually implies the path doesn't exist in the shadow state. Just leave replaced_val as None
                pass

        # Update shadow state if the structure changed due to an 'add' or 'remove' op
        if container and op["op"] in ("add", "remove"):
            assert rel_path is not None  # Shouldn't be since container is set
            _apply_fast_list_op(shadow_state[container], op, rel_path)

        # Build Result
        change = JsonChange(**op)
        if op["op"] == "replace":
            change.replaced = replaced_val
        changes.append(change)

    return changes
