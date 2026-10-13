import subprocess
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import JsonValue
from typing_extensions import override

from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.version import has_required_version
from inspect_ai.analysis import (
    Column,
    EvalColumns,
    EventColumn,
    MessageColumn,
    SampleColumn,
)
from inspect_ai.analysis._dataframe.columns import parse
from inspect_ai.analysis._dataframe.evals.columns import EvalColumn
from inspect_ai.analysis._dataframe.record import _resolve_value, import_record
from inspect_ai.event import ModelEvent, ToolEvent
from inspect_ai.log._file import read_eval_log
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalSample,
    EvalSampleSummary,
    EvalSpec,
)
from inspect_ai.model import ChatMessageAssistant, GenerateConfig, ModelOutput
from inspect_ai.scorer import Score, Value


class TColumn(Column):
    @override
    def path_schema(self) -> None:
        return None


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


def eval_log() -> EvalLog:
    return EvalLog(
        eval=EvalSpec(
            created=iso_now(),
            task="task",
            dataset=EvalDataset(),
            model="model",
            config=EvalConfig(),
        )
    )


def test_basic_import() -> None:
    """Test basic field import with direct mapping."""
    spec: list[Column] = [
        TColumn("status", path="$.status"),
        TColumn("model", path="$.eval.model"),
    ]

    result = import_record(eval_log(), test_record, spec)

    assert result["status"] == "complete"
    assert result["model"] == "openai/gpt-4o"


def test_wildcard_fields() -> None:
    """Test importing wildcard fields."""
    spec: list[Column] = [
        TColumn("task_arg_*", path="$.eval.task_args"),
    ]

    result = import_record(eval_log(), test_record, spec)

    assert result["task_arg_foo"] == 42
    assert result["task_arg_bar"] == 84


def test_extract_function() -> None:
    log = read_eval_log(
        Path(__file__).parent.parent / "log" / "test_eval_log" / "log_formats.eval"
    )
    spec: list[Column] = [
        EvalColumn("status", path=lambda log: log.status, required=True),
    ]
    result = import_record(eval_log(), log, spec)
    assert result["status"] == "success"


def test_field_options() -> None:
    """Test importing with field options."""
    spec: list[Column] = [
        TColumn("status", path="$.status", required=True),
        TColumn("error_msg", path="$.error.message", required=False),
        TColumn("missing", path="$.not.existing", required=False),
    ]

    result = import_record(eval_log(), test_record, spec)

    assert result["status"] == "complete"
    assert result["error_msg"] == "Some error occurred"
    assert result["missing"] is None


def test_predefined_spec() -> None:
    """Test using the predefined EvalColumns spec."""
    log = read_eval_log(
        Path(__file__).parent.parent / "log" / "test_eval_log" / "log_formats.eval"
    )
    result = import_record(log, log, EvalColumns)

    assert result["status"] == "success"
    assert result["model"] == "ollama/llama3.1"
    assert result["error_message"] is None


def test_type_coercion_simple() -> None:
    """Test simple type coercion."""
    spec: list[Column] = [
        TColumn(
            "flag", path="$.data.flag", type=bool
        ),  # will yaml parse bool from 'true'
        TColumn("values", path="$.data.values", type=str),  # Will json.dumps
    ]

    result = import_record(eval_log(), test_record, spec)
    assert result["flag"] is True
    assert result["values"] == "[1, 2, 3, 4]"


def test_type_coercion_failure() -> None:
    """Test failure with incompatible type coercion."""
    spec: list[Column] = [
        TColumn(
            "status_int", path="$.status", type=int
        )  # Will fail - string can't convert to int
    ]

    with pytest.raises(ValueError, match="Cannot coerce"):
        print(import_record(eval_log(), test_record, spec))


