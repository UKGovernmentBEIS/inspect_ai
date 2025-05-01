import json
from datetime import date, datetime, time, timezone
from typing import Any, Callable, Literal, Type, cast, overload

import yaml
from jsonpath_ng import (  # type: ignore
    JSONPath,  # type: ignore
    parse,
)
from pydantic import JsonValue

from .spec import FieldOptions, FieldType, ImportSpec


@overload
def import_record(
    record: dict[str, JsonValue],
    spec: ImportSpec | list[ImportSpec],
    raise_on_error: Literal[True] = True,
) -> dict[str, FieldType]: ...


@overload
def import_record(
    record: dict[str, JsonValue],
    spec: ImportSpec | list[ImportSpec],
    raise_on_error: Literal[False],
) -> tuple[dict[str, FieldType], list[str]]: ...


def import_record(
    record: dict[str, JsonValue],
    spec: ImportSpec | list[ImportSpec],
    raise_on_error: bool = True,
) -> dict[str, FieldType] | tuple[dict[str, FieldType], list[str]]:
    # return values
    result: dict[str, FieldType] = {}
    errors: list[str] = []

    # helper to record a field w/ optional type checking/coercion
    def set_result(
        field_name: str,
        value: JsonValue,
        type_: Type[FieldType] | None = None,
    ) -> None:
        try:
            result[field_name] = _resolve_value(field_name, value, type_)
        except ValueError as ex:
            if raise_on_error:
                raise
            else:
                errors.append(repr(ex))

    # helper to raise or record errror
    def field_not_found(
        field_name: str, json_path: JSONPath, required_type: str | None = None
    ) -> None:
        condition = f"of type {required_type}" if required_type else "found"
        error = f"Required field '{field_name}' not {condition} at '{json_path}'"
        if raise_on_error:
            raise ValueError(error)
        else:
            errors.append(error)

    # merge import specs
    if isinstance(spec, list):
        merged_specs: ImportSpec = {}
        for s in spec:
            merged_specs.update(s)
    else:
        merged_specs = spec

    # process each field in turn
    for field_name, field_spec in merged_specs.items():
        # resolve options
        options: FieldOptions = {"required": False, "type": None}
        if isinstance(field_spec, tuple):
            path_spec, opts = field_spec
            options.update(opts)
        else:
            path_spec = field_spec

        # resolve path
        if isinstance(path_spec, str):
            try:
                json_path = parse(path_spec)
            except Exception as ex:
                error = f"Error parsing JSON path expression: {path_spec}: {ex}"
                if raise_on_error:
                    raise ValueError(error)
                else:
                    errors.append(error)
                    continue
        else:
            json_path = path_spec

        # find matches
        matches = json_path.find(record)

        # handle wildcard vs. no wildcard
        if field_name.endswith("*"):
            if matches and matches[0].value is not None:
                match = matches[0]
                if isinstance(match.value, dict):
                    # flatten dictionary keys into separate fields
                    base_name = field_name.replace("*", "")
                    for key, value in match.value.items():
                        col_name = f"{base_name}{key}"
                        set_result(col_name, value, options.get("type", None))
                else:
                    field_not_found(field_name, json_path, "dict")
            else:
                field_not_found(field_name, json_path)
        else:
            if matches:
                set_result(field_name, matches[0].value, options.get("type", None))
            elif options["required"]:
                field_not_found(field_name, json_path)
            else:
                result[field_name] = None

    if raise_on_error:
        return result
    else:
        return result, errors


def _resolve_value(
    field_name: str,
    value: JsonValue,
    type_: Type[FieldType] | None = None,
) -> FieldType:
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
        f"Field {field_name!r}: cannot coerce {value!r} "
        f"(type {type(value).__name__}) to {type_.__name__}"
    )


def _is_bool_int_mismatch(tp: Type[FieldType], obj: Any) -> bool:
    """True when an *int* coercion would silently produce a *bool* (undesired)."""
    return tp is int and isinstance(obj, bool)


def _try_constructor(tp: Type[FieldType], obj: Any) -> FieldType:
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


def _from_timestamp(tp: Type[FieldType], ts: int | float) -> FieldType | None:
    """Convert POSIX timestamp to the requested temporal type, UTC zone."""
    if tp is datetime:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if tp is date:
        return date.fromtimestamp(ts)
    if tp is time:  # derive from a datetime
        return datetime.fromtimestamp(ts, tz=timezone.utc).time()
    return None


def _coerce_from_str(tp: Type[FieldType], text: str) -> FieldType:
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
            return cast(FieldType, parsed)
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
