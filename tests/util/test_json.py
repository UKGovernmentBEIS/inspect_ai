import json
import random
from copy import deepcopy
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from inspect_ai._util.json import (
    JsonChange,
    exceeds_max_depth,
    json_changes,
    to_json_safe,
    to_json_str_safe,
)
from inspect_ai.dataset._sources.json import (
    json_dataset_reader,
    jsonlines_dataset_reader,
)
from inspect_ai.event import StoreEvent
from inspect_ai.util._store import _apply_store_event


def _apply_changes(
    before: dict[str, Any], changes: list[JsonChange] | None
) -> dict[str, Any]:
    """Apply changes to a copy of `before` the way StoreEvent replay does."""
    return _apply_store_event(deepcopy(before), StoreEvent(changes=changes or []))


def _assert_round_trip(before: dict[str, Any], after: dict[str, Any]) -> None:
    changes = json_changes(before, after)
    # dumps tells 1 from True and 1.0, which == does not
    assert json.dumps(_apply_changes(before, changes), sort_keys=True) == json.dumps(
        after, sort_keys=True
    )


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


def test_json_unicode_replace_preserves_exclude():
    result = to_json_safe(
        {"keep": "\ud800", "drop": "excluded"},
        exclude={"drop": True},
    )

    assert json.loads(result) == {"keep": "\\ud800"}


def test_json_changes_compares_lists_index_by_index():
    before = {"x": ["a", "b"]}
    after = {"x": ["c", "a", "d"]}

    changes = json_changes(before, after)

    assert changes is not None
    assert [(c.op, c.path, c.value, c.replaced) for c in changes] == [
        ("replace", "/x/0", "c", "a"),
        ("replace", "/x/1", "a", "b"),
        ("add", "/x/2", "d", None),
    ]
    assert _apply_changes(before, changes) == after


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


def test_array_insert_replaces_then_appends():
    """The `replaced` value of each replace is the item at that index in `before`."""
    before = {"x": ["a", "b"]}
    after = {"x": ["c", "d", "b"]}

    changes = json_changes(before, after)

    assert changes is not None
    assert [(c.op, c.path, c.value, c.replaced) for c in changes] == [
        ("replace", "/x/0", "c", "a"),
        ("replace", "/x/1", "d", "b"),
        ("add", "/x/2", "b", None),
    ]
    assert _apply_changes(before, changes) == after


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
    assert changes is not None
    ops = {c.path: c for c in changes}

    # Check A: index by index, then the appended item
    assert ops["/A/0"].replaced == 1
    assert ops["/A/1"].replaced == 2
    assert ops["/A/2"].op == "add"
    assert ops["/A/2"].value == 88

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

    # Index 2 held "c" in `before`
    assert "/items/0/tags/2" in ops
    assert ops["/items/0/tags/2"].op == "replace"
    assert ops["/items/0/tags/2"].value == "NEW"
    assert ops["/items/0/tags/2"].replaced == "c"


def test_json_changes_dict_with_numeric_keys():
    """Test that dicts with numeric string keys don't crash json_changes.

    JSON Patch uses the same /container/0 syntax for both list indices and
    dict keys.
    """
    before = {"tasks": {"0": {"status": "pending"}, "1": {"status": "pending"}}}
    after = {
        "tasks": {
            "0": {"status": "done"},
            "1": {"status": "pending"},
            "2": {"status": "new"},
        }
    }

    changes = json_changes(before, after)
    assert changes is not None

    ops = {c.path: c for c in changes}
    # Replace: /tasks/0/status pending -> done
    assert "/tasks/0/status" in ops
    assert ops["/tasks/0/status"].op == "replace"
    assert ops["/tasks/0/status"].replaced == "pending"
    assert ops["/tasks/0/status"].value == "done"
    # Add: /tasks/2
    assert "/tasks/2" in ops
    assert ops["/tasks/2"].op == "add"


