from dataclasses import dataclass, field
from typing import Any

import pytest

from inspect_ai._util.format import format_template


@dataclass
class FormatterCase:
    """Test case for format_template function."""

    params: dict[str, Any]
    template: str
    expected: str
    skip_unknown: bool = field(default=True)
    should_raise: bool = field(default=False)


def test_basic_substitution() -> None:
    """Test basic parameter substitution."""
    params = {"name": "World"}
    result = format_template("Hello {name}!", params)
    assert result == "Hello World!"


def test_multiple_substitutions() -> None:
    """Test multiple parameter substitutions."""
    params = {"first": "John", "last": "Doe"}
    result = format_template("Hello {first} {last}!", params)
    assert result == "Hello John Doe!"


def test_unknown_placeholder_skipping() -> None:
    """Test that unknown placeholders are preserved when skip_unknown is True."""
    result = format_template("Hello {unknown}!", {})
    assert result == "Hello {unknown}!"


def test_unknown_placeholder_raising() -> None:
    """Test that unknown placeholders raise KeyError when skip_unknown is False."""
    with pytest.raises(KeyError):
        format_template("Hello {unknown}!", {}, skip_unknown=False)


def test_escaped_braces() -> None:
    """Test that escaped braces are handled correctly."""
    test_cases: list[FormatterCase] = [
        FormatterCase(
            params={"name": "John"}, template="{{name}} {name}", expected="{name} John"
        ),
        FormatterCase(params={}, template="{{literal}}", expected="{literal}"),
    ]

    for case in test_cases:
        result = format_template(case.template, case.params)
        assert result == case.expected


def test_nested_attributes() -> None:
    """Test handling of nested attribute access."""

    @dataclass
    class Person:
        name: str
        age: int

    params = {"person": Person(name="John", age=30)}
    result = format_template("{person.name} is {person.age}", params)
    assert result == "John is 30"


def test_nested_dict() -> None:
    """Test handling of nested dictionary access."""
    params = {"obj": {"attr": "value"}}
    result = format_template("{obj[attr]}", params)
    assert result == "value"


def test_invalid_nested_attributes() -> None:
    """Test handling of invalid nested attribute access."""
    test_cases: list[FormatterCase] = [
        FormatterCase(
            params={"obj": {}}, template="{obj.missing}", expected="{obj.missing}"
        ),
        FormatterCase(
            params={"obj": None}, template="{obj.anything}", expected="{obj.anything}"
        ),
    ]

    for case in test_cases:
        result = format_template(case.template, case.params)
        assert result == case.expected


def test_format_specifications() -> None:
    """Test handling of format specifications."""
    test_cases: list[FormatterCase] = [
        FormatterCase(params={"num": 42}, template="{num:03d}", expected="042"),
        FormatterCase(params={"pi": 3.14159}, template="{pi:.2f}", expected="3.14"),
        FormatterCase(
            params={"text": "center"}, template="{text:^10}", expected="  center  "
        ),
    ]

    for case in test_cases:
        result = format_template(case.template, case.params)
        assert result == case.expected


def test_array_indexing() -> None:
    """Test handling of array indexing."""
    test_cases: list[FormatterCase] = [
        FormatterCase(
            params={"arr": [1, 2, 3]},
            template="{arr[0]} {arr[1]} {arr[2]}",
            expected="1 2 3",
        ),
        FormatterCase(
            params={"arr": ["first", "second"]}, template="{arr[0]}", expected="first"
        ),
    ]

    for case in test_cases:
        result = format_template(case.template, case.params)
        assert result == case.expected


def test_mixed_known_unknown() -> None:
    """Test mixing known and unknown parameters."""
    test_cases: list[FormatterCase] = [
        FormatterCase(
            params={"known": "value"},
            template="{known} and {unknown}",
            expected="value and {unknown}",
        ),
        FormatterCase(
            params={"a": 1, "b": 2},
            template="{a} {missing} {b}",
            expected="1 {missing} 2",
        ),
    ]

    for case in test_cases:
        result = format_template(case.template, case.params)
        assert result == case.expected


