import json
from datetime import date, datetime, time, timezone
from typing import Any, Callable, Literal, Sequence, Type, cast, overload

import yaml
from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue

from inspect_ai.analysis.beta._dataframe.events.columns import EventColumn
from inspect_ai.analysis.beta._dataframe.messages.columns import MessageColumn
from inspect_ai.analysis.beta._dataframe.samples.columns import SampleColumn
from inspect_ai.log._log import EvalLog, EvalSample, EvalSampleSummary
from inspect_ai.log._transcript import BaseEvent, Event
from inspect_ai.model._chat_message import ChatMessage, ChatMessageBase

from .columns import Column, ColumnError, ColumnType
from .evals.columns import EvalColumn
from .extract import model_to_record


@overload
def import_record(
    log: EvalLog,
    record: EvalLog
    | EvalSampleSummary
    | EvalSample
    | ChatMessage
    | Event
    | dict[str, JsonValue],
    columns: Sequence[Column],
    strict: Literal[True] = True,
) -> dict[str, ColumnType]: ...


@overload
def import_record(
    log: EvalLog,
    record: EvalLog
    | EvalSampleSummary
    | EvalSample
    | ChatMessage
    | Event
    | dict[str, JsonValue],
    columns: Sequence[Column],
    strict: Literal[False],
) -> tuple[dict[str, ColumnType], list[ColumnError]]: ...


def import_record(
    log: EvalLog,
    record: EvalLog
    | EvalSampleSummary
    | EvalSample
    | ChatMessage
    | Event
    | dict[str, JsonValue],
    columns: Sequence[Column],
    strict: bool = True,
) -> dict[str, ColumnType] | tuple[dict[str, ColumnType], list[ColumnError]]:
    # resolve the record BaseModel into a dict (and optionally a summary dict).
    # summary dict will be required in the case that record is for samples.
    # we also want to save the original BaseModel (if any) for playing back
    # to columns that yield their value using a callable.
    record_target = record
    record_summary: dict[str, JsonValue] | None = None
    if isinstance(record, EvalSample):
        record_summary = model_to_record(record.summary())
        record = model_to_record(record)
    elif isinstance(record, EvalSampleSummary):
        record_summary = model_to_record(record)
        record = record_summary
    elif isinstance(record, EvalLog | ChatMessageBase | BaseEvent):
        record = model_to_record(record)
    else:
        record = record

    # return values
    result: dict[str, ColumnType] = {}
    errors: list[ColumnError] = []

    # helper to record a field w/ optional type checking/coercion
    def set_result(name: str, column: Column, value: JsonValue) -> None:
        try:
            result[name] = _resolve_value(value, column.type)
        except ValueError as ex:
            error = ColumnError(name, path=column.path, error=ex, log=log)
            if strict:
                raise ValueError(str(error))
            else:
                errors.append(error)

    # helper to raise or record errror
    def field_not_found(
        name: str, path: JSONPath | None, required_type: str | None = None
    ) -> None:
        ex = ValueError(
            f"field not of type {required_type}" if required_type else "field not found"
        )
        error = ColumnError(name, path=path, error=ex, log=log)
        if strict:
            raise ValueError(str(error))
        else:
            errors.append(error)

    # process each column
    for column in columns:
        # start with none
        value: JsonValue = None

        # resolve path
        try:
            # read by path or extract function
            if column.path is not None:
                if not column.validate_path():
                    raise ValueError("Specified path is not valid")
                # sample columns may read from summary of full sample
                if isinstance(column, SampleColumn):
                    matches = column.path.find(
                        record if column._full else record_summary
                    )
                else:
                    matches = column.path.find(record)

                if matches:
                    value = matches[0].value
            # some eval columns yield their value with an extract function
            elif (
                isinstance(column, EvalColumn)
                and column._extract_eval is not None
                and isinstance(record_target, EvalLog)
            ):
                value = column._extract_eval(record_target)
            # some sample columns yield their value with an extract function
            elif (
                isinstance(column, SampleColumn)
                and column._extract_sample is not None
                and isinstance(record_target, EvalSample | EvalSampleSummary)
            ):
                value = column._extract_sample(record_target)  # type: ignore[arg-type]
            elif (
                isinstance(column, MessageColumn)
                and column._extract_message is not None
                and isinstance(record_target, ChatMessageBase)
            ):
                value = column._extract_message(record_target)
            elif (
                isinstance(column, EventColumn)
                and column._extract_event is not None
                and isinstance(record_target, BaseEvent)
            ):
                value = column._extract_event(record_target)
            else:
                raise ValueError("column must have path or extract function")

            # call value function on column if it exists
            if value is not None:
                value = column.value(value)

        except Exception as ex:
            error = ColumnError(
                column.name,
                path=str(column.path) if column.path else None,
                error=ex,
                log=log,
            )
            if strict:
                raise ValueError(str(error))
            else:
                errors.append(error)
                continue

        # provide default if None
        if value is None and column.default is not None:
            value = column.default

        # check for required
        if column.required and value is None:
            field_not_found(column.name, column.path)

        # handle wildcard vs. no wildcard
        if column.name.endswith("*"):
            values = value if isinstance(value, list) else [value]
            for value in values:
                expanded = _expand_fields(column.name, value)
                for k, v in expanded.items():
                    set_result(k, column, v)
        else:
            set_result(column.name, column, value)

    # optionally return errors if we aren't in strict mode
    if strict:
        return result
    else:
        return result, errors


def resolve_duplicate_columns(columns: Sequence[Column]) -> list[Column]:
    """Remove duplicate columns (with the later columns winning)"""
    seen = set[str]()
    deduped: list[Column] = []
    for col in reversed(columns):
        if col.name not in seen:
            deduped.append(col)
            seen.add(col.name)
    deduped.reverse()
    return deduped


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


def _expand_fields(name: str, value: JsonValue) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}

    # Base case: no asterisks in the field name
    if "*" not in name:
        result[name] = value
        return result

    # If there's an asterisk but value isn't a dictionary, we can't expand
    if not isinstance(value, dict):
        # Handle this case - either return empty dict, skip it, or use a default name
        # For now, I'll just return an empty dict
        return result

    # Get the position of the first asterisk
    asterisk_pos = name.find("*")
    prefix = name[:asterisk_pos]
    suffix = name[asterisk_pos + 1 :]

    # recursive case: expand each key in the dictionary
    for key, val in value.items():
        new_field = prefix + key + suffix
        # recursively expand any remaining asterisks
        if "*" in suffix:
            if isinstance(val, dict):
                expanded = _expand_fields(new_field, val)
                result.update(expanded)
            # If suffix has '*' but val is not a dict, skip it
            else:
                pass
        else:
            result[new_field] = val

    return result
