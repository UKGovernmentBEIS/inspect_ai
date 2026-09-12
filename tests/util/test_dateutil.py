from datetime import time, timezone

from pydantic import TypeAdapter

from inspect_ai._util.dateutil import UtcTime, datetime_from_iso_format_safe


def test_datetime_from_iso_format_safe_accepts_lowercase_z() -> None:
    value = datetime_from_iso_format_safe("2025-04-17T12:00:00z")

    assert value.utcoffset() == timezone.utc.utcoffset(value)
    assert value.isoformat() == "2025-04-17T12:00:00+00:00"


def test_utc_time_accepts_lowercase_z() -> None:
    value = TypeAdapter(UtcTime).validate_python("12:34:56z")

    assert value == time(12, 34, 56, tzinfo=timezone.utc)
