import pytest

from inspect_ai._util.json import JsonChange, synthesize_comparable


def test_json_changes_add_simple_value():
    changes = [JsonChange(op="add", path="/name", value="John")]
    before, after = synthesize_comparable(changes)
    assert before == {}
    assert after == {"name": "John"}


def test_json_changes_add_nested_value():
    changes = [JsonChange(op="add", path="/user/name", value="John")]
    before, after = synthesize_comparable(changes)
    assert before == {"user": {}}
    assert after == {"user": {"name": "John"}}


def test_json_changes_add_to_array():
    changes = [JsonChange(op="add", path="/users/1", value="John")]
    before, after = synthesize_comparable(changes)
    assert before == {"users": [""]}  # Initialized with empty string
    assert after == {"users": ["", "John"]}


def test_json_changes_remove_value():
    changes = [JsonChange(op="remove", path="/name", value="John")]
    before, after = synthesize_comparable(changes)
    assert before == {"name": "John"}
    assert after == {}


def test_json_changes_replace_value():
    changes = [JsonChange(op="replace", path="/name", value="Jane", replaced="John")]
    before, after = synthesize_comparable(changes)
    assert before == {"name": "John"}
    assert after == {"name": "Jane"}


def test_json_changes_move_value():
    changes = [JsonChange(op="move", path="/new_name", from_="/name", value="John")]
    before, after = synthesize_comparable(changes)
    assert before == {"name": "John"}
    assert after == {"new_name": "John"}


def test_json_changes_copy_value():
    changes = [JsonChange(op="copy", path="/name_copy", value="John")]
    before, after = synthesize_comparable(changes)
    assert before == {"name_copy": "John"}
    assert after == {"name_copy": "John"}


def test_json_changes_test_json_changes_operation():
    changes = [JsonChange(op="test", path="/name", value="John")]
    before, after = synthesize_comparable(changes)
    assert before == {}
    assert after == {}


def test_json_changes_multiple_operations():
    changes = [
        JsonChange(op="add", path="/user/name", value="John"),
        JsonChange(op="add", path="/user/age", value=30),
        JsonChange(op="replace", path="/user/name", value="Jane", replaced="John"),
    ]
    before, after = synthesize_comparable(changes)
    assert before == {"user": {"name": "John"}}
    assert after == {"user": {"name": "Jane", "age": 30}}


def test_json_changes_array_operations():
    changes = [
        JsonChange(op="add", path="/users/0", value="John"),
        JsonChange(op="add", path="/users/2", value="Jane"),
    ]
    before, after = synthesize_comparable(changes)
    assert before == {"users": ["", ""]}
    assert after == {"users": ["John", "", "Jane"]}


def test_json_changes_move_without_from_field():
    changes = [JsonChange(op="move", path="/new_name", from_=None, value="John")]
    with pytest.raises(
        ValueError, match="'from_' field is required for move operation"
    ):
        synthesize_comparable(changes)


def test_json_changes_empty_path():
    changes = [JsonChange(op="add", path="", value="John")]
    with pytest.raises(ValueError, match="Path cannot be empty"):
        synthesize_comparable(changes)
