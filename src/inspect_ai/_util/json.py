import json
import math
from typing import (
    TYPE_CHECKING,
    Any,
    Iterable,
    Literal,
    Mapping,
    TypeAlias,
)

import ijson  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, JsonValue
from pydantic_core import PydanticSerializationError, to_json, to_jsonable_python

if TYPE_CHECKING:
    from ijson import IncompleteJSONError  # type: ignore[import-untyped]
    from ijson.backends.python import UnexpectedSymbol  # type: ignore[import-untyped]


def exceeds_max_depth(value: object, max_depth: int) -> bool:
    """Whether `value` nests containers deeper than `max_depth` levels.

    Iterative traversal (explicit stack) so that measuring the depth of an
    adversarially deep value can't itself exhaust the interpreter stack.
    `BaseModel` values are descended into via their fields, including the
    extra fields of `extra="allow"` models (pydantic-core serializes both
    recursively, so their nesting counts toward the depth a serializer must
    tolerate).

    A container already expanded at an equal-or-greater depth is not expanded
    again (tracked by `id()`): everything below it was already measured from at
    least as deep, so it cannot newly exceed the limit. Without this, a
    structure that shares sub-containers across many paths — a directed acyclic
    graph, e.g. the aliased nodes `yaml.safe_load` produces from
    anchors/aliases — would be re-expanded combinatorially, turning a
    sub-kilobyte input into billions of visits and an uninterruptible CPU hang.
    It also makes traversal terminate on reference cycles. Re-expansion at a
    strictly greater depth is required for correctness (a shared node reached
    by a longer path can push its subtree past the limit) and stays bounded:
    depth only ever increases, and `max_depth` short-circuits the walk.
    """
    # container id -> greatest depth it has already been expanded from
    expanded_at: dict[int, int] = {}
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if isinstance(current, dict):
            children: Iterable[object] = current.values()
        elif isinstance(current, (list, tuple, set, frozenset)):
            children = current
        elif isinstance(current, BaseModel):
            # extra="allow" values live in __pydantic_extra__, not __dict__
            extra = current.__pydantic_extra__
            children = (
                current.__dict__.values()
                if not extra
                else [*current.__dict__.values(), *extra.values()]
            )
        else:
            continue
        if depth > max_depth:
            return True
        seen_at = expanded_at.get(id(current))
        if seen_at is not None and seen_at >= depth:
            continue
        expanded_at[id(current)] = depth
        stack.extend((child, depth + 1) for child in children)
    return False


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
        # yajl2 rejects the leading minus of -Infinity before seeing the token
        or "a digit is required after the minus sign" in error_msg
    )


def is_ijson_int_overflow_error(
    ex: "ValueError | IncompleteJSONError | UnexpectedSymbol",
) -> bool:
    """Check if an ijson exception is due to an integer larger than 2**63 - 1.

    The ijson C backend (yajl2_c) with use_float=True parses integers into a
    C long long and raises "integer overflow" for anything bigger, even though
    such integers are valid JSON and parse fine with the stdlib json module.
    This helper identifies these errors so callers can fall back to json.load.

    Args:
        ex: Exception from ijson parsing (ValueError, IncompleteJSONError,
            or UnexpectedSymbol).

    Returns:
        True if the exception is due to integer overflow.
    """
    return "integer overflow" in str(ex).lower()


def get_ijson_backend() -> Any:
    """Return an ijson module compatible with the current async backend.

    The default yajl2_c C backend implements ``parse_async`` with
    asyncio-specific yields, which crash under trio. Fall back to the
    pure-Python backend when running under trio so that async readers
    (e.g. ``read_eval_log_async(..., exclude_fields=...)``) work there.
    """
    import sniffio

    try:
        if sniffio.current_async_library() == "trio":
            import ijson.backends.python as ijson_py  # type: ignore[import-untyped]

            return ijson_py
    except sniffio.AsyncLibraryNotFoundError:
        pass
    return ijson


