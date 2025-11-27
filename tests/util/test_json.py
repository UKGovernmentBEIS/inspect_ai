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
