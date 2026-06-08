import json
import sys
from enum import auto

from inspect_ai._util.strenum import StrEnum


class Color(StrEnum):
    RED = "red"
    GREEN = "green"
    BLUE = auto()


def test_str_is_value() -> None:
    # the critical property: str(member) is the value, not "Color.RED"
    assert str(Color.RED) == "red"
    assert f"{Color.RED}" == "red"
    assert f"{Color.RED:>6}" == "   red"


def test_value_semantics() -> None:
    assert Color.RED == "red"  # type: ignore[comparison-overlap]
    assert isinstance(Color.RED, str)
    assert json.dumps(Color.RED) == '"red"'
    assert json.dumps({Color.RED: 1}) == '{"red": 1}'


def test_auto_lowercases_name() -> None:
    assert Color.BLUE.value == "blue"


def test_rejects_non_str_value() -> None:
    import pytest

    with pytest.raises(TypeError, match="not a string"):
        StrEnum("Bad", {"X": 1})


def test_is_stdlib_on_311() -> None:
    if sys.version_info >= (3, 11):
        import enum

        assert StrEnum is enum.StrEnum
