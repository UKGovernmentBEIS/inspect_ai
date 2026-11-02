import pytest
import sniffio
from test_helpers.utils import fail_in_a_group_with_handled_context

from inspect_ai.tool._tool import ToolError
from inspect_ai.util._anyio import _flatten_exception, inner_exception


def test_crazy_with_from():
    flattened = _flatten_exception(_construct_mcp_exception(True))
    assert len(flattened) == 1
    assert str(flattened[0]) == "tool error"


def test_crazy_without_from():
    flattened = _flatten_exception(_construct_mcp_exception(False))
    assert len(flattened) == 2
    assert str(flattened[0]) == "tool error"
    assert str(flattened[1]) == "mcp error"


def _construct_mcp_exception(use_from: bool) -> Exception:
    """
    Constructs an exception "stack" that is observed when an MCP server raises a ToolError

          ┌───────────────────────┐
          │ ExceptionGroup        │
          └───────────────────────┘
               │            │
           exceptions  __context__
               │            │
               ▼            ▼
          ┌───────────────────────┐
          │ ExceptionGroup        │
          └───────────────────────┘
                     │
                 exceptions
                     │
                     ▼
          ┌───────────────────────┐
          │ ToolError             │
          └───────────────────────┘
               │            │
           __cause__   __context__
         (depending on      │
           use_from)        │
               │            │
               ▼            ▼
          ┌───────────────────────┐
          │ McpError              │
          └───────────────────────┘
    """
    inner_group: ExceptionGroup
    try:
        try:
            raise RuntimeError("mcp error")
        except RuntimeError as e:
            if use_from:
                raise ToolError("tool error") from e
            else:
                raise ToolError("tool error")
    except Exception as inner_tool_error:
        inner_group = ExceptionGroup("Inner Group", [inner_tool_error])

    try:
        try:
            raise inner_group
        except Exception as e:
            raise ExceptionGroup("Outer Group", [e])
    except Exception as wow:
        return wow


def test_circular_exception_context():
    """Test that _flatten_exception handles circular exception references without infinite recursion."""
    # Create two exceptions that reference each other circularly
    exc1 = ValueError("first exception")
    exc2 = TypeError("second exception")

    # Create a circular reference: exc1.__context__ -> exc2 -> exc1
    exc1.__context__ = exc2
    exc2.__context__ = exc1

    # This should not cause infinite recursion
    flattened = _flatten_exception(exc1)

    # Should get both exceptions, but not infinitely
    assert len(flattened) == 2
    assert any(
        isinstance(e, ValueError) and str(e) == "first exception" for e in flattened
    )
    assert any(
        isinstance(e, TypeError) and str(e) == "second exception" for e in flattened
    )


def test_circular_exception_group():
    """Test that _flatten_exception handles circular ExceptionGroup references."""
    # Create a circular reference in exception groups
    exc1 = ValueError("value error")
    exc2 = TypeError("type error")

    # Create groups that would create a cycle
    group1 = ExceptionGroup("group1", [exc1])
    group2 = ExceptionGroup("group2", [exc2])

    # Make group1 contain group2, and group2's context point back to group1
    group1 = ExceptionGroup("group1", [exc1, group2])
    group2.__context__ = group1

    # This should not cause infinite recursion
    flattened = _flatten_exception(group1)

    # Should contain the actual exceptions, not the groups
    assert len(flattened) >= 2  # At least the two base exceptions
    assert any(isinstance(e, ValueError) and str(e) == "value error" for e in flattened)
    assert any(isinstance(e, TypeError) and str(e) == "type error" for e in flattened)


def test_self_referencing_exception():
    """Test that _flatten_exception handles an exception that references itself."""
    exc = RuntimeError("self-referencing exception")
    # Make the exception reference itself
    exc.__context__ = exc

    # This should not cause infinite recursion
    flattened = _flatten_exception(exc)

    # Should get the exception exactly once
    assert len(flattened) == 1
    assert isinstance(flattened[0], RuntimeError)
    assert str(flattened[0]) == "self-referencing exception"


@pytest.mark.parametrize("outer_cause", [False, True])
async def test_inner_exception_prefers_group_members_over_context(
    outer_cause: bool,
) -> None:
    """A group's first exception is its member, not the one it was handling."""
    # members and context were ordered by a set of exceptions: try fresh ones
    for _ in range(50):
        with pytest.raises(ExceptionGroup) as excinfo:
            await fail_in_a_group_with_handled_context(outer_cause)
        group = excinfo.value
        assert isinstance(_handled_context(group), ToolError)
        assert inner_exception(group) is group.exceptions[0]


def _handled_context(group: BaseException) -> BaseException | None:
    """The handled error in the group's context, directly or in its history group."""
    context = group.__context__
    if isinstance(context, BaseExceptionGroup):
        return context.exceptions[0]
    return context


@pytest.mark.anyio
async def test_anyio_backend_matches_variant(request: pytest.FixtureRequest):
    """The actual async backend should match the anyio test variant."""
    expected = "trio" if "[trio]" in request.node.nodeid else "asyncio"
    actual = sniffio.current_async_library()
    assert actual == expected, (
        f"Variant says {expected} but actually running under {actual}"
    )