@pytest.mark.parametrize(
    "before,after",
    [
        # jsonpatch moves 1 into its own former container (invalid path)
        ({"a": [{}, 1, [{}, 0]]}, {"a": [[], "text", [1]]}),
        # jsonpatch moves a value out of a list item it has just shifted
        (
            {"a": [[2, 0, [0, 1]], {"b": True}, True, {"b": {}}]},
            {"a": [1, {"b": {"d": {}}, "d": 1, "c": []}, {}, {}]},
        ),
        # jsonpatch's patch applies but does not reproduce the target
        (
            {"a": [["x", {}, [True]]]},
            {"a": [["y", {"a": 1, "b": "x"}, [], {"d": 1}], {}, [], {}]},
        ),
        # values moved between containers
        ({"a": [1, [2]], "b": []}, {"a": [[2]], "b": [1]}),
        ({"a": {"b": [1]}, "c": []}, {"a": {}, "c": [[1]]}),
        ({"a": [{"k": 1}, 2]}, {"a": [2], "b": {"k": 1}}),
        ({"a": [[1, 2], [3]]}, {"a": [[3], [1, 2]]}),
        # values moved within a list
        ({"a": ["x", "y", "z"]}, {"a": ["z", "x", "y"]}),
        ({"a": [{"k": 1}, {"k": 2}, {"k": 3}]}, {"a": [{"k": 3}, {"k": 1}]}),
        # dict values moved between keys, including keys needing escapes
        ({"a/b": {"k": [1]}, "c~d": 2}, {"e": {"k": [1]}, "f": 2}),
    ],
)
def test_json_changes_reproduce_target_when_values_move(
    before: dict[str, Any], after: dict[str, Any]
):
    _assert_round_trip(before, after)


def _random_json(rng: random.Random, depth: int = 0) -> Any:
    kind = rng.random()
    if depth < 4 and kind < 0.45:
        return [_random_json(rng, depth + 1) for _ in range(rng.randint(0, 6))]
    if depth < 4 and kind < 0.6:
        return {
            rng.choice("ab"): _random_json(rng, depth + 1)
            for _ in range(rng.randint(0, 2))
        }
    return rng.choice([0, 1, 1.5, "x", None, {}, [], [0], {"a": 0}])


def _mutate_json(rng: random.Random, value: Any, depth: int = 0) -> Any:
    if isinstance(value, list):
        value = [
            _mutate_json(rng, item, depth + 1) if rng.random() < 0.3 else item
            for item in value
        ]
        for _ in range(rng.randint(0, 2)):
            edit = rng.random()
            if edit < 0.4:
                value.insert(rng.randint(0, len(value)), _random_json(rng, depth + 1))
            elif edit < 0.7 and value:
                value.pop(rng.randrange(len(value)))
            elif value:
                item = value.pop(rng.randrange(len(value)))
                value.insert(rng.randint(0, len(value)), item)
        return value
    if isinstance(value, dict):
        return {
            key: _mutate_json(rng, item, depth + 1) if rng.random() < 0.4 else item
            for key, item in value.items()
        }
    return _random_json(rng, depth) if rng.random() < 0.5 else value


def test_json_changes_reproduce_target_for_random_edits():
    """Seeded probe: edits that move, insert and remove nested values.

    jsonpatch.make_patch() fails on 91 of these 3,000 pairs (80 raise, 11 differ).
    """
    rng = random.Random(0)
    for _ in range(3000):
        before = {"a": _random_json(rng)}
        if rng.random() < 0.7:
            after = {"a": _mutate_json(rng, deepcopy(before["a"]))}
        else:
            after = {"a": _random_json(rng)}
        _assert_round_trip(before, after)


def test_json_changes_replaced_values_come_from_before():
    before = {"a": [{"k": 1}, "x", [1, 2]], "b": {"c": "old"}}
    after = {"a": ["y", {"k": 1}, [1]], "b": {"c": "new"}}

    changes = json_changes(before, after)

    assert changes is not None
    assert [(c.op, c.path, c.replaced) for c in changes] == [
        ("replace", "/a/0", {"k": 1}),
        ("replace", "/a/1", "x"),
        ("remove", "/a/2/1", None),
        ("replace", "/b/c", "old"),
    ]
    assert _apply_changes(before, changes) == after


def test_jsonlines_reader_kwargs(tmp_path):
    jsonl_content = '{"a": NaN}\n{"b": 123}\n'
    json_file = tmp_path / "test.jsonl"
    json_file.write_text(jsonl_content, encoding="utf-8")

    def safe_load(s):
        return json.loads(s.replace("NaN", "null"))

    with open(json_file, "r", encoding="utf-8") as f:
        result = list(jsonlines_dataset_reader(f, loads=safe_load))

    assert result == [{"a": None}, {"b": 123}]


