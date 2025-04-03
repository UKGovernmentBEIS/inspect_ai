# For now, this module very specific to token limits, but could be generalized to other
# limits (time, messages, etc.). Note that for cost limits, the limit would likely want
# to be a float, not an int.

from __future__ import annotations

import abc
from collections import deque
from contextvars import ContextVar

# TODO: Will this work with "parallel" agents? Do we need to ensure each has their own
# async context?
# Stores the current async context's token limit stack.
token_limit_stack_ctx_var: ContextVar[_TokenLimitStack] = ContextVar("limit_ctx_var")


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
    The context manager can be opened multiple times, even in different async contexts.

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
        current_usage = _get_token_tokens_used()
        item = _TokenLimitItem(current_usage, self._limit_value_wrapper)
        # Note that we don't store stack as an instance variable, because the context
        # manager may be used across multiple async tasks.
        stack = _TokenLimitStack.get_or_create()
        stack.push(item)

    def __exit__(self, exc_type: type, exc_val: Exception, exc_tb: type) -> None:
        stack = _TokenLimitStack.get_or_create()
        # Assume that the context manager is used in a stack-like manner (i.e. using
        # `with` statements) so pop the top item from the stack.
        stack.pop()

    @property
    def limit(self) -> int | None:
        """Get the configured token limit value."""
        return self._limit_value_wrapper.value

    @limit.setter
    def limit(self, value: int | None) -> None:
        """Update the token limit value.

        This will affect the limit for all active token limit items derived from this
        context manager.

        It will also trigger a check of the token limit.
        """
        self._validate_token_limit(value)
        self._limit_value_wrapper.value = value
        check_token_limit()

    def _validate_token_limit(self, value: int | None) -> None:
        if value is not None and value < 0:
            raise ValueError("Token limit value must be a non-negative integer.")


def check_token_limit() -> None:
    """Check if the current token usage exceeds _any_ of the token limits.

    Note that all active token limits are checked, not just the most recent one.
    """
    usage = _get_token_tokens_used()
    _TokenLimitStack.get_or_create().check(usage)


# TODO: This is just a convenience function. Should we keep it? (see docs example)
def has_token_limit_been_exceeded() -> bool:
    """Check if the current token usage exceeds _any_ of the token limits.

    Note that all active token limits are checked, not just the most recent one.
    """
    from inspect_ai.solver._limit import SampleLimitExceededError

    usage = _get_token_tokens_used()
    try:
        _TokenLimitStack.get_or_create().check(usage)
    except SampleLimitExceededError:
        return True
    return False


def _get_token_tokens_used() -> int:
    """Get the total number of tokens used in the current async context."""
    from inspect_ai.model._model import sample_total_tokens

    return sample_total_tokens()


class _LimitValueWrapper:
    """Container/wrapper type for the limit value.

    This facilitates updating the limit value, which may have been passed to many
    _TokenLimitItem instances.
    """

    def __init__(self, value: int | None) -> None:
        self.value = value


class _TokenLimitStack:
    """A stack of token limit items."""

    def __init__(self) -> None:
        self._stack: deque[_TokenLimitItem] = deque()

    def push(self, limit: _TokenLimitItem) -> None:
        self._stack.append(limit)

    def pop(self) -> None:
        self._stack.pop()

    def check(self, usage: int) -> None:
        """Check if the current token usage exceeds any of the token limits."""
        for limit in self._stack:
            limit.check(usage)

    @classmethod
    def get_or_create(cls) -> _TokenLimitStack:
        """Get the async context's token limit stack, creating it if it does not exist."""
        stack = token_limit_stack_ctx_var.get(None)
        if stack is None:
            stack = _TokenLimitStack()
            token_limit_stack_ctx_var.set(stack)
        return stack


class _TokenLimitItem:
    def __init__(self, initial_usage: int, limit: _LimitValueWrapper) -> None:
        """
        Initialize a token limit item.

        Args:
          initial_usage: Snapshot of the token usage at the time the context manager was
            opened.
          limit: The maximum number of tokens that can be used while the context
            manager is open.
        """
        self._initial_usage = initial_usage
        self._limit = limit

    def check(self, usage: int) -> None:
        """Check if the current token usage exceeds the token limit.

        Args:
          usage: The current total token usage. The initial usage is subtracted from
            this value to get the number of tokens used while the context manager was
            open.
        """
        from inspect_ai.solver._limit import SampleLimitExceededError

        if self._limit.value is None:
            return
        if usage - self._initial_usage > self._limit.value:
            raise SampleLimitExceededError(
                "token", value=usage, limit=self._limit.value
            )
