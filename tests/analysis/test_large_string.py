"""Tests for PyArrow large_string conversion to handle offset overflow."""

import pandas as pd
import pyarrow as pa

from inspect_ai.analysis._dataframe.samples.table import _convert_to_large_string


def test_convert_to_large_string_small_column():
    """Test that small string columns are not converted unnecessarily."""
    # Create a DataFrame with a small PyArrow string column
    # Force it to use regular string type (not large_string)
    small_strings = pa.array(["hello", "world", "test"], type=pa.string())
    df = pd.DataFrame({"text": pd.arrays.ArrowExtensionArray(small_strings)})

    # Verify it starts as regular string
    arrow_array_before = df["text"].array._pa_array
    assert pa.types.is_string(arrow_array_before.type)
    assert not pa.types.is_large_string(arrow_array_before.type)

    # Convert
    result = _convert_to_large_string(df)

    # Small column should NOT be converted (stays as regular string)
    arrow_array = result["text"].array._pa_array
    assert pa.types.is_string(arrow_array.type)
    assert not pa.types.is_large_string(arrow_array.type)


def test_convert_to_large_string_large_column():
    """Test that large string columns are converted to large_string."""
    # Create a DataFrame with a large PyArrow string column
    # Each string is ~10MB, and we create 200 of them = ~2GB total
    large_string = "x" * (10 * 1024 * 1024)  # 10MB string
    data = [large_string] * 200  # ~2GB total

    # Force regular string type (pandas may auto-convert to large_string for big data)
    arrow_array = pa.array(data, type=pa.string())
    df = pd.DataFrame({"text": pd.arrays.ArrowExtensionArray(arrow_array)})

    # Verify it starts as regular string
    arrow_array_before = df["text"].array._pa_array
    assert pa.types.is_string(arrow_array_before.type)

    # Convert
    result = _convert_to_large_string(df)

    # Large column should be converted to large_string
    arrow_array_after = result["text"].array._pa_array
    assert pa.types.is_large_string(arrow_array_after.type)


def test_convert_to_large_string_mixed_columns():
    """Test that only large columns are converted, not small ones."""
    # Create a DataFrame with both small and large columns (same length)
    large_string = "y" * (10 * 1024 * 1024)  # 10MB string
    num_rows = 200
    data_large = [large_string] * num_rows  # ~2GB total
    data_small = ["small", "text", "data"] * (num_rows // 3 + 1)  # Make same length
    data_small = data_small[:num_rows]  # Trim to exact length

    # Force regular string types
    large_arrow = pa.array(data_large, type=pa.string())
    small_arrow = pa.array(data_small, type=pa.string())

    df = pd.DataFrame(
        {
            "large_col": pd.arrays.ArrowExtensionArray(large_arrow),
            "small_col": pd.arrays.ArrowExtensionArray(small_arrow),
        }
    )

    # Convert
    result = _convert_to_large_string(df)

    # Large column should be converted
    large_arrow_result = result["large_col"].array._pa_array
    assert pa.types.is_large_string(large_arrow_result.type)

    # Small column should NOT be converted
    small_arrow_result = result["small_col"].array._pa_array
    assert pa.types.is_string(small_arrow_result.type)
    assert not pa.types.is_large_string(small_arrow_result.type)


def test_convert_to_large_string_non_pyarrow_columns():
    """Test that non-PyArrow columns are left unchanged."""
    df = pd.DataFrame(
        {
            "text": ["hello", "world"],
            "number": [1, 2],
            "float": [1.5, 2.5],
        }
    )

    # Convert
    result = _convert_to_large_string(df)

    # Non-PyArrow columns should be unchanged
    assert result["text"].dtype == object
    assert result["number"].dtype == "int64"
    assert result["float"].dtype == "float64"


def test_convert_to_large_string_preserves_data():
    """Test that data is preserved during conversion."""
    large_string = "z" * (10 * 1024 * 1024)  # 10MB string
    data = [large_string] * 200  # ~2GB total

    df = pd.DataFrame({"text": pd.array(data, dtype="string[pyarrow]")})

    # Convert
    result = _convert_to_large_string(df)

    # Data should be preserved
    assert len(result) == len(df)
    assert result["text"][0] == large_string
    assert result["text"][100] == large_string
    assert result["text"][199] == large_string
