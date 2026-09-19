from pydantic import TypeAdapter

from inspect_ai._util.dateutil import UtcDatetime, UtcTime


def test_lowercase_z_is_normalized_for_datetime_and_time() -> None:
    datetime_value = TypeAdapter(UtcDatetime).validate_python("2025-04-17T12:00:00z")
    time_value = TypeAdapter(UtcTime).validate_python("12:00:00z")

    assert datetime_value.utcoffset().total_seconds() == 0
    assert time_value.utcoffset().total_seconds() == 0


def test_uppercase_z_remains_supported_for_datetime_and_time() -> None:
    datetime_value = TypeAdapter(UtcDatetime).validate_python("2025-04-17T12:00:00Z")
    time_value = TypeAdapter(UtcTime).validate_python("12:00:00Z")

    assert datetime_value.utcoffset().total_seconds() == 0
    assert time_value.utcoffset().total_seconds() == 0
