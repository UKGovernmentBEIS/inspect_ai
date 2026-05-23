import io
from contextlib import contextmanager
from typing import Any, Iterator

import pytest
from acp.schema import (
    ElicitationBooleanPropertySchema,
    ElicitationIntegerPropertySchema,
    ElicitationMultiSelectPropertySchema,
    ElicitationNumberPropertySchema,
    ElicitationSchema,
    ElicitationStringPropertySchema,
    EnumOption,
    TitledMultiSelectItems,
    UntitledMultiSelectItems,
)
from rich.console import Console
from rich.prompt import Prompt

from inspect_ai.input import InputRequest
from inspect_ai.input import console as console_module
from inspect_ai.input.console import (
    DECLINE_TOKEN,
    _ask_schema,
    console_handler,
)


def _silent_console() -> Console:
    return Console(file=io.StringIO(), width=80, force_terminal=False)


def _patch_prompt(
    monkeypatch: pytest.MonkeyPatch, responses: list[str]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    it = iter(responses)

    def fake_ask(*args: Any, **kwargs: Any) -> str:
        calls.append({"args": args, "kwargs": kwargs})
        return next(it)

    monkeypatch.setattr(Prompt, "ask", fake_ask)
    return calls


# -- string --------------------------------------------------------------


def test_string_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["alice"])
    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "accepted"
    assert result.content == {"name": "alice"}


def test_string_enum_invalid_then_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First answer isn't in the enum -> re-prompt; second is accepted.
    # We validate choices ourselves (not via Rich) so :decline keeps working.
    _patch_prompt(monkeypatch, ["purple", "green"])
    schema = ElicitationSchema(
        properties={
            "color": ElicitationStringPropertySchema(
                type="string", enum=["red", "green", "blue"]
            )
        },
        required=["color"],
    )
    result = _ask_schema("pick", schema, _silent_console())
    assert result.content == {"color": "green"}


def test_string_one_of_returns_const(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["draft"])
    schema = ElicitationSchema(
        properties={
            "status": ElicitationStringPropertySchema(
                type="string",
                one_of=[
                    EnumOption(const="draft", title="Draft"),
                    EnumOption(const="pub", title="Published"),
                ],
            )
        },
        required=["status"],
    )
    result = _ask_schema("pick", schema, _silent_console())
    assert result.content == {"status": "draft"}


def test_string_enum_accepts_decline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: :decline must work even when the property has an enum.
    _patch_prompt(monkeypatch, [DECLINE_TOKEN])
    schema = ElicitationSchema(
        properties={
            "color": ElicitationStringPropertySchema(
                type="string", enum=["red", "green", "blue"]
            )
        },
        required=["color"],
    )
    result = _ask_schema("pick", schema, _silent_console())
    assert result.outcome == "declined"


def test_string_pattern_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["nope", "ab12"])  # second matches [a-z]{2}\d{2}
    schema = ElicitationSchema(
        properties={
            "code": ElicitationStringPropertySchema(
                type="string", pattern=r"[a-z]{2}\d{2}"
            )
        },
        required=["code"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"code": "ab12"}


def test_string_min_length_reprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["ab", "abcdef"])  # first too short, second ok
    schema = ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(type="string", min_length=3)
        },
        required=["name"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"name": "abcdef"}


def test_string_max_length_reprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["abcdef", "ab"])  # first too long, second ok
    schema = ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(type="string", max_length=3)
        },
        required=["name"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"name": "ab"}


# -- integer / number ----------------------------------------------------