def test_date_time_coercion() -> None:
    """Test date/time coercion."""
    spec: list[Column] = [
        TColumn("timestamp_dt", path="$.data.timestamps.unix", type=datetime),
        TColumn("timestamp_d", path="$.data.timestamps.unix", type=date),
        TColumn("timestamp_t", path="$.data.timestamps.unix", type=time),
        TColumn("iso_dt", path="$.data.timestamps.iso", type=datetime),
    ]

    result = import_record(eval_log(), test_record, spec)

    assert isinstance(result["timestamp_dt"], datetime)
    assert result["timestamp_dt"] == datetime.fromtimestamp(1714640400, tz=timezone.utc)

    assert isinstance(result["timestamp_d"], date)
    assert (
        result["timestamp_d"]
        == datetime.fromtimestamp(1714640400, tz=timezone.utc).date()
    )

    assert isinstance(result["timestamp_t"], time)
    assert result["timestamp_t"].hour == 9
    assert result["timestamp_t"].minute == 0

    assert isinstance(result["iso_dt"], datetime)
    expected_dt = datetime(2024, 5, 1, 12, 0, 0, 0, timezone.utc)
    # Account for timezone differences in comparison
    assert result["iso_dt"].year == expected_dt.year
    assert result["iso_dt"].month == expected_dt.month
    assert result["iso_dt"].day == expected_dt.day
    assert result["iso_dt"].hour == expected_dt.hour


def test_yaml_string_coercion() -> None:
    """Test YAML string coercion."""
    spec: list[Column] = [
        TColumn("int_val", path="$.string_int", type=int),
        TColumn("float_val", path="$.string_float", type=float),
        TColumn("bool_val", path="$.string_bool", type=bool),
        TColumn("date_val", path="$.string_date", type=date),
        TColumn("array_val", path="$.string_array", type=str),  # Keep as string
    ]

    result = import_record(eval_log(), yaml_record, spec)

    assert result["int_val"] == 42
    assert result["float_val"] == 3.14
    assert result["bool_val"] is True
    assert isinstance(result["date_val"], date)
    assert result["date_val"] == date(2024, 5, 1)
    assert result["array_val"] == "[1, 2, 3]"


def test_required_field_missing() -> None:
    """Test error when required field is missing."""
    spec: list[Column] = [
        TColumn("missing", path="$.not.existing", required=True),
    ]

    with pytest.raises(ValueError, match="not found"):
        import_record(eval_log(), test_record, spec)


def test_collect_errors() -> None:
    """Test collecting errors instead of raising."""
    spec: list[Column] = [
        TColumn("status", path="$.status"),
        TColumn("missing", path="$.not.existing", required=True),
        TColumn("bad_type", path="$.data.extra", type=int),  # str to int will fail
    ]

    _, errors = import_record(eval_log(), test_record, spec, strict=False)

    assert len(errors) == 2

    assert any("not found" in str(error.error) for error in errors)
    assert any("Cannot coerce" in str(error.error) for error in errors)


def test_invalid_jsonpath() -> None:
    """Test handling of invalid JSONPath expressions."""
    spec: list[Column] = [
        TColumn("invalid", path="$..[*"),  # Invalid JSONPath syntax
    ]

    with pytest.raises(
        Exception
    ):  # Exception type depends on jsonpath-ng implementation
        import_record(eval_log(), test_record, spec)


def test_empty_record() -> None:
    """Test importing from an empty record."""
    empty_record: dict[str, JsonValue] = {}

    spec: list[Column] = [
        TColumn("status", path="$.status", required=False),
    ]

    result = import_record(eval_log(), empty_record, spec)
    assert result["status"] is None


def test_none_values() -> None:
    """Test handling of None values."""
    none_record: dict[str, JsonValue] = {
        "explicit_none": None,
    }

    spec: list[Column] = [
        TColumn("explicit_none", path="$.explicit_none"),
        TColumn("null_value", path="$.data.null_value"),
    ]

    result = import_record(eval_log(), {**test_record, **none_record}, spec)
    assert result["explicit_none"] is None
    assert result["null_value"] is None


def test_multiple_import_specs() -> None:
    """Test importing with multiple import specs."""
    spec1: list[Column] = [
        TColumn("status", path="$.status"),
    ]

    spec2: list[Column] = [
        TColumn("model", path="$.eval.model"),
    ]

    result = import_record(eval_log(), test_record, spec1 + spec2)

    assert result["status"] == "complete"
    assert result["model"] == "openai/gpt-4o"


def test_resolve_value_compound_types() -> None:
    """Test resolving compound values."""
    # List to string
    assert _resolve_value([1, 2, 3], str) == "[1, 2, 3]"

    # dict to string
    assert _resolve_value({"a": 1}, str) == '{"a": 1}'

    # None handling
    assert _resolve_value(None, int) is None


