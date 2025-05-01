import json
from datetime import date, datetime, time, timezone

import pytest
from pydantic import JsonValue

from inspect_ai.analysis import EvalDefault, ImportSpec
from inspect_ai.analysis._df.record import _resolve_value, import_record

# ======== Test Data ========
test_record: dict[str, JsonValue] = {
    "id": "foobar",
    "status": "complete",
    "eval": {
        "run_id": "foo",
        "task_id": "bar",
        "task": "foo",
        "task_version": 0,
        "created": 1714640400,
        "model": "openai/gpt-4o",
        "task_args": {"foo": 42, "bar": 84},
    },
    "data": {
        "timestamps": {
            "unix": 1714640400,  # 2024-05-01T09:00:00Z
            "iso": "2024-05-01T12:00:00Z",
        },
        "values": [1, 2, 3, 4],
        "flag": True,
        "extra": "extra",
        "null_value": None,
    },
    "results": {"total_samples": 10, "completed_samples": 10},
    "error": {"message": "Some error occurred"},
}

test_record_no_error = test_record.copy()
del test_record_no_error["error"]

yaml_record: dict[str, JsonValue] = {
    "string_int": "42",
    "string_float": "3.14",
    "string_bool": "true",
    "string_date": "2024-05-01",
    "string_array": "[1, 2, 3]",
}


# ======== Basic Functionality Tests ========
def test_basic_import() -> None:
    """Test basic field import with direct mapping."""
    spec: ImportSpec = {
        "status": "$.status",
        "model": "$.eval.model",
    }

    result = import_record(test_record, spec)

    assert result["status"] == "complete"
    assert result["model"] == "openai/gpt-4o"


def test_wildcard_fields() -> None:
    """Test importing wildcard fields."""
    spec: ImportSpec = {
        "task_arg_*": "$.eval.task_args",
    }

    result = import_record(test_record, spec)

    assert result["task_arg_foo"] == 42
    assert result["task_arg_bar"] == 84


def test_field_options() -> None:
    """Test importing with field options."""
    spec: ImportSpec = {
        "status": ("$.status", {"required": True}),
        "error_msg": ("$.error.message", {"required": False}),
        "missing": ("$.not.existing", {"required": False}),
    }

    result = import_record(test_record, spec)

    assert result["status"] == "complete"
    assert result["error_msg"] == "Some error occurred"
    assert result["missing"] is None


def test_predefined_spec() -> None:
    """Test using the predefined EvalBase spec."""
    result = import_record(test_record_no_error, EvalDefault)

    assert result["status"] == "complete"
    assert result["model"] == "openai/gpt-4o"
    task_args = json.loads(str(result["task_args"]))
    assert task_args["foo"] == 42
    assert task_args["bar"] == 84
    assert result["error_message"] is None


# ======== Type Coercion Tests ========
def test_type_coercion_simple() -> None:
    """Test simple type coercion."""
    spec: ImportSpec = {
        "flag": ("$.data.flag", {"type": bool}),  # will yaml parse bool from 'true'
        "values": ("$.data.values", {"type": str}),  # Will json.dumps
    }

    result = import_record(test_record, spec)
    assert result["flag"] is True
    assert result["values"] == "[1, 2, 3, 4]"


def test_type_coercion_failure() -> None:
    """Test failure with incompatible type coercion."""
    spec: ImportSpec = {
        "status_int": (
            "$.status",
            {"type": int},
        ),  # Will fail - string can't convert to int
    }

    with pytest.raises(ValueError, match="cannot coerce"):
        print(import_record(test_record, spec))