def test_integer_in_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["42"])
    schema = ElicitationSchema(
        properties={
            "age": ElicitationIntegerPropertySchema(
                type="integer", minimum=0, maximum=150
            )
        },
        required=["age"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"age": 42}


def test_integer_out_of_range_reprompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompt(monkeypatch, ["200", "50"])  # first too big, second ok
    schema = ElicitationSchema(
        properties={
            "age": ElicitationIntegerPropertySchema(type="integer", maximum=150)
        },
        required=["age"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"age": 50}


def test_integer_invalid_reprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["abc", "7"])
    schema = ElicitationSchema(
        properties={"n": ElicitationIntegerPropertySchema(type="integer")},
        required=["n"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"n": 7}


def test_number_accepts_float(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["1.75"])
    schema = ElicitationSchema(
        properties={"height": ElicitationNumberPropertySchema(type="number")},
        required=["height"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"height": 1.75}


# -- boolean -------------------------------------------------------------


def test_boolean_returns_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["y"])
    schema = ElicitationSchema(
        properties={"active": ElicitationBooleanPropertySchema(type="boolean")},
        required=["active"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"active": True}


def test_boolean_false_value(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["n"])
    schema = ElicitationSchema(
        properties={"active": ElicitationBooleanPropertySchema(type="boolean")},
        required=["active"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"active": False}


def test_boolean_invalid_then_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["maybe", "yes"])
    schema = ElicitationSchema(
        properties={"active": ElicitationBooleanPropertySchema(type="boolean")},
        required=["active"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"active": True}


def test_boolean_accepts_decline(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: :decline must work on boolean prompts.
    _patch_prompt(monkeypatch, [DECLINE_TOKEN])
    schema = ElicitationSchema(
        properties={"active": ElicitationBooleanPropertySchema(type="boolean")},
        required=["active"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "declined"


def test_optional_boolean_blank_omits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: optional boolean with no default should be omittable,
    # not silently coerced to False.
    _patch_prompt(monkeypatch, [""])
    schema = ElicitationSchema(
        properties={"active": ElicitationBooleanPropertySchema(type="boolean")},
        required=None,
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "accepted"
    assert result.content == {}


# -- multi-select --------------------------------------------------------


def test_multiselect_titled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["1,3"])
    schema = ElicitationSchema(
        properties={
            "colors": ElicitationMultiSelectPropertySchema(
                type="array",
                items=TitledMultiSelectItems(
                    any_of=[
                        EnumOption(const="r", title="Red"),
                        EnumOption(const="g", title="Green"),
                        EnumOption(const="b", title="Blue"),
                    ]
                ),
                min_items=1,
            )
        },
        required=["colors"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"colors": ["r", "b"]}


def test_multiselect_untitled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["2"])
    schema = ElicitationSchema(
        properties={
            "tags": ElicitationMultiSelectPropertySchema(
                type="array",
                items=UntitledMultiSelectItems(
                    type="string", enum=["python", "rust", "go"]
                ),
            )
        },
        required=["tags"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"tags": ["rust"]}


def test_multiselect_min_items_reprompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompt(monkeypatch, ["1", "1,2"])  # too few, then ok
    schema = ElicitationSchema(
        properties={
            "colors": ElicitationMultiSelectPropertySchema(
                type="array",
                items=UntitledMultiSelectItems(type="string", enum=["a", "b", "c"]),
                min_items=2,
            )
        },
        required=["colors"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"colors": ["a", "b"]}


def test_multiselect_max_items_reprompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompt(monkeypatch, ["1,2,3", "1"])  # too many, then ok
    schema = ElicitationSchema(
        properties={
            "colors": ElicitationMultiSelectPropertySchema(
                type="array",
                items=UntitledMultiSelectItems(type="string", enum=["a", "b", "c"]),
                max_items=1,
            )
        },
        required=["colors"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"colors": ["a"]}


def test_required_multiselect_empty_is_valid_without_min_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: a required array with no min_items / min_items=0 should
    # accept an empty selection (the array itself is present, just empty).
    _patch_prompt(monkeypatch, [""])
    schema = ElicitationSchema(
        properties={
            "tags": ElicitationMultiSelectPropertySchema(
                type="array",
                items=UntitledMultiSelectItems(type="string", enum=["a", "b"]),
            )
        },
        required=["tags"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "accepted"
    assert result.content == {"tags": []}


# -- required / optional / decline / cancel ------------------------------


def test_optional_blank_omits(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, [""])
    schema = ElicitationSchema(
        properties={"nick": ElicitationStringPropertySchema(type="string")},
        required=None,
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "accepted"
    assert result.content == {}


def test_required_blank_reprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["", "alice"])
    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"name": "alice"}


def test_decline_token_returns_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompt(monkeypatch, [DECLINE_TOKEN])
    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.outcome == "declined"
    assert result.content is None


async def test_keyboard_interrupt_returns_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def fake_ask_console() -> Iterator[Console]:
        yield _silent_console()

    monkeypatch.setattr(console_module, "_ask_console", fake_ask_console)

    def raise_kbd(*args: Any, **kwargs: Any) -> str:
        raise KeyboardInterrupt()

    monkeypatch.setattr(Prompt, "ask", raise_kbd)

    schema = ElicitationSchema(
        properties={"name": ElicitationStringPropertySchema(type="string")},
        required=["name"],
    )
    result = await console_handler(InputRequest(message="hi", schema=schema))
    assert result.outcome == "cancelled"


def test_multiple_properties_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_prompt(monkeypatch, ["alice", "42"])
    schema = ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(type="string"),
            "age": ElicitationIntegerPropertySchema(type="integer"),
        },
        required=["name", "age"],
    )
    result = _ask_schema("hi", schema, _silent_console())
    assert result.content == {"name": "alice", "age": 42}