def test_empty_template() -> None:
    """Test handling of empty template."""
    result = format_template("", {})
    assert result == ""


def test_complex_nested_structures() -> None:
    """Test handling of complex nested data structures."""

    @dataclass
    class Address:
        street: str
        city: str

    @dataclass
    class Person:
        name: str
        address: Address
        scores: list[int]

    person = Person(
        name="John",
        address=Address(street="123 Main St", city="Anytown"),
        scores=[95, 87, 91],
    )

    test_cases: list[FormatterCase] = [
        FormatterCase(
            params={"person": person},
            template="{person.name} lives in {person.address.city}",
            expected="John lives in Anytown",
        ),
        FormatterCase(
            params={"person": person},
            template="Best score: {person.scores[0]}",
            expected="Best score: 95",
        ),
    ]

    for case in test_cases:
        result = format_template(case.template, case.params)
        assert result == case.expected


def test_unescaped_json_braces_pass_through() -> None:
    """Unescaped JSON-style braces are preserved rather than rewritten (#5256)."""
    test_cases: list[FormatterCase] = [
        # a space after the colon makes the remainder parse as a format spec
        FormatterCase(
            params={},
            template='Return output in JSON format: {"answer": "value"}.',
            expected='Return output in JSON format: {"answer": "value"}.',
        ),
        # without the space the spec is a valid width, which silently
        # swallowed the value before the fix
        FormatterCase(
            params={},
            template='Emit {"ok":1} on success.',
            expected='Emit {"ok":1} on success.',
        ),
        FormatterCase(
            params={"prompt": "Q"},
            template='{prompt} -> {"a": 1, "b": 2}',
            expected='Q -> {"a": 1, "b": 2}',
        ),
    ]

    for case in test_cases:
        result = format_template(case.template, case.params)
        assert result == case.expected


def test_unknown_placeholder_preserves_format_spec() -> None:
    """An unknown placeholder keeps its format spec and conversion verbatim."""
    test_cases: list[FormatterCase] = [
        FormatterCase(params={}, template="{custom:>10}", expected="{custom:>10}"),
        FormatterCase(params={}, template="{missing!r}", expected="{missing!r}"),
        FormatterCase(params={}, template="{missing!s:^8}", expected="{missing!s:^8}"),
        FormatterCase(
            params={"known": "v"},
            template="{known} {other:.2f}",
            expected="v {other:.2f}",
        ),
    ]

    for case in test_cases:
        result = format_template(case.template, case.params)
        assert result == case.expected


def test_escaped_braces_still_supported() -> None:
    """The {{ }} escaping introduced alongside #5174 keeps working."""
    test_cases: list[FormatterCase] = [
        FormatterCase(
            params={},
            template='Return output in JSON format: {{"answer": "value"}}.',
            expected='Return output in JSON format: {"answer": "value"}.',
        ),
        FormatterCase(
            params={"name": "John"},
            template="{{name}} {name}",
            expected="{name} John",
        ),
    ]

    for case in test_cases:
        result = format_template(case.template, case.params)
        assert result == case.expected


def test_nested_format_spec_still_expands() -> None:
    """A format spec that references another param is still expanded."""
    result = format_template("{value:>{width}}", {"value": "a", "width": 4})
    assert result == "   a"


def test_warns_for_variable_like_placeholder(caplog) -> None:
    """An unresolved identifier-shaped placeholder warns (likely a typo)."""
    import logging

    from inspect_ai._util import logger as logger_module

    logger_module._warned.clear()
    with caplog.at_level(logging.WARNING):
        result = format_template("Answer the {promt} carefully.", {})

    assert result == "Answer the {promt} carefully."
    assert any("promt" in record.message for record in caplog.records)


def test_no_warning_for_json_braces(caplog) -> None:
    """JSON-style braces are literal content and must not warn."""
    import logging

    from inspect_ai._util import logger as logger_module

    logger_module._warned.clear()
    with caplog.at_level(logging.WARNING):
        result = format_template('Emit {"ok": 1} now.', {})

    assert result == 'Emit {"ok": 1} now.'
    assert not caplog.records
