from __future__ import annotations

import abc
from contextvars import ContextVar
from typing import TYPE_CHECKING, Literal

from inspect_ai.util._counter import ModelUsageCounterNode, get_counter_leaf_node

if TYPE_CHECKING:
    # TaskState is used as a type hint only - prevent circular import.
    from inspect_ai.solver._task_state import TaskState

# Stores the current execution context's leaf _TokenLimitNode.
# Same data structure as in the util._counter module.
leaf_node: ContextVar[_TokenLimitNode | None] = ContextVar(
    "leaf_node_limit", default=None
)


# TODO: Should/could we drop "Sample" terminology?
class SampleLimitExceededError(Exception):
    """Exception raised when a sample limit is exceeded.

    Args:
       type: Type of limit exceeded.
       value: Value compared to.
       limit: Limit applied.
       message (str | None): Optional. Human readable message.
    """

    def __init__(
        self,
        type: Literal["message", "time", "working", "token", "operator", "custom"],
        *,
        value: int,
        limit: int,
        message: str | None = None,
        state: TaskState | None = None,
    ) -> None:
        self.type = type
        self.value = value
        self.limit = limit
        self.message = f"Exceeded {type} limit: {limit:,}"
        self.state = state
        super().__init__(message)

    def with_state(self, state: TaskState) -> SampleLimitExceededError:
        return SampleLimitExceededError(
            self.type,
            value=self.value,
            limit=self.limit,
            message=self.message,
            state=state,
        )


class Limit(abc.ABC):
    """Base class for all limits."""

    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type: type, exc_val: Exception, exc_tb: type) -> None:
        pass


def token_limit(limit: int | None) -> TokenLimit:
    """Create a TokenLimit."""
    return TokenLimit(limit)


class TokenLimit(Limit):
    """Limits the total number of tokens which can be used.

    The counter starts when the context manager is opened and ends when it is closed.
    The context manager can be opened multiple times, even in different execution
    contexts.

    These limits can be stacked.

    This relies on "cooperative" checking - consumers must call check_token_limit()
    themselves whenever tokens are consumed.

    When a limit is exceeded, a SampleLimitExceededError is raised.

    Args:
      limit: The maximum number of tokens that can be used while the context manager is
        open. Tokens used before the context manager was opened are not counted. A value
        of None means unlimited tokens.
    """

    def __init__(self, limit: int | None) -> None:
        self._validate_token_limit(limit)
        self._limit_value_wrapper = _LimitValueWrapper(limit)

    def __enter__(self) -> None:
        current_node = leaf_node.get()
        new_node = _TokenLimitNode(
            self._limit_value_wrapper, get_counter_leaf_node(), current_node
        )
        # Note that we don't store new_node as an instance variable, because the context
        # manager may be used across multiple execution contexts, or opened multiple
        # times.
        leaf_node.set(new_node)

    def __exit__(self, exc_type: type, exc_val: Exception, exc_tb: type) -> None:
        current_node = leaf_node.get()
        assert current_node is not None, (
            "Token limit node should not be None when exiting context manager."
        )
        leaf_node.set(current_node.parent)

    @property
    def limit(self) -> int | None:
        """Get the configured token limit value."""
        return self._limit_value_wrapper.value

    @limit.setter
    def limit(self, value: int | None) -> None:
        """Update the token limit value.

        This will affect the limit for all active token limit nodes derived from this
        context manager.

        It will also trigger a check of the token limit.
        """
        self._validate_token_limit(value)
        self._limit_value_wrapper.value = value
        check_token_limit()

    def _validate_token_limit(self, value: int | None) -> None:
        if value is not None and value < 0:
            raise ValueError("Token limit value must be a non-negative integer.")


# TODO: Should we pre-emptively drop the "token" name from this function?
def check_token_limit() -> None:
    """Check if the current token usage exceeds _any_ of the token limits.

    Within the current execution context (e.g. async task) and its parent contexts only.

    Note that all active token limits are checked, not just the most recent one.
    """
    node = leaf_node.get()
    if node is None:
        return
    node.check()


# TODO: This is just a convenience function. Should we keep it? (see docs example)
def has_token_limit_been_exceeded() -> bool:
    """Check if the current token usage exceeds _any_ of the token limits.

    Within the current execution context (e.g. async task) and its parent contexts only.

    Note that all active token limits are checked, not just the most recent one.
    """
    try:
        check_token_limit()
    except SampleLimitExceededError:
        return True
    return False


class _LimitValueWrapper:
    """Container/wrapper type for the limit value.

    This facilitates updating the limit value, which may have been passed to many
    _TokenLimitNode instances.
    """

    def __init__(self, value: int | None) -> None:
        self.value = value


class _TokenLimitNode:
    def __init__(
        self,
        limit: _LimitValueWrapper,
        counter: ModelUsageCounterNode,
        parent: _TokenLimitNode | None,
    ) -> None:
        """
        Initialize a token limit node.

        This is associated with the counter which was active when the context manager
        was opened.

        Tracks what the token usage was when the context manager was opened, and the
        (variable) limit.

        Args:
          limit: The maximum number of tokens that can be used while the context
            manager is open.
          counter: ...
          parent: ...
        """
        self._limit = limit
        self._counter = counter
        self.parent = parent
        self._initial_usage = counter.get_total_sum()

    def check(self) -> None:
        """Check if this token limit or any parent limits have been exceeded."""
        self._check_self()
        if self.parent is not None:
            self.parent.check()

    def _check_self(self) -> None:
        if self._limit.value is None:
            return
        usage = self._counter.get_total_sum() - self._initial_usage
        if usage > self._limit.value:
            print(f"Token limit exceeded: {usage} > {self._limit.value}")
            raise SampleLimitExceededError(
                "token", value=usage, limit=self._limit.value
            )
