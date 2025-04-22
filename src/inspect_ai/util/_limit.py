from __future__ import annotations

import abc
import logging
from contextvars import ContextVar
from types import TracebackType
from typing import TYPE_CHECKING, Literal

from inspect_ai._util.logger import warn_once

if TYPE_CHECKING:
    # These imports are used as type hints only - prevent circular imports.
    from inspect_ai.model._conversation import ModelConversation
    from inspect_ai.model._model_output import ModelUsage
    from inspect_ai.solver._task_state import TaskState


logger = logging.getLogger(__name__)

# Stores the current execution context's leaf _TokenLimitNode.
# The resulting data structure is a tree of _TokenLimitNode nodes which each
# have a pointer to their parent node. Each additional context manager inserts a new
# child node into the tree. The fact that there can be multiple execution contexts is
# what makes this a tree rather than a stack.
token_limit_leaf_node: ContextVar[_TokenLimitNode | None] = ContextVar(
    "token_leaf_node", default=None
)


class LimitExceededError(Exception):
    """Exception raised when a limit is exceeded.

    Args:
       type: Type of limit exceeded.
       value: Value compared to.
       limit: Limit applied.
       message (str | None): Optional. Human readable message.
       conversation: ModelConversation | None: Optional. A ModelConversation, TaskState
         or AgentState if conversation should be overridden for scoring purposes.
    """

    def __init__(
        self,
        type: Literal["message", "time", "working", "token", "operator", "custom"],
        *,
        value: int,
        limit: int,
        message: str | None = None,
        conversation: ModelConversation | None = None,
    ) -> None:
        self.type = type
        self.value = value
        self.limit = limit
        self.message = f"Exceeded {type} limit: {limit:,}"
        self.conversation = conversation
        super().__init__(message)

    def with_state(self, state: TaskState) -> LimitExceededError:
        warn_once(
            logger,
            "LimitExceededError.with_state() is deprecated. Please use "
            "LimitExceededError.with_conversation() instead.",
        )
        return self.with_conversation(state)

    def with_conversation(self, conversation: ModelConversation) -> LimitExceededError:
        return LimitExceededError(
            self.type,
            value=self.value,
            limit=self.limit,
            message=self.message,
            conversation=conversation,
        )


class Limit(abc.ABC):
    """Base class for all limits."""

    @abc.abstractmethod
    def __enter__(self) -> Limit:
        pass

    @abc.abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass


def record_model_usage(usage: ModelUsage) -> None:
    """Record model usage against any active token limits."""
    node = token_limit_leaf_node.get()
    if node is None:
        return
    node.record(usage)


def check_token_limit() -> None:
    """Check if the current token usage exceeds _any_ of the token limits.

    Within the current execution context (e.g. async task) and its parent contexts only.

    Note that all active token limits are checked, not just the most recent one.
    """
    node = token_limit_leaf_node.get()
    if node is None:
        return
    node.check()


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

    When a limit is exceeded, a LimitExceededError is raised.

    Args:
      limit: The maximum number of tokens that can be used while the context manager is
        open. Tokens used before the context manager was opened are not counted. A value
        of None means unlimited tokens.
    """

    def __init__(self, limit: int | None) -> None:
        self._validate_token_limit(limit)
        self._limit_value_wrapper = _LimitValueWrapper(limit)

    def __enter__(self) -> Limit:
        current_node = token_limit_leaf_node.get()
        new_node = _TokenLimitNode(self._limit_value_wrapper, current_node)
        # Note that we don't store new_node as an instance variable, because the context
        # manager may be used across multiple execution contexts, or opened multiple
        # times.
        token_limit_leaf_node.set(new_node)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        current_node = token_limit_leaf_node.get()
        assert current_node is not None, (
            "Token limit node should not be None when exiting context manager."
        )
        token_limit_leaf_node.set(current_node.parent)

    @property
    def limit(self) -> int | None:
        """Get the configured token limit value."""
        return self._limit_value_wrapper.value

    @limit.setter
    def limit(self, value: int | None) -> None:
        """Update the token limit value.

        This will affect the limit for all active token limit nodes derived from this
        context manager.

        This does not trigger a check of the token limit (which could now have been
        exceeded).
        """
        self._validate_token_limit(value)
        self._limit_value_wrapper.value = value

    def _validate_token_limit(self, value: int | None) -> None:
        if value is not None and value < 0:
            raise ValueError("Token limit value must be a non-negative integer.")


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
        parent: _TokenLimitNode | None,
    ) -> None:
        """
        Initialize a token limit node.

        Forms part of a tree structure. Each node has a pointer to its parent, or None
        if it is the root node.

        Tracks the token usage for this node and its parent nodes and checks if the
        usage has exceeded a (variable) limit.

        Args:
          limit: The maximum number of tokens that can be used while the context
            manager is open.
          parent: The parent node in the tree.
        """
        from inspect_ai.model._model_output import ModelUsage

        self._limit = limit
        self.parent = parent
        self._usage = ModelUsage()

    def record(self, usage: ModelUsage) -> None:
        """Record model usage for this node and its parent nodes."""
        if self.parent is not None:
            self.parent.record(usage)
        self._usage += usage

    def check(self) -> None:
        """Check if this token limit or any parent limits have been exceeded."""
        self._check_self()
        if self.parent is not None:
            self.parent.check()

    def _check_self(self) -> None:
        if self._limit.value is None:
            return
        total = self._usage.total_tokens
        if total > self._limit.value:
            raise LimitExceededError("token", value=total, limit=self._limit.value)
