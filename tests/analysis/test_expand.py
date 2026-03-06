from pydantic import JsonValue

from inspect_ai.analysis._dataframe.record import _expand_fields


def test_single_level_expansion() -> None:
    """Test basic expansion with a single asterisk."""
    field_name = "foo_*"
    value: dict[str, JsonValue] = {"x": 1, "y": 2}
    expected = {"foo_x": 1, "foo_y": 2}
    assert _expand_fields(field_name, value) == expected


def test_multi_level_expansion() -> None:
    """Test expansion with multiple asterisks in different levels."""
    field_name = "foo_*_*"
    value: dict[str, JsonValue] = {"first": {"x": 1, "y": 2}, "second": {"z": 3}}
    expected = {"foo_first_x": 1, "foo_first_y": 2, "foo_second_z": 3}
    assert _expand_fields(field_name, value) == expected


def test_prefix_only() -> None:
    """Test expansion when asterisk is at the end."""
    field_name = "prefix_*"
    value: dict[str, JsonValue] = {"a": 1, "b": 2}
    expected = {"prefix_a": 1, "prefix_b": 2}
    assert _expand_fields(field_name, value) == expected


def test_suffix_only() -> None:
    """Test expansion when asterisk is at the beginning."""
    field_name = "*_suffix"
    value: dict[str, JsonValue] = {"a": 1, "b": 2}
    expected = {"a_suffix": 1, "b_suffix": 2}
    assert _expand_fields(field_name, value) == expected


def test_no_asterisk() -> None:
    """Test function when there's no asterisk."""
    field_name = "simple_field"
    value: dict[str, JsonValue] = {"a": 1, "b": 2}
    expected = {"simple_field": {"a": 1, "b": 2}}
    assert _expand_fields(field_name, value) == expected


def test_multiple_asterisks_same_level() -> None:
    """Test handling multiple asterisks at the same level."""
    field_name = "foo_*_bar_*"
    value: dict[str, JsonValue] = {"x": {"y": 1, "z": 2}}
    expected = {"foo_x_bar_y": 1, "foo_x_bar_z": 2}
    assert _expand_fields(field_name, value) == expected


def test_empty_dict() -> None:
    """Test expansion with an empty dictionary."""
    field_name = "foo_*"
    value: dict[str, JsonValue] = {}
    expected: dict[str, JsonValue] = {}
    assert _expand_fields(field_name, value) == expected


def test_non_dict_value_with_asterisk() -> None:
    """Test handling when there's an asterisk but value isn't a dictionary."""
    field_name = "foo_*"
    value = 123
    expected: dict[str, JsonValue] = {}
    assert _expand_fields(field_name, value) == expected


def test_nested_non_dict_value() -> None:
    """Test handling nested non-dictionary values."""
    field_name = "foo_*_*"
    value: dict[str, JsonValue] = {"first": 123, "second": {"x": 1}}
    expected = {"foo_second_x": 1}
    assert _expand_fields(field_name, value) == expected


def test_deep_nesting() -> None:
    """Test deep nesting of dictionaries."""
    field_name = "level1_*_level2_*_level3_*"
    value: dict[str, JsonValue] = {"a": {"b": {"c": 1, "d": 2}, "e": {"f": 3}}}
    expected = {
        "level1_a_level2_b_level3_c": 1,
        "level1_a_level2_b_level3_d": 2,
        "level1_a_level2_e_level3_f": 3,
    }
    assert _expand_fields(field_name, value) == expected


def test_mixed_values() -> None:
    """Test mixed types of values in dictionary."""
    field_name = "foo_*"
    value: dict[str, JsonValue] = {
        "a": 1,
        "b": "string",
        "c": True,
        "d": None,
        "e": [1, 2, 3],
    }
    expected = {
        "foo_a": 1,
        "foo_b": "string",
        "foo_c": True,
        "foo_d": None,
        "foo_e": [1, 2, 3],
    }
    assert _expand_fields(field_name, value) == expected


def test_complex_mixed_case() -> None:
    """Test a complex mixed case with various nesting levels."""
    field_name = "stats_*_*"
    value: dict[str, JsonValue] = {
        "user": {"id": 123, "name": "test_user", "active": True},
        "metrics": {
            "views": 1000,
            "clicks": 50,
            "details": {"source": "web", "campaign": "spring"},
        },
        "empty": {},
    }

    # We need to handle nested dict case specially
    result = _expand_fields(field_name, value)
    assert "stats_user_id" in result and result["stats_user_id"] == 123
    assert "stats_user_name" in result and result["stats_user_name"] == "test_user"
    assert "stats_user_active" in result and result["stats_user_active"] is True
    assert "stats_metrics_views" in result and result["stats_metrics_views"] == 1000
    assert "stats_metrics_clicks" in result and result["stats_metrics_clicks"] == 50
    assert "stats_metrics_details" in result
    assert isinstance(result["stats_metrics_details"], dict)
    assert result["stats_metrics_details"]["source"] == "web"
    assert result["stats_metrics_details"]["campaign"] == "spring"