def test_resolve_value_type_coercion() -> None:
    """Test various type coercions in _resolve_value."""
    # Simple types
    assert _resolve_value(42, int) == 42
    assert _resolve_value("hello", str) == "hello"
    assert _resolve_value(True, bool) is True

    # Constructor coercion
    assert _resolve_value("42", int) == 42
    assert _resolve_value(42, str) == "42"

    # YAML string coercion
    assert _resolve_value("true", bool) is True
    assert _resolve_value("false", bool) is False
    assert _resolve_value("no", bool) is False
    assert _resolve_value("0", bool) is False
    assert _resolve_value("off", bool) is False
    assert _resolve_value("42", int) == 42
    assert _resolve_value("3.14", float) == 3.14

    # Timestamp to temporal
    ts_dt = _resolve_value(1714640400, datetime)
    assert isinstance(ts_dt, datetime)
    assert ts_dt.year == 2024

    ts_date = _resolve_value(1714640400, date)
    assert isinstance(ts_date, date)
    assert ts_date.year == 2024

    ts_time = _resolve_value(1714640400, time)
    assert isinstance(ts_time, time)

    # ISO string to temporal
    iso_str = "2024-05-01T12:00:00Z"
    iso_dt = _resolve_value(iso_str, datetime)
    assert isinstance(iso_dt, datetime)

    # Numeric string timestamp
    str_ts = _resolve_value("1714640400", datetime)
    assert isinstance(str_ts, datetime)


def test_resolve_value_errors() -> None:
    """Test error handling in _resolve_value."""
    # Type mismatch
    with pytest.raises(ValueError, match=r"^Cannot coerce str from type str to time$"):
        _resolve_value("str", time)

    # Incompatible conversion
    with pytest.raises(
        ValueError, match=r"^Cannot coerce not a bool from type str to int$"
    ):
        _resolve_value("not a bool", int)


def test_column_error_path_type() -> None:
    """Test that ColumnError.path is a str | None, not a JSONPath object."""
    spec: list[Column] = [
        TColumn("bad_type", path="$.eval.task", type=int),
        TColumn("missing_req", path="$.eval.nonexistent", required=True),
    ]
    _, errors = import_record(eval_log(), test_record, spec, strict=False)
    assert len(errors) == 2
    for err in errors:
        assert isinstance(err.path, str)
    # str() of a path differs across jsonpath-ng versions, so check it re-parses
    assert [parse(str(err.path)) for err in errors] == [
        parse("$.eval.task"),
        parse("$.eval.nonexistent"),
    ]
    assert "Cannot coerce foo from type str to int" in str(errors[0])
    assert "field not found" in str(errors[1])


def test_index_paths_across_jsonpath_ng_versions() -> None:
    """Integer indices that select nothing raise on jsonpath-ng < 1.9 only."""
    record: dict[str, JsonValue] = {"mapping": {"a": 1}, "items": [1, 2]}
    spec: list[Column] = [
        TColumn("mapping_index", path="$.mapping[0]"),
        TColumn("out_of_range", path="$.items[-3]"),
        TColumn("last", path="$.items[-1]"),
    ]
    result, errors = import_record(eval_log(), record, spec, strict=False)
    assert result["last"] == 2
    if has_required_version("jsonpath-ng", "1.9.0"):
        assert errors == []
        assert result["mapping_index"] is None
        assert result["out_of_range"] is None
    else:
        assert [(e.column, type(e.error)) for e in errors] == [
            ("mapping_index", KeyError),
            ("out_of_range", IndexError),
        ]
        assert "mapping_index" not in result
        assert "out_of_range" not in result


def test_integer_filter_across_jsonpath_ng_versions() -> None:
    """Integer filters truncate non-string values on jsonpath-ng < 1.9 only."""
    record: dict[str, JsonValue] = {
        "values": [{"v": 1.9, "name": "float"}, {"v": "1", "name": "string"}]
    }
    spec: list[Column] = [TColumn("name", path="$.values[?(@.v == 1)].name")]
    result, errors = import_record(eval_log(), record, spec, strict=False)
    assert errors == []
    expected = "string" if has_required_version("jsonpath-ng", "1.9.0") else "float"
    assert result["name"] == expected


