import json
from datetime import date, datetime, time, timezone
from typing import Any, Callable, Literal, Type, cast, overload

import yaml
from jsonpath_ng import JSONPath  # type: ignore
from jsonpath_ng.ext import parse  # type: ignore
from pydantic import JsonValue

from .types import ColumnError, Columns, ColumnType


@overload
def import_record(
    record: dict[str, JsonValue],
    columns: Columns,
    dry_run: Literal[False] = False,
) -> dict[str, ColumnType]: ...


@overload
def import_record(
    record: dict[str, JsonValue],
    columns: Columns,
    dry_run: Literal[True],
) -> list[ColumnError]: ...


def import_record(
    record: dict[str, JsonValue],
    columns: Columns,
    dry_run: bool = False,
) -> dict[str, ColumnType] | list[ColumnError]:
    # return values
    result: dict[str, ColumnType] = {}
    errors: list[ColumnError] = []

    # helper to record a field w/ optional type checking/coercion
    def set_result(
        name: str,
        path: JSONPath,
        value: JsonValue,
        type_: Type[ColumnType] | None = None,
    ) -> None:
        try:
            result[name] = _resolve_value(value, type_)
        except ValueError as ex:
            error = ColumnError(name, path=path, message=str(ex))
            if dry_run:
                errors.append(error)
            else:
                raise ValueError(str(error))

    # helper to raise or record errror
    def field_not_found(
        name: str, json_path: JSONPath, required_type: str | None = None
    ) -> None:
        condition = f"of type {required_type}" if required_type else "found"
        error = ColumnError(name, path=str(json_path), message=f"not {condition}")
        if dry_run:
            errors.append(error)
        else:
            raise ValueError(str(error))

    # process each column
    for name, column in columns.items():
        # resolve path
        if isinstance(column.path, str):
            try:
                json_path = parse(column.path)
            except Exception as ex:
                error = ColumnError(
                    name,
                    path=column.path,
                    message=f"Error parsing JSON path expression: {ex}",
                )
                if dry_run:
                    errors.append(error)
                    continue
                else:
                    raise ValueError(str(error))

        else:
            json_path = column.path

        # find matches
        matches = json_path.find(record)

        # handle wildcard vs. no wildcard
        if name.endswith("*"):
            if matches and matches[0].value is not None:
                match = matches[0]
                if isinstance(match.value, dict):
                    # flatten dictionary keys into separate fields
                    base_name = name.replace("*", "")
                    for key, value in match.value.items():
                        set_result(f"{base_name}{key}", json_path, value, column.type)
                else:
                    field_not_found(name, json_path, "dict")
            elif column.required:
                field_not_found(name, json_path)
        else:
            if matches:
                set_result(name, json_path, matches[0].value, column.type)
            elif column.required:
                field_not_found(name, json_path)
            else:
                result[name] = None

    if dry_run:
        return errors
    else:
        return result


def _resolve_value(
    value: JsonValue,
    type_: Type[ColumnType] | None = None,
) -> ColumnType:
    """
    Coerce *value* to *type_* (if supplied).

    Supported conversions
    ---------------------
    * Normal Python constructor coercion (`int("5")`, `str(3.14)` …)
    * Strings through YAML (handles "`true`", "`3.2`", "`2025-05-01`", …)
    * ISO-8601 strings to ``date``, ``time``, ``datetime``
    * POSIX timestamps (int/float **or** numeric string) → temporal types
    * When *value* is a ``list`` or ``dict`` **and** either
        - *type_* is ``str`` **or**
        - *type_* is ``None`` (unspecified),
      the structure is serialised with `json.dumps`
    """
    ## reflect none back
    if value is None:
        return None

    # auto-stringify compound types
    if isinstance(value, list | dict) and (type_ is None or type_ is str):
        return json.dumps(value)

    # we have now narrowed the value to not be none or a compound type
    value = cast(int | str | float | bool, value)

    # no target type or None → nothing to do
    if type_ is None:
        return value

    # already correct
    if isinstance(value, type_) and not _is_bool_int_mismatch(type_, value):
        return value

    # numeric timestamp → temporal
    if isinstance(value, int | float):
        coerced = _from_timestamp(type_, value)
        if coerced is not None:
            return coerced

    # straight constructor
    coerced = _try_constructor(type_, value)
    if coerced is not None:
        return coerced

    # 4) string handling (YAML, ISO, numeric-string timestamp, …)
    if isinstance(value, str):
        coerced = _coerce_from_str(type_, value)
        if coerced is not None:
            return coerced

    # give up
    raise ValueError(
        f"Cannot coerce {value} from type {type(value).__name__}) to {type_.__name__}"
    )


def _is_bool_int_mismatch(tp: Type[ColumnType], obj: Any) -> bool:
    """True when an *int* coercion would silently produce a *bool* (undesired)."""
    return tp is int and isinstance(obj, bool)


def _try_constructor(tp: Type[ColumnType], obj: Any) -> ColumnType:
    """Run `tp(obj)` but swallow any exception, return None on failure."""
    # Constructors of date / time / datetime require ≥3 positional ints, so don’t even try them.
    if tp in (date, time, datetime):
        return None

    # reflect None back
    if obj is None:
        return obj

    try:
        coerced = tp(obj)  # type: ignore[call-arg, misc]
    except Exception:
        return None
    return None if _is_bool_int_mismatch(tp, coerced) else coerced


def _from_timestamp(tp: Type[ColumnType], ts: int | float) -> ColumnType | None:
    """Convert POSIX timestamp to the requested temporal type, UTC zone."""
    if tp is datetime:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if tp is date:
        return date.fromtimestamp(ts)
    if tp is time:  # derive from a datetime
        return datetime.fromtimestamp(ts, tz=timezone.utc).time()
    return None


def _coerce_from_str(tp: Type[ColumnType], text: str) -> ColumnType:
    """
    Best-effort coercion from *text* to *tp*:

    1. YAML parsing (catches booleans, numbers, ISO timestamps, …)
    2. `fromisoformat` when available on the target class
    3. Numeric-string → POSIX timestamp (for temporal targets)
    4. Constructor fall-back
    """
    # 1) YAML
    try:
        parsed = yaml.safe_load(text)
    except Exception:
        parsed = None

    if parsed is not None:
        # exact match?
        if isinstance(parsed, tp) and not _is_bool_int_mismatch(tp, parsed):
            return cast(ColumnType, parsed)
        # try constructor on the YAML result (e.g. str→float via YAML "1.5")
        coerced = _try_constructor(tp, parsed)
        if coerced is not None:
            return coerced

    # 2) fromisoformat — only on temporal types and str itself
    from_iso: Callable[[str], datetime] | None = getattr(tp, "fromisoformat", None)
    if callable(from_iso):
        try:
            return from_iso(text)
        except Exception:
            pass

    # 3) numeric string timestamp?
    try:
        tstmp = float(text)
    except ValueError:
        tstmp = None
    if tstmp is not None:
        coerced = _from_timestamp(tp, tstmp)
        if coerced is not None:
            return coerced

    # 4) plain constructor last
    return _try_constructor(tp, text)
