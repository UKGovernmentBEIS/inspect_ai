import json

from inspect_ai._util.json import json_changes, to_json_str_safe


def test_json_unicode_replace():
    # data with invalid surrogate characters
    data = {
        "text": "Some text with \ud83c invalid surrogate",
        "nested": {"field": "Another \ud800 bad surrogate"},
        "list": ["item1", "item with \udfff surrogate", "item3"],
    }
    json_str = to_json_str_safe(data)
    deserialized = json.loads(json_str)
    assert deserialized == {
        "text": "Some text with \\ud83c invalid surrogate",
        "nested": {"field": "Another \\ud800 bad surrogate"},
        "list": ["item1", "item with \\udfff surrogate", "item3"],
    }


def test_json_changes_tracks_replaced_value_through_array_shifts():
    before = {"x": ["a", "b"]}
    after = {"x": ["c", "a", "d"]}

    changes = json_changes(before, after)

    assert changes is not None
    assert len(changes) == 2

    # First op: add "c" at index 0
    assert changes[0].op == "add"
    assert changes[0].path == "/x/0"
    assert changes[0].value == "c"

    # Second op: replace index 2 (was "b", now "d")
    assert changes[1].op == "replace"
    assert changes[1].path == "/x/2"
    assert changes[1].value == "d"
    assert changes[1].replaced == "b"


def test_json_changes_basic_replace_no_arrays():
    """Test standard replacement without array complexity."""
    before = {"key": "old_value", "stay": 1}
    after = {"key": "new_value", "stay": 1}

    changes = json_changes(before, after)

    assert len(changes) == 1
    assert changes[0].op == "replace"
    assert changes[0].path == "/key"
    assert changes[0].value == "new_value"
    assert changes[0].replaced == "old_value"


def test_array_insert_shifts_indices_fast_path():
    """Test 'Fast Path': Simple list of strings.

    This tests that the `replaced` value is correctly captured for the replace op.
    """
    before = {"x": ["a", "b"]}
    after = {"x": ["c", "d", "b"]}

    changes = json_changes(before, after)

    # Filter to ensure we have the ops we expect
    ops = {c.path: c for c in changes}

    # The replace operation at index 0
    assert "/x/0" in ops
    assert ops["/x/0"].op == "replace"
    assert ops["/x/0"].value == "c"
    assert ops["/x/0"].replaced == "a"  # Was "a" before replacement

    # The add operation at index 1
    assert "/x/1" in ops
    assert ops["/x/1"].op == "add"
    assert ops["/x/1"].value == "d"


def test_array_remove_shifts_indices():
    """Test that removing an item correctly shifts subsequent lookups.

    The key test is that `replaced` correctly captures "b" (the value at index 1 before replacement).
    """
    before = {"x": ["a", "b", "c"]}
    after = {"x": ["a", "z"]}

    changes = json_changes(before, after)
    ops = {c.path: c for c in changes}

    # The replace at index 1: b -> z
    assert "/x/1" in ops
    assert ops["/x/1"].op == "replace"
    assert ops["/x/1"].value == "z"
    assert ops["/x/1"].replaced == "b"  # Was "b" before replacement

    # The remove at index 2 (removing "c")
    assert "/x/2" in ops
    assert ops["/x/2"].op == "remove"


def test_slow_path_nested_object_modification():
    """Test 'Slow Path': Modifying an object inside a list.

    This triggers the `else` block in `apply_fast_list_op` and requires correct handling of leading slashes in `resolve_pointer`.

    The key test is that `replaced` values are correctly tracked even with multiple nested replace operations on array items.
    """
    before = {"items": [{"id": 1, "status": "active"}, {"id": 2, "status": "active"}]}
    after = {
        "items": [
            {"id": 99, "status": "new"},  # Was item with id:1
            {"id": 1, "status": "inactive"},  # Was item with id:2
            {"id": 2, "status": "active"},  # New item added
        ]
    }

    changes = json_changes(before, after)
    ops = {c.path: c for c in changes}

    # Replace at /items/0/id: 1 -> 99
    assert "/items/0/id" in ops
    assert ops["/items/0/id"].op == "replace"
    assert ops["/items/0/id"].value == 99
    assert ops["/items/0/id"].replaced == 1

    # Replace at /items/0/status: "active" -> "new"
    assert "/items/0/status" in ops
    assert ops["/items/0/status"].op == "replace"
    assert ops["/items/0/status"].value == "new"
    assert ops["/items/0/status"].replaced == "active"

    # Replace at /items/1/id: 2 -> 1
    assert "/items/1/id" in ops
    assert ops["/items/1/id"].op == "replace"
    assert ops["/items/1/id"].value == 1
    assert ops["/items/1/id"].replaced == 2

    # Replace at /items/1/status: "active" -> "inactive"
    assert "/items/1/status" in ops
    assert ops["/items/1/status"].op == "replace"
    assert ops["/items/1/status"].value == "inactive"
    assert ops["/items/1/status"].replaced == "active"

    # Add at /items/2
    assert "/items/2" in ops
    assert ops["/items/2"].op == "add"
    assert ops["/items/2"].value == {"id": 2, "status": "active"}


