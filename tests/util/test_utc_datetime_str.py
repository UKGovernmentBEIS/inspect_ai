import pytest
from pydantic import BaseModel, ValidationError

from inspect_ai._util.dateutil import UtcDatetimeStr, iso_now


def validate_model(model: BaseModel, input_str: str) -> None:
    """Verify model serializes to JSON and parses back identically.

    Args:
        model: Model instance to test
        input_str: Original input string to also test parsing from raw JSON
    """
    # Test round-trip of already-constructed model
    json_str = model.model_dump_json()
    parsed = type(model).model_validate_json(json_str)
    assert parsed.timestamp == model.timestamp  # type: ignore
    assert isinstance(parsed.timestamp, str)  # type: ignore

    # Test parsing from raw JSON with original input string
    raw_json = f'{{"timestamp": "{input_str}"}}'
    parsed_from_raw = type(model).model_validate_json(raw_json)
    assert parsed_from_raw.timestamp == model.timestamp  # type: ignore
    assert isinstance(parsed_from_raw.timestamp, str)  # type: ignore


@pytest.mark.parametrize(
    ("input_str", "expected_utc"),
    [
        # UTC ISO string
        ("2025-01-24T12:00:00+00:00", "2025-01-24T12:00:00+00:00"),
        # 12:00:00-05:00 becomes 17:00:00+00:00
        ("2025-01-24T12:00:00-05:00", "2025-01-24T17:00:00+00:00"),
        # Naive datetime treated as UTC
        ("2025-01-24T12:00:00", "2025-01-24T12:00:00+00:00"),
        # Z suffix converts to +00:00
        ("2025-01-24T12:00:00Z", "2025-01-24T12:00:00+00:00"),
        # Positive offset (UTC+5)
        ("2025-01-24T12:00:00+05:00", "2025-01-24T07:00:00+00:00"),
        # Negative offset (UTC-8)
        ("2025-01-24T12:00:00-08:00", "2025-01-24T20:00:00+00:00"),
        # Microseconds precision preserved
        ("2025-01-24T12:00:00.123456+00:00", "2025-01-24T12:00:00.123456+00:00"),
    ],
)
def test_timezone_normalization(input_str: str, expected_utc: str) -> None:
    """Should normalize various timezone formats to UTC."""

    class Model(BaseModel):
        timestamp: UtcDatetimeStr

    m = Model(timestamp=input_str)
    assert m.timestamp == expected_utc
    assert isinstance(m.timestamp, str)
    validate_model(m, input_str)


@pytest.mark.parametrize(
    "invalid_value",
    [
        12345,  # Non-string int
        None,  # None
        [],  # List
        {},  # Dict
        "not a date",  # Invalid ISO format
        "",  # Empty string
        "2025-13-01T12:00:00+00:00",  # Invalid month
    ],
)
def test_rejects_invalid_values(invalid_value: object) -> None:
    """Should reject non-string and invalid ISO format values."""

    class Model(BaseModel):
        timestamp: UtcDatetimeStr

    with pytest.raises(ValidationError):
        Model(timestamp=invalid_value)  # type: ignore


def test_iso_now_timespec_parameter() -> None:
    """Should respect timespec parameter."""
    # Seconds precision (default) - no fractional seconds
    seconds = iso_now(timespec="seconds")
    # Split on + to get time part before timezone
    time_part = seconds.split("+")[0]
    assert "." not in time_part

    # Milliseconds precision - has fractional seconds
    millis = iso_now(timespec="milliseconds")
    assert "." in millis
