from typing import Any

import pytest
from jsonpath_ng.ext import parse  # type: ignore

from inspect_ai.analysis.beta._dataframe.validate import (
    Schema,
    jsonpath_in_schema,
    resolved_schema,
)
from inspect_ai.log import EvalLog


@pytest.fixture(scope="session")
def expanded_schema() -> Schema:
    """Fully dereferenced JSON-Schema for EvalLog.

    Uses `jsonref.replace_refs` with an explicit base URI so internal
    fragments like '#/$defs/Foo' resolve without IOError.
    """
    return resolved_schema(EvalLog)


def assert_valid(expr: str, schema: dict[str, Any]) -> None:
    """Assert that `expr` is accepted by the walker."""
    jp = parse(expr)
    assert jsonpath_in_schema(jp, schema), f"{expr!r} should be valid"


def assert_invalid(expr: str, schema: dict[str, Any]) -> None:
    """Assert that `expr` is rejected by the walker."""
    jp = parse(expr)
    assert not jsonpath_in_schema(jp, schema), f"{expr!r} should be invalid"


def test_basic(expanded_schema: dict[str, Any]) -> None:
    assert_valid("eval.run_id", expanded_schema)


def test_nullable_branch(expanded_schema: dict[str, Any]) -> None:
    assert_valid("eval.revision.origin", expanded_schema)


def test_open_dict(expanded_schema: dict[str, Any]) -> None:
    assert_valid("eval.metadata.foo", expanded_schema)


def test_closed_object(expanded_schema: dict[str, Any]) -> None:
    assert_invalid("eval.revision.foo", expanded_schema)


def test_array_wildcard(expanded_schema: dict[str, Any]) -> None:
    """Wildcard over array items succeeds."""
    assert_valid("results.scores[*].scorer", expanded_schema)


def test_array_index_zero(expanded_schema: dict[str, Any]) -> None:
    """Concrete index inside homogenous array succeeds."""
    assert_valid("results.scores[0].scorer", expanded_schema)


def test_array_negative_index(expanded_schema: dict[str, Any]) -> None:
    """Negative index -1 should resolve to the last item."""
    assert_valid("results.scores[-1].scorer", expanded_schema)


def test_wildcard_object_properties(expanded_schema: dict[str, Any]) -> None:
    """Wildcard over object properties succeeds."""
    assert_valid("eval.packages.*", expanded_schema)


def test_extra_key_in_closed_leaf(expanded_schema: dict[str, Any]) -> None:
    """'solver' is a plain string → adding a child key must fail."""
    assert_invalid("eval.solver.foo", expanded_schema)


def test_skip_filter_expression(expanded_schema: dict[str, Any]) -> None:
    """Filter expression should be skipped (returns True)."""
    jp = parse("results.scores[?@.name == 'accuracy']")
    assert jsonpath_in_schema(jp, expanded_schema) is True


def test_skip_slice_expression(expanded_schema: dict[str, Any]) -> None:
    """True slice 1:5 is in UNSUPPORTED and therefore skipped."""
    jp = parse("results.scores[1:5].name")
    assert jsonpath_in_schema(jp, expanded_schema) is True