def test_multiple_independent_arrays():
    """Ensure changes in one array do not affect tracking of another."""
    before = {"A": [1, 2], "B": [10, 20]}
    after = {
        "A": [99, 1, 3],  # Insert 99 at 0, replace 2 with 3
        "B": [10, 25],  # Replace 20 with 25 (no structural change here, strictly)
    }
    # Make B structural too to force tracking
    after["B"] = [10, 20, 30]  # Append 30
    after["A"] = [99, 1, 88]  # Insert 99, Replace 2 (now idx 2) with 88

    changes = json_changes(before, after)
    ops = {c.path: c for c in changes}

    # Check A: /A/2 replaced value should be 2 (shifted from pos 1)
    assert "/A/2" in ops
    assert ops["/A/2"].replaced == 2

    # Check B: Just an append (add), no replaces.
    assert "/B/2" in ops
    assert ops["/B/2"].op == "add"
    assert ops["/B/2"].value == 30


def test_append_character_handling():
    """Test handling of the '-' character if jsonpatch generates it (end of array)."""
    before = ["a"]
    after = ["a", "b"]  # Append b

    changes = json_changes(before, after)
    assert len(changes) == 1
    assert changes[0].op == "add"
    assert changes[0].path == "/1"
    assert changes[0].value == "b"


def test_replace_root_array_item():
    """Test replacing an item in a root-level array."""
    before = ["x", "y"]
    after = ["z", "x"]
    # Insert z at 0 -> ["z", "x", "y"]
    # Remove y at 2 -> ["z", "x"]

    changes = json_changes(before, after)

    # Should be something like:
    # 1. Add /0 "z"
    # 2. Remove /2 "y" (which was shifted)

    assert len(changes) >= 2


def test_no_changes():
    """Test that identical objects return an empty list or None."""
    before = {"a": [1, 2]}
    after = {"a": [1, 2]}
    changes = json_changes(before, after)
    assert changes is None or len(changes) == 0


def test_nested_arrays_with_structural_changes():
    """Test that nested arrays are tracked correctly with structural changes and replaces.

    This tests a scenario where a nested array (/items/0/tags) has both structural
    changes (add/remove) and replace operations, requiring correct index tracking.
    """
    before = {
        "items": [
            {"tags": ["a", "b", "c"]},
            {"tags": ["x", "y"]},
        ]
    }
    after = {
        "items": [
            {
                "tags": ["z", "a", "NEW"]
            },  # Insert "z" at 0, remove "b", replace "c" with "NEW"
            {"tags": ["x", "y"]},
            {"tags": ["p", "q"]},  # New item added at end
        ]
    }

    changes = json_changes(before, after)
    assert changes is not None
    ops = {c.path: c for c in changes}

    # The replace at /items/0/tags/2 should have the correct replaced value
    # After add at index 0 and remove at index 2, the shadow is ["z", "a", "c"]
    # So replace at index 2 replaces "c" with "NEW"
    assert "/items/0/tags/2" in ops
    assert ops["/items/0/tags/2"].op == "replace"
    assert ops["/items/0/tags/2"].value == "NEW"
    assert ops["/items/0/tags/2"].replaced == "c"


def test_get_active_container_selects_longest_match():
    """Test that _get_active_container returns the most specific (longest) matching container.

    This is a unit test for the internal function to ensure correct behavior
    when there are overlapping tracked containers.
    """
    from inspect_ai._util.json import _get_active_container

    tracked = {"/items", "/items/0/tags"}

    # Path under nested container should match the nested one
    container, rel_path = _get_active_container("/items/0/tags/2", tracked)
    assert container == "/items/0/tags"
    assert rel_path == "2"

    # Path under parent but not nested should match parent
    container, rel_path = _get_active_container("/items/1/name", tracked)
    assert container == "/items"
    assert rel_path == "1/name"

    # Path not under any container
    container, rel_path = _get_active_container("/other/path", tracked)
    assert container is None
    assert rel_path is None