def test_date_time_coercion() -> None:
    """Test date/time coercion."""
    spec: ImportSpec = {
        "timestamp_dt": ("$.data.timestamps.unix", {"type": datetime}),
        "timestamp_d": ("$.data.timestamps.unix", {"type": date}),
        "timestamp_t": ("$.data.timestamps.unix", {"type": time}),
        "iso_dt": ("$.data.timestamps.iso", {"type": datetime}),
    }

    result = import_record(test_record, spec)

    assert isinstance(result["timestamp_dt"], datetime)
    assert result["timestamp_dt"] == datetime.fromtimestamp(1714640400, tz=timezone.utc)

    assert isinstance(result["timestamp_d"], date)
    assert result["timestamp_d"] == date.fromtimestamp(1714640400)

    assert isinstance(result["timestamp_t"], time)
    assert result["timestamp_t"].hour == 9
    assert result["timestamp_t"].minute == 0

    assert isinstance(result["iso_dt"], datetime)
    expected_dt = datetime(2024, 5, 1, 12, 0, 0)
    # Account for timezone differences in comparison
    assert result["iso_dt"].year == expected_dt.year
    assert result["iso_dt"].month == expected_dt.month
    assert result["iso_dt"].day == expected_dt.day
    assert result["iso_dt"].hour == expected_dt.hour


def test_yaml_string_coercion() -> None:
    """Test YAML string coercion."""
    spec: ImportSpec = {
        "int_val": ("$.string_int", {"type": int}),
        "float_val": ("$.string_float", {"type": float}),
        "bool_val": ("$.string_bool", {"type": bool}),
        "date_val": ("$.string_date", {"type": date}),
        "array_val": ("$.string_array", {"type": str}),  # Keep as string
    }

    result = import_record(yaml_record, spec)

    assert result["int_val"] == 42
    assert result["float_val"] == 3.14
    assert result["bool_val"] is True
    assert isinstance(result["date_val"], date)
    assert result["date_val"] == date(2024, 5, 1)
    assert result["array_val"] == "[1, 2, 3]"


# ======== Error Handling Tests ========
def test_required_field_missing() -> None:
    """Test error when required field is missing."""
    spec: ImportSpec = {
        "missing": ("$.not.existing", {"required": True}),
    }

    with pytest.raises(ValueError, match="Required field 'missing' not found"):
        import_record(test_record, spec)


def test_collect_errors() -> None:
    """Test collecting errors instead of raising."""
    spec: ImportSpec = {
        "status": "$.status",
        "missing": ("$.not.existing", {"required": True}),
        "bad_type": ("$.data.extra", {"type": int}),  # str to int will fail
    }

    result, errors = import_record(test_record, spec, strict=False)

    assert result["status"] == "complete"
    assert len(errors) == 2
    assert any("missing" in error for error in errors)
    assert any("cannot coerce" in error for error in errors)


def test_invalid_jsonpath() -> None:
    """Test handling of invalid JSONPath expressions."""
    spec: ImportSpec = {
        "invalid": "$..[*",  # Invalid JSONPath syntax
    }

    with pytest.raises(
        Exception
    ):  # Exception type depends on jsonpath-ng implementation
        import_record(test_record, spec)


# ======== Edge Cases Tests ========
def test_empty_record() -> None:
    """Test importing from an empty record."""
    empty_record: dict[str, JsonValue] = {}

    spec: ImportSpec = {
        "status": ("$.status", {"required": False}),
    }

    result = import_record(empty_record, spec)
    assert result["status"] is None


def test_none_values() -> None:
    """Test handling of None values."""
    none_record: dict[str, JsonValue] = {
        "explicit_none": None,
    }

    spec: ImportSpec = {
        "explicit_none": "$.explicit_none",
        "null_value": "$.data.null_value",
    }

    result = import_record({**test_record, **none_record}, spec)
    assert result["explicit_none"] is None
    assert result["null_value"] is None


def test_multiple_import_specs() -> None:
    """Test importing with multiple import specs."""
    spec1: ImportSpec = {
        "status": "$.status",
    }

    spec2: ImportSpec = {
        "model": "$.eval.model",
    }

    result = import_record(test_record, [spec1, spec2])

    assert result["status"] == "complete"
    assert result["model"] == "openai/gpt-4o"