class ExcludingObjectBuilder:
    """Build a JSON object from ijson events, skipping excluded top-level keys.

    The counterpart of ijson's ``ObjectBuilder`` for reading a large object
    selectively: feed it the ``(event, value)`` pairs a streaming parse
    yields, and ``data`` holds the included top-level fields when the parse
    ends. An excluded key's subtree is never built, so it costs no memory.
    """

    def __init__(self, exclude_fields: set[str]) -> None:
        self.data: dict[str, Any] = {}
        self._excluded = exclude_fields
        self._depth = 0
        self._key = ""
        self._builder: Any | None = None

    def event(self, event: str, value: Any) -> None:
        if event in ("start_map", "start_array"):
            self._depth += 1
        elif event in ("end_map", "end_array"):
            self._depth -= 1

        if self._depth == 1 and event == "map_key":
            self._key = value
            self._builder = None if value in self._excluded else ijson.ObjectBuilder()
        elif self._builder is not None:
            self._builder.event(event, value)
            if self._depth == 1:
                self.data[self._key] = self._builder.value
                self._builder = None


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
    indent: int | None = 2,
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
            indent=indent,
            exclude_none=True,
            fallback=lambda _x: None,
            exclude=exclude,
        )
    except PydanticSerializationError as ex:
        if "surrogates not allowed" in str(ex):
            cleaned = clean_utf8_json(normalized)
            return to_json(
                cleaned,
                indent=indent,
                exclude_none=True,
                fallback=lambda _x: None,
                exclude=exclude,
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


JsonChangeOp = Literal["remove", "add", "replace", "move", "test", "copy"]


class JsonChange(BaseModel):
    """Describes a change to data using JSON Patch format."""

    op: JsonChangeOp
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


def _json_pointer_join(path: str, key: str | int) -> str:
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _replace_change(path: str, value: Any, replaced: Any) -> JsonChange:
    change = JsonChange(op="replace", path=path, value=value)
    # assigned without validation, since validating a deeply nested old value
    # exceeds pydantic's recursion limit
    change.replaced = replaced
    return change


def _same_list_item(old: Any, new: Any) -> bool:
    """`old == new`, except that NaN equals NaN at any depth.

    Snapshots serialized separately hold distinct NaN objects, and NaN != NaN.
    Callers try `==` first, so this walk only runs for items it finds unequal.
    """
    if old == new:
        return True
    if isinstance(old, float) and isinstance(new, float):
        return math.isnan(old) and math.isnan(new)
    if isinstance(old, dict) and isinstance(new, dict):
        return old.keys() == new.keys() and all(
            _same_list_item(value, new[key]) for key, value in old.items()
        )
    if isinstance(old, list) and isinstance(new, list):
        return len(old) == len(new) and all(
            _same_list_item(a, b) for a, b in zip(old, new)
        )
    return False


def _diff_values(path: str, before: Any, after: Any, changes: list[JsonChange]) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        for key in before:
            if key not in after:
                changes.append(
                    JsonChange(op="remove", path=_json_pointer_join(path, key))
                )
        for key, value in after.items():
            if key not in before:
                changes.append(
                    JsonChange(
                        op="add", path=_json_pointer_join(path, key), value=value
                    )
                )
        for key, value in before.items():
            if key in after:
                _diff_values(_json_pointer_join(path, key), value, after[key], changes)
    elif isinstance(before, list) and isinstance(after, list):
        # leave the items both lists end with alone, so an insert or removal
        # does not replace every item after it
        end_before, end_after = len(before), len(after)
        while (
            end_before
            and end_after
            and (
                before[end_before - 1] == after[end_after - 1]
                or _same_list_item(before[end_before - 1], after[end_after - 1])
            )
        ):
            end_before -= 1
            end_after -= 1
        common = min(end_before, end_after)
        for index in range(common):
            old, new = before[index], after[index]
            if old == new or _same_list_item(old, new):
                continue
            item_path = _json_pointer_join(path, index)
            if (isinstance(old, dict) and isinstance(new, dict)) or (
                isinstance(old, list) and isinstance(new, list)
            ):
                _diff_values(item_path, old, new, changes)
            else:
                changes.append(_replace_change(item_path, new, old))
        # removals and inserts come last, so they shift no index an earlier
        # change used
        for _ in range(common, end_before):
            changes.append(
                JsonChange(op="remove", path=_json_pointer_join(path, common))
            )
        for index in range(common, end_after):
            changes.append(
                JsonChange(
                    op="add", path=_json_pointer_join(path, index), value=after[index]
                )
            )
    elif json.dumps(before) != json.dumps(after):
        changes.append(_replace_change(path, after, before))


def json_changes(
    before: dict[str, Any] | list[Any], after: dict[str, Any] | list[Any]
) -> list[JsonChange] | None:
    """Calculates JSON changes including the 'replaced' value for replace operations.

    The changes are JSON Patch operations (plus the value each 'replace'
    overwrote) that turn `before` into `after` when applied in order.

    Dicts are compared key by key. Lists are compared index by index after
    skipping the items both lists end with, and the extra items of the longer
    list are then removed or added, so inserting or removing one item gives one
    change.
    Values compare as in `jsonpatch.make_patch()`, except that NaN equals NaN,
    so an unchanged NaN gives no change.

    Unlike `make_patch()`, this never pairs a removed value with an equal added
    value into a 'move': jsonpatch does not adjust the indices of such moves
    across containers, so they can produce invalid paths or a patch that does
    not reproduce `after`. `make_patch()` has no option to turn moves off, so
    the comparison is done here. Without moves no operation shifts an index
    that a later operation reads, so each 'replaced' value comes straight from
    `before`.

    Args:
        before: The original dictionary.
        after: The modified dictionary.

    Returns:
        A list of JsonChange objects (which mimic JSON patch ops but include the 'replaced' field), or None if there are no changes.
    """
    changes: list[JsonChange] = []
    _diff_values("", before, after, changes)
    return changes or None
