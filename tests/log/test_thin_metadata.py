import textwrap
from datetime import date, datetime, time

from inspect_ai.log._util import thin_metadata


def test_thin_metadata_preserves_numeric_types():
    """Test that int, float, and bool values are preserved as-is."""
    metadata = {
        "int_value": 42,
        "float_value": 3.14159,
        "bool_true": True,
        "bool_false": False,
        "negative_int": -100,
        "zero": 0,
    }

    result = thin_metadata(metadata)

    assert result == metadata


def test_thin_metadata_preserves_datetime_types():
    """Test that date, time, and datetime values are preserved as-is."""
    test_date = date(2024, 1, 1)
    test_time = time(12, 30, 45)
    test_datetime = datetime(2024, 1, 1, 12, 30, 45)

    metadata = {
        "date_value": test_date,
        "time_value": test_time,
        "datetime_value": test_datetime,
    }

    result = thin_metadata(metadata)

    assert result == metadata


def test_thin_metadata_shortens_long_strings():
    """Test that strings longer than 1024 characters are shortened."""
    long_string = "a" * 2000
    metadata = {
        "long_string": long_string,
    }

    result = thin_metadata(metadata)

    assert len(result["long_string"]) <= 1024
    assert result["long_string"].endswith("...")
    assert result["long_string"] == textwrap.shorten(
        long_string, width=1024, placeholder="..."
    )


def test_thin_metadata_preserves_short_strings():
    """Test that strings shorter than 1024 characters are preserved."""
    metadata = {
        "short_string": "Hello, World!",
        "empty_string": "",
        "medium_string": "x" * 1000,  # Still under 1024
    }

    result = thin_metadata(metadata)

    assert result == metadata


def test_thin_metadata_handles_small_complex_objects():
    """Test that small complex objects (< 1024 chars when serialized) are preserved."""
    metadata = {
        "small_list": [1, 2, 3, 4, 5],
        "small_dict": {"a": 1, "b": 2},
        "nested": {"level1": {"level2": "value"}},
        "mixed_list": [1, "two", 3.0, True],
    }

    result = thin_metadata(metadata)

    assert result == metadata


def test_thin_metadata_removes_large_complex_objects():
    """Test that large complex objects (>= 1024 chars when serialized) are replaced."""
    # Create a large object that serializes to > 1024 characters
    large_list = list(range(500))  # This should serialize to > 1024 chars
    large_dict = {f"key_{i}": f"value_{i}" for i in range(100)}

    metadata = {
        "large_list": large_list,
        "large_dict": large_dict,
    }

    result = thin_metadata(metadata)

    assert result["large_list"] == "Key removed from summary (> 1k)"
    assert result["large_dict"] == "Key removed from summary (> 1k)"


def test_thin_metadata_mixed_types():
    """Test handling of mixed data types in a single metadata dict."""
    metadata = {
        "number": 42,
        "text": "Short text",
        "long_text": "x" * 2000,
        "date": date.today(),
        "small_data": {"nested": "value"},
        "large_data": {"key": "x" * 1024},  # Should be > 1024 when serialized
        "boolean": True,
    }

    result = thin_metadata(metadata)

    assert result["number"] == 42
    assert result["text"] == "Short text"
    assert len(result["long_text"]) <= 1024
    assert result["long_text"].endswith("...")
    assert result["date"] == metadata["date"]
    assert result["small_data"] == {"nested": "value"}
    assert result["large_data"] == "Key removed from summary (> 1k)"
    assert result["boolean"] is True


def test_thin_metadata_empty_dict():
    """Test that an empty metadata dict returns an empty dict."""
    result = thin_metadata({})
    assert result == {}


def test_thin_metadata_none_values():
    """Test handling of None values (they should be < 1024 chars)."""
    metadata = {
        "none_value": None,
    }

    result = thin_metadata(metadata)

    # None serializes to "null" which is < 1024 chars
    assert result["none_value"] is None


def test_thin_metadata_edge_case_string_length():
    """Test strings at exactly 1024 characters boundary."""
    exactly_1024 = "x" * 1024
    just_over_1024 = "x" * 1025
    just_under_1024 = "x" * 1023

    metadata = {
        "exactly_1024": exactly_1024,
        "just_over_1024": just_over_1024,
        "just_under_1024": just_under_1024,
    }

    result = thin_metadata(metadata)

    # The exact behavior depends on textwrap.shorten implementation
    assert result["just_under_1024"] == just_under_1024
    assert len(result["exactly_1024"]) <= 1024
    assert len(result["just_over_1024"]) <= 1024
    assert result["just_over_1024"].endswith("...")


def test_thin_metadata_preserves_key_order():
    """Test that the function preserves the order of keys."""
    metadata = {
        "z_key": 1,
        "a_key": "value",
        "m_key": True,
    }

    result = thin_metadata(metadata)

    assert list(result.keys()) == list(metadata.keys())


def test_thin_metadata_unicode_strings():
    """Test handling of unicode strings."""
    metadata = {
        "emoji": "🚀" * 500,  # Should exceed 1024 when considering unicode
        "chinese": "你好世界",
        "mixed": "Hello 世界 🌍",
    }

    result = thin_metadata(metadata)

    assert result["chinese"] == "你好世界"
    assert result["mixed"] == "Hello 世界 🌍"
    # The emoji string should be shortened
    assert len(result["emoji"]) <= 1024