# ======== Internal Function Tests ========
def test_resolve_value_compound_types() -> None:
    """Test resolving compound values."""
    # List to string
    assert _resolve_value("list_field", [1, 2, 3], str) == "[1, 2, 3]"

    # dict to string
    assert _resolve_value("dict_field", {"a": 1}, str) == '{"a": 1}'

    # None handling
    assert _resolve_value("none_field", None, int) is None


def test_resolve_value_type_coercion() -> None:
    """Test various type coercions in _resolve_value."""
    # Simple types
    assert _resolve_value("int_field", 42, int) == 42
    assert _resolve_value("str_field", "hello", str) == "hello"
    assert _resolve_value("bool_field", True, bool) is True

    # Constructor coercion
    assert _resolve_value("str_to_int", "42", int) == 42
    assert _resolve_value("int_to_str", 42, str) == "42"

    # YAML string coercion
    assert _resolve_value("yaml_bool", "true", bool) is True
    assert _resolve_value("yaml_int", "42", int) == 42
    assert _resolve_value("yaml_float", "3.14", float) == 3.14

    # Timestamp to temporal
    ts_dt = _resolve_value("ts_to_dt", 1714640400, datetime)
    assert isinstance(ts_dt, datetime)
    assert ts_dt.year == 2024

    ts_date = _resolve_value("ts_to_date", 1714640400, date)
    assert isinstance(ts_date, date)
    assert ts_date.year == 2024

    ts_time = _resolve_value("ts_to_time", 1714640400, time)
    assert isinstance(ts_time, time)

    # ISO string to temporal
    iso_str = "2024-05-01T12:00:00Z"
    iso_dt = _resolve_value("iso_to_dt", iso_str, datetime)
    assert isinstance(iso_dt, datetime)

    # Numeric string timestamp
    str_ts = _resolve_value("str_ts_to_dt", "1714640400", datetime)
    assert isinstance(str_ts, datetime)


def test_resolve_value_errors() -> None:
    """Test error handling in _resolve_value."""
    # Type mismatch
    with pytest.raises(ValueError, match="cannot coerce"):
        _resolve_value("str_to_time", "str", time)

    # Incompatible conversion
    with pytest.raises(ValueError, match="cannot coerce"):
        _resolve_value("str_to_int", "not a bool", int)


# ======== Complex Tests ========
def test_complex_import_scenario() -> None:
    """Test a complex import scenario with various field types and options."""
    complex_record: dict[str, JsonValue] = {
        "id": "record-123",
        "metrics": {
            "value1": 42,
            "value2": "3.14",
            "value3": True,
            "timestamp": 1714640400,
        },
        "tags": ["tag1", "tag2", "tag3"],
        "nested": {"level1": {"level2": {"data": "nested value"}}},
        "items": [{"name": "item1", "value": 10}, {"name": "item2", "value": 20}],
    }

    spec: ImportSpec = {
        "record_id": "$.id",
        "value1": ("$.metrics.value1", {"type": int, "required": True}),
        "value2": ("$.metrics.value2", {"type": float}),
        "value3": ("$.metrics.value3", {"type": bool}),
        "timestamp": ("$.metrics.timestamp", {"type": datetime}),
        "tags": ("$.tags", {"type": str}),
        "deep_value": "$.nested.level1.level2.data",
        "items": ("$.items", {"type": str}),
        # Test a non-existent field
        "missing": ("$.not.here", {"required": False}),
    }

    result = import_record(complex_record, spec)

    assert result["record_id"] == "record-123"
    assert result["value1"] == 42
    assert result["value2"] == 3.14
    assert result["value3"] is True
    assert isinstance(result["timestamp"], datetime)
    assert result["tags"] == '["tag1", "tag2", "tag3"]'
    assert result["deep_value"] == "nested value"
    assert (
        result["items"]
        == '[{"name": "item1", "value": 10}, {"name": "item2", "value": 20}]'
    )
    assert result["missing"] is None
