from __future__ import annotations

import abc
import logging
import time
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from types import TracebackType
from typing import TYPE_CHECKING, Generic, Iterator, Literal, TypeVar

import anyio
from typing_extensions import Self

from inspect_ai._util.logger import warn_once

if TYPE_CHECKING:
    # These imports are used as type hints only - prevent circular imports.
    from inspect_ai.model._model_output import ModelUsage
    from inspect_ai.solver._task_state import TaskState


logger = logging.getLogger(__name__)
TNode = TypeVar("TNode", bound="_LimitNode")


class LimitExceededError(Exception):
    """Exception raised when a limit is exceeded.

    In some scenarios this error may be raised when `value >= limit` to
    prevent another operation which is guaranteed to exceed the limit from being
    wastefully performed.

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
        value: float,
        limit: float,
        message: str | None = None,
    ) -> None:
        self.type = type
        self.value = value
        self.limit = limit
        self.message = f"Exceeded {type} limit: {limit:,}"
        super().__init__(message)

    def with_state(self, state: TaskState) -> LimitExceededError:
        warn_once(
            logger,
            "LimitExceededError.with_state() is deprecated (no longer required).",
        )
        return self


class Limit(abc.ABC):
    """Base class for all limit context managers."""

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


@contextmanager
def apply_limits(limits: list[Limit]) -> Iterator[None]:
    """
    Apply a list of limits within a context manager.

    Args:
      limits: List of limits to apply while the context manager is open. Should a
        limit be exceeded, a LimitExceededError is raised.
    """
    with ExitStack() as stack:
        for limit in limits:
            stack.enter_context(limit)
        yield


def token_limit(limit: int | None) -> _TokenLimit:
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
    return _TokenLimit(limit)


def record_model_usage(usage: ModelUsage) -> None:
    """Record model usage against any active token limits.

    Does not check if the limit has been exceeded.
    """
    node = token_limit_tree.get()
    if node is None:
        return
    node.record(usage)


def check_token_limit() -> None:
    """Check if the current token usage exceeds _any_ of the token limits.

    Within the current execution context (e.g. async task) and its parent contexts only.

    Note that all active token limits are checked, not just the most recent one.
    """
    node = token_limit_tree.get()
    if node is None:
        return
    node.check()


def message_limit(limit: int | None) -> _MessageLimit:
    """Limits the number of messages in a conversation.

    The total number of messages in the conversation are compared to the limit (not just
    "new" messages). The context manager can be opened multiple times, even in different
    execution contexts.

    These limits can be stacked.

    This relies on "cooperative" checking - consumers must call check_message_limit()
    themselves whenever the message count is updated.

    When a limit is exceeded, a LimitExceededError is raised.

    Args:
      limit: The maximum conversation length (number of messages) allowed while the
        context manager is open. A value of None means unlimited messages.
    """
    return _MessageLimit(limit)


def check_message_limit(count: int, raise_for_equal: bool) -> None:
    """Check if the current message count exceeds the active message limit.

    Only the most recent message limit is checked. Ancestors are not checked.

    Args:
      count: The number of messages in the conversation.
      raise_for_equal: If True, raise an error if the message count is equal to the
        limit, otherwise, only raise an error if the message count is greater than the
        limit.
    """
    node = message_limit_tree.get()
    if node is None:
        return
    node.check(count, raise_for_equal)


def time_limit(limit: float | None) -> _TimeLimit:
    """Limits the wall clock time which can elapse.

    The timer starts when the context manager is opened and stops when it is closed.
    The context manager can be opened multiple times, even in different execution
    contexts.

    These limits can be stacked.

    When a limit is exceeded, the code block is cancelled and a LimitExceededError is
    raised.

    Uses anyio's cancellation scopes meaning that the operations within the context
    manager block are cancelled if the limit is exceeded. The LimitExceededError is
    therefore raised at the level that the time_limit() context manager was opened, not
    at the level of the operation which caused the limit to be exceeded (e.g. a call to
    generate()).

    Args:
      limit: The maximum number of seconds that can pass while the context manager is
        open. A value of None means unlimited time.
    """
    return _TimeLimit(limit)


def working_limit(limit: float | None) -> _WorkingLimit:
    """Limits the working time which can elapse.

    Working time is the wall clock time minus any waiting time e.g. waiting for a model
    respond or waiting on a semaphore.

    The timer starts when the context manager is opened and stops when it is closed.
    The context manager can be opened multiple times, even in different execution
    contexts.

    These limits can be stacked.

    When a limit is exceeded, a LimitExceededError is raised.

    Args:
      limit: The maximum number of seconds that can pass while the context manager is
        open. A value of None means unlimited time.
    """
    return _WorkingLimit(limit)


def record_waiting_time(waiting_time: float) -> None:
    node = working_limit_tree.get()
    if node is None:
        return
    node.record_waiting_time(waiting_time)


def check_working_limit() -> None:
    node = working_limit_tree.get()
    if node is None:
        return
    node.check()


class _Tree(Generic[TNode]):
    """A tree data structure of limit nodes.

    Each node has a pointer to its parent, or None if it is the root node.

    Each additional context manager inserts a new child node into the tree. The fact
    that there can be multiple execution contexts is what makes this a tree rather than
    a stack and why a context variable is used to store the leaf node.
    """

    def __init__(self, id: str) -> None:
        self._leaf_node: ContextVar[TNode | None] = ContextVar(id, default=None)

    def get(self) -> TNode | None:
        return self._leaf_node.get()

    def push(self, new_node: TNode) -> None:
        current_leaf = self._leaf_node.get()
        new_node.parent = current_leaf
        self._leaf_node.set(new_node)

    def pop(self) -> TNode:
        current_leaf = self._leaf_node.get()
        if current_leaf is None:
            raise RuntimeError("Limit tree is empty. Cannot pop from an empty tree.")
        self._leaf_node.set(current_leaf.parent)
        return current_leaf


token_limit_tree: _Tree[_TokenLimitNode] = _Tree("token_limit_tree")
# Store the message limit leaf node so that we know which limit to check in
# check_message_limit().
message_limit_tree: _Tree[_MessageLimitNode] = _Tree("message_limit_tree")
# Store the time limit leaf node so that we can exit the correct cancel scope when the
# _MessageLimit context manager is exited.
time_limit_tree: _Tree[_TimeLimitNode] = _Tree("time_limit_tree")
working_limit_tree: _Tree[_WorkingLimitNode] = _Tree("working_limit_tree")


class _LimitValueWrapper:
    """Container/wrapper type for the limit value.

    This facilitates updating the limit value, which may have been passed to many
    _TokenLimitNode instances.
    """

    def __init__(self, value: float | None) -> None:
        self.value = value

    def as_optional_int(self) -> int | None:
        return int(self.value) if self.value is not None else None


class _LimitNode:
    """Base class for all limit nodes.

    A new node instance is created every time a Limit context manager is opened.
    """

    parent: Self | None
    _limit: _LimitValueWrapper

    def __init__(self, limit: _LimitValueWrapper) -> None:
        self._limit = limit


class _TokenLimit(Limit):
    def __init__(self, limit: int | None) -> None:
        self._validate_token_limit(limit)
        self._limit_value_wrapper = _LimitValueWrapper(limit)

    def __enter__(self) -> Limit:
        # State is not stored as instance variables, because the context manager may be
        # opened multiple times including across different execution contexts.
        token_limit_tree.push(_TokenLimitNode(self._limit_value_wrapper))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        token_limit_tree.pop()

    @property
    def limit(self) -> int | None:
        """Get the configured token limit value."""
        return self._limit_value_wrapper.as_optional_int()

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
            raise ValueError(
                f"Token limit value must be a non-negative integer or None: {value}"
            )


class _TokenLimitNode(_LimitNode):
    def __init__(self, limit: _LimitValueWrapper) -> None:
        from inspect_ai.model._model_output import ModelUsage

        super().__init__(limit)
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
        from inspect_ai.log._transcript import SampleLimitEvent, transcript

        if self._limit.value is None:
            return
        total = self._usage.total_tokens
        limit = self._limit.value
        if total > limit:
            message = f"Token limit exceeded. value: {total:,}; limit: {limit:,}"
            transcript()._event(
                SampleLimitEvent(type="token", limit=limit, message=message)
            )
            raise LimitExceededError("token", value=total, limit=limit, message=message)


class _MessageLimit(Limit):
    def __init__(self, limit: int | None) -> None:
        self._validate_message_limit(limit)
        self._limit_value_wrapper = _LimitValueWrapper(limit)

    def __enter__(self) -> Limit:
        # State is not stored as instance variables, because the context manager may be
        # opened multiple times including across different execution contexts.
        message_limit_tree.push(_MessageLimitNode(self._limit_value_wrapper))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        message_limit_tree.pop()

    @property
    def limit(self) -> int | None:
        """Get the configured message limit value."""
        return self._limit_value_wrapper.as_optional_int()

    @limit.setter
    def limit(self, value: int | None) -> None:
        """Update the message limit value.

        This will affect the limit for all active message limit nodes derived from this
        context manager.

        This does not trigger a check of the message limit (which could now have been
        exceeded).
        """
        self._validate_message_limit(value)
        self._limit_value_wrapper.value = value

    def _validate_message_limit(self, value: int | None) -> None:
        if value is not None and value < 0:
            raise ValueError(
                f"Message limit value must be a non-negative integer or None: {value}"
            )


class _MessageLimitNode(_LimitNode):
    def check(self, count: int, raise_for_equal: bool) -> None:
        """Check if this message limit has been exceeded.

        Does not check parents.
        """
        from inspect_ai.log._transcript import SampleLimitEvent, transcript

        if self._limit.value is None:
            return
        limit = self._limit.value
        if count > limit or (raise_for_equal and count == limit):
            reached_or_exceeded = "reached" if count == limit else "exceeded"
            message = (
                f"Message limit {reached_or_exceeded}. count: {count:,}; "
                f"limit: {limit:,}"
            )
            transcript()._event(
                SampleLimitEvent(type="message", limit=limit, message=message)
            )
            raise LimitExceededError(
                "message", value=count, limit=limit, message=message
            )


class _TimeLimit(Limit):
    def __init__(self, limit: float | None) -> None:
        self._validate_time_limit(limit)
        self._limit = _LimitValueWrapper(limit)

    def __enter__(self) -> Limit:
        # State is not stored as instance variables, because the context manager may be
        # opened multiple times including across different execution contexts.
        time_limit_tree.push(_TimeLimitNode(self._limit))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        popped = time_limit_tree.pop()
        popped.exit(exc_type, exc_val, exc_tb)

    def _validate_time_limit(self, value: float | None) -> None:
        if value is not None and value < 0:
            raise ValueError(
                f"Time limit value must be a non-negative float or None: {value}"
            )


class _TimeLimitNode(_LimitNode):
    def __init__(self, limit: _LimitValueWrapper) -> None:
        super().__init__(limit)
        self._cancel_scope = anyio.move_on_after(limit.value)
        self._cancel_scope.__enter__()

    def exit(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        from inspect_ai.log._transcript import SampleLimitEvent, transcript

        self._cancel_scope.__exit__(exc_type, exc_val, exc_tb)
        limit = self._limit.value
        if self._cancel_scope.cancel_called and limit is not None:
            message = f"Time limit exceeded. limit: {limit} seconds"
            transcript()._event(
                SampleLimitEvent(type="time", message=message, limit=limit)
            )
            raise LimitExceededError(
                "time", value=limit, limit=limit, message=message
            ) from exc_val


class _WorkingLimit(Limit):
    def __init__(self, limit: float | None) -> None:
        self._validate_time_limit(limit)
        self._limit = _LimitValueWrapper(limit)

    def __enter__(self) -> Limit:
        # State is not stored as instance variables, because the context manager may be
        # opened multiple times including across different execution contexts.
        working_limit_tree.push(_WorkingLimitNode(self._limit))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        working_limit_tree.pop()

    def _validate_time_limit(self, value: float | None) -> None:
        if value is not None and value < 0:
            raise ValueError(
                f"Working time limit value must be a non-negative float or None: {value}"
            )


class _WorkingLimitNode(_LimitNode):
    def __init__(self, limit: _LimitValueWrapper) -> None:
        super().__init__(limit)
        self._start_time = time.monotonic()
        self._waiting_time = 0.0

    def record_waiting_time(self, waiting_time: float) -> None:
        """Record waiting time for this node and its parent nodes."""
        if self.parent is not None:
            self.parent.record_waiting_time(waiting_time)
        self._waiting_time += waiting_time

    def check(self) -> None:
        """Check if this working time limit or any parent limits have been exceeded."""
        self._check_self()
        if self.parent is not None:
            self.parent.check()

    def _check_self(self) -> None:
        from inspect_ai.log._transcript import SampleLimitEvent, transcript

        if self._limit.value is None:
            return
        working_time = time.monotonic() - self._start_time - self._waiting_time
        limit = self._limit.value
        if working_time > limit:
            message = f"Working time limit exceeded. limit: {limit} seconds"
            transcript()._event(
                SampleLimitEvent(type="working", message=message, limit=limit)
            )
            raise LimitExceededError(
                "working", value=working_time, limit=limit, message=message
            )