def test_json_dataset_reader_kwargs(tmp_path):
    json_content = '{"x": NaN, "y": Infinity, "z": -Infinity, "a": "5", "b": 5}'
    json_file = tmp_path / "test.json"
    json_file.write_text(json_content, encoding="utf-8")

    def parse_values(constant: str):
        mapping = {
            "NaN": None,
            "Infinity": float("inf"),
            "-Infinity": float("-inf"),
        }
        return mapping.get(constant, constant)

    with open(json_file, "r", encoding="utf-8") as f:
        result = list(json_dataset_reader(f, parse_constant=parse_values))

    assert result == [
        {"x": None, "y": float("inf"), "z": float("-inf"), "a": "5", "b": 5}
    ]


def test_exceeds_max_depth_measures_nesting():
    assert not exceeds_max_depth({"a": 1}, 1)
    assert exceeds_max_depth({"a": {"b": 1}}, 1)
    assert not exceeds_max_depth({"a": {"b": 1}}, 2)
    assert exceeds_max_depth([[1]], 1)
    assert not exceeds_max_depth([[1]], 2)
    assert not exceeds_max_depth("scalar", 1)


def test_exceeds_max_depth_handles_pathologically_deep_values():
    # measuring depth must not itself exhaust the interpreter stack
    deep: dict[str, object] = {"a": 1}
    for _ in range(100_000):
        deep = {"a": deep}

    assert exceeds_max_depth(deep, 100)


def test_exceeds_max_depth_does_not_blow_up_on_shared_substructure():
    # yaml anchors/aliases (reachable from model-emitted tool call arguments)
    # build a DAG whose distinct root-to-leaf paths grow exponentially with its
    # size. Re-expanding shared nodes per path would turn this sub-kilobyte
    # value into ~2**60 visits — an uninterruptible CPU hang on the event loop.
    dag: object = ["leaf"]
    for _ in range(60):
        dag = [dag, dag]

    assert not exceeds_max_depth(dag, 100)
    assert exceeds_max_depth(dag, 30)


def test_exceeds_max_depth_reexpands_shared_node_reached_deeper():
    # a node shared between a shallow and a deeper path must be measured from
    # the deeper one — skipping it there would under-report the real depth
    shared = {"deep": {"deeper": {"deepest": 1}}}
    for value in (
        {"shallow_first": shared, "deep_path": {"a": {"b": {"c": shared}}}},
        {"deep_path": {"a": {"b": {"c": shared}}}, "shallow_last": shared},
    ):
        assert exceeds_max_depth(value, 6)
        assert not exceeds_max_depth(value, 7)


def test_exceeds_max_depth_traverses_frozensets():
    # pydantic-core serializes frozensets recursively, so a deep frozenset
    # chain must count toward depth — otherwise it slips past the
    # condense-time guard and fails at flush-time serialization instead
    deep: frozenset[object] = frozenset(["leaf"])
    for _ in range(300):
        deep = frozenset([deep])

    assert exceeds_max_depth(deep, 250)
    assert not exceeds_max_depth(frozenset([frozenset(["leaf"])]), 2)


def test_exceeds_max_depth_traverses_pydantic_extra_fields():
    # extra="allow" models keep extra values in __pydantic_extra__ rather than
    # __dict__; pydantic-core serializes them recursively all the same, so
    # they must count toward depth like declared fields do
    class Declared(BaseModel):
        value: object

    class Extras(BaseModel):
        model_config = ConfigDict(extra="allow")

    deep: object = 1
    for _ in range(50):
        deep = {"a": deep}

    assert exceeds_max_depth(Declared(value=deep), 10)
    assert exceeds_max_depth(Extras(**{"extra_value": deep}), 10)
    assert not exceeds_max_depth(Extras(**{"extra_value": {"a": 1}}), 3)
    assert not exceeds_max_depth(Extras(), 1)


def test_exceeds_max_depth_terminates_on_cycles():
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    assert exceeds_max_depth(cyclic, 100)

    cyclic_list: list[object] = []
    cyclic_list.append(cyclic_list)
    assert exceeds_max_depth(cyclic_list, 100)


def test_excluding_object_builder_skips_excluded_top_level_keys() -> None:
    from inspect_ai._util.json import ExcludingObjectBuilder, get_ijson_backend

    document = (
        b'{"id": 1, "events": [{"a": {"b": 2}}, 3], "input": "q", '
        b'"nested": {"events": "kept"}}'
    )
    builder = ExcludingObjectBuilder({"events", "missing"})
    for _prefix, event, value in get_ijson_backend().parse(document):
        builder.event(event, value)
    # only top-level keys are excluded; a same-named nested key is kept
    assert builder.data == {"id": 1, "input": "q", "nested": {"events": "kept"}}