def model_event_completion(event: ModelEvent) -> str:
    return event.output.completion


def event_counts(event: ModelEvent | ToolEvent) -> list[dict[str, int]]:
    return [{"count": 1 if isinstance(event, ModelEvent) else 2}]


def assistant_text(message: ChatMessageAssistant) -> str:
    return message.text


def first_score(sample: EvalSample | EvalSampleSummary) -> Value | None:
    return next(iter(sample.scores.values())).value if sample.scores else None


def eval_counts(log: EvalLog) -> dict[str, list[int]]:
    return {"counts": [1, 2]}


def test_extract_function_subtypes() -> None:
    """Extract functions may take a subtype and return a precise JSON type.

    mypy checks these calls as part of the test suite.
    """
    model_event = ModelEvent(
        model="model",
        input=[],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("model", "hello"),
    )
    tool_event = ToolEvent(id="1", function="f", arguments={})
    event_spec: list[Column] = [
        EventColumn("completion", path=model_event_completion),
        EventColumn("counts", path=event_counts),
    ]
    assert import_record(eval_log(), model_event, event_spec) == {
        "completion": "hello",
        "counts": '[{"count": 1}]',
    }
    assert import_record(eval_log(), tool_event, event_spec[1:]) == {
        "counts": '[{"count": 2}]'
    }

    message_spec: list[Column] = [MessageColumn("text", path=assistant_text)]
    message = ChatMessageAssistant(content="hi")
    assert import_record(eval_log(), message, message_spec) == {"text": "hi"}

    sample = EvalSampleSummary(
        id=1, epoch=1, input="x", target="y", scores={"s": Score(value=0.5)}
    )
    sample_spec: list[Column] = [SampleColumn("score", path=first_score)]
    assert import_record(eval_log(), sample, sample_spec) == {"score": 0.5}

    eval_spec: list[Column] = [EvalColumn("counts", path=eval_counts)]
    assert import_record(eval_log(), eval_log(), eval_spec) == {
        "counts": '{"counts": [1, 2]}'
    }


@pytest.mark.slow
def test_extract_function_types_checked(tmp_path: Path) -> None:
    """Mypy accepts subtype extract functions and rejects unrelated types."""
    source = tmp_path / "columns.py"
    source.write_text(
        dedent(
            """
            from inspect_ai.analysis import EventColumn, MessageColumn
            from inspect_ai.event import ModelEvent, ToolEvent
            from inspect_ai.model import ChatMessageAssistant

            def model_input(event: ModelEvent) -> list[dict[str, int]]:
                return []

            def tool_or_model(event: ModelEvent | ToolEvent) -> str:
                return ""

            def text(message: ChatMessageAssistant) -> str:
                return message.text

            def number(value: int) -> str:
                return ""

            EventColumn("input", path=model_input)
            EventColumn("event", path=tool_or_model)
            MessageColumn("text", path=text)
            EventColumn("number", path=number)
            """
        )
    )
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-incremental", str(source)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    errors = [line for line in result.stdout.splitlines() if ": error:" in line]
    if has_required_version("jsonpath-ng", "1.9.0"):
        assert len(errors) == 1, result.stdout
        assert 'variable "E" of "EventColumn" cannot be "int"' in errors[0]
    else:
        # jsonpath-ng < 1.9 is untyped, so the path union accepts any callable
        assert errors == [], result.stdout


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

    spec: list[Column] = [
        TColumn("record_id", path="$.id"),
        TColumn("value1", path="$.metrics.value1", type=int, required=True),
        TColumn("value2", path="$.metrics.value2", type=float),
        TColumn("value3", path="$.metrics.value3", type=bool),
        TColumn("timestamp", path="$.metrics.timestamp", type=datetime),
        TColumn("tags", path="$.tags", type=str),
        TColumn("deep_value", path="$.nested.level1.level2.data"),
        TColumn("items", path="$.items", type=str),
        # Test a non-existent field
        TColumn("missing", path="$.not.here", required=False),
    ]

    result = import_record(eval_log(), complex_record, spec)

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
