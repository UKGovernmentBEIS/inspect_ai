from __future__ import annotations

import abc
import logging
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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
TNode = TypeVar("TNode", bound="_Node")


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
       source (Limit | None): Optional. The `Limit` instance which was responsible for raising this error.
    """

    def __init__(
        self,
        type: Literal["message", "time", "working", "token", "operator", "custom"],
        *,
        value: float,
        limit: float,
        message: str | None = None,
        source: Limit | None = None,
    ) -> None:
        self.type = type
        self.value = value
        self.value_str = self._format_float_or_int(value)
        self.limit = limit
        self.limit_str = self._format_float_or_int(limit)
        self.message = f"Exceeded {type} limit: {limit:,}"
        self.source = source
        super().__init__(message)

    def with_state(self, state: TaskState) -> LimitExceededError:
        warn_once(
            logger,
            "LimitExceededError.with_state() is deprecated (no longer required).",
        )
        return self

    def _format_float_or_int(self, value: float | int) -> str:
        if isinstance(value, int):
            return f"{value:,}"
        else:
            return f"{value:,.2f}"


class Limit(abc.ABC):
    """Base class for all limit context managers."""

    def __init__(self) -> None:
        self._entered = False

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

    @property
    @abc.abstractmethod
    def limit(self) -> float | None:
        """The value of the limit being applied.

        Can be None which represents no limit.
        """
        pass

    @property
    @abc.abstractmethod
    def usage(self) -> float:
        """The current usage of the resource being limited."""
        pass

    @property
    def remaining(self) -> float | None:
        """The remaining "unused" amount of the resource being limited.

        Returns None if the limit is None.
        """
        if self.limit is None:
            return None
        return self.limit - self.usage

    def _check_reuse(self) -> None:
        if self._entered:
            raise RuntimeError(
                "Each Limit may only be used once in a single 'with' block. Please "
                "create a new instance of the Limit."
            )
        self._entered = True


@contextmanager
def apply_limits(
    limits: list[Limit], catch_errors: bool = False
) -> Iterator[LimitScope]:
    """
    Apply a list of limits within a context manager.

    Optionally catches any `LimitExceededError` raised by the applied limits, while
    allowing other limit errors from any other scope (e.g. the Sample level) to
    propagate.

    Yields a `LimitScope` object which can be used once the context manager is closed
    to determine which, if any, limits were exceeded.

    Args:
      limits: List of limits to apply while the context manager is open. Should a
        limit be exceeded, a `LimitExceededError` is raised.
      catch_errors: If True, catch any `LimitExceededError` raised by the applied
        limits. Callers can determine whether any limits were exceeded by checking the
        limit_error property of the `LimitScope` object yielded by this function. If
        False, all `LimitExceededError` exceptions will be allowed to propagate.
    """
    limit_scope = LimitScope()
    # Try scope is outside the `with ExitStack()` so that we can catch any errors raised
    # when exiting it (which will be where time_limit() would raise LimitExceededError).
    try:
        with ExitStack() as stack:
            for limit in limits:
                stack.enter_context(limit)
            yield limit_scope
    except LimitExceededError as e:
        # If it was not one of the limits we applied.
        if e.source is None or e.source not in limits:
            raise
        limit_scope.limit_error = e
        if not catch_errors:
            raise


class LimitScope:
    """Object returned from `apply_limits()`.

    Used to check which, if any, limits were exceeded.
    """

    def __init__(self) -> None:
        self.limit_error: LimitExceededError | None = None


@dataclass
class SampleLimits:
    """Data class to hold the limits applied to a Sample.

    This is used to return the limits from `sample_limits()`.
    """

    token: Limit
    """Token limit."""

    message: Limit
    """Message limit."""

    working: Limit
    """Working limit."""

    time: Limit
    """Time limit."""


def sample_limits() -> SampleLimits:
    """Get the top-level limits applied to the current `Sample`."""

    def get_root_node(node: TNode | None, name: str) -> TNode:
        if node is None:
            raise RuntimeError(
                f"No {name} limit node found. Is there a running sample?"
            )
        while node.parent is not None:
            node = node.parent
        return node

    return SampleLimits(
        token=get_root_node(token_limit_tree.get(), "token"),
        message=get_root_node(message_limit_tree.get(), "message"),
        working=get_root_node(working_limit_tree.get(), "working"),
        time=get_root_node(time_limit_tree.get(), "time"),
    )


def token_limit(limit: int | None) -> _TokenLimit:
    """Limits the total number of tokens which can be used.

    The counter starts when the context manager is opened and ends when it is closed.

    These limits can be stacked.

    This relies on "cooperative" checking - consumers must call `check_token_limit()`
    themselves whenever tokens are consumed.

    When a limit is exceeded, a `LimitExceededError` is raised.

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
    "new" messages).

    These limits can be stacked.

    This relies on "cooperative" checking - consumers must call check_message_limit()
    themselves whenever the message count is updated.

    When a limit is exceeded, a `LimitExceededError` is raised.

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

    These limits can be stacked.

    When a limit is exceeded, the code block is cancelled and a `LimitExceededError` is
    raised.

    Uses anyio's cancellation scopes meaning that the operations within the context
    manager block are cancelled if the limit is exceeded. The `LimitExceededError` is
    therefore raised at the level that the `time_limit()` context manager was opened,
    not at the level of the operation which caused the limit to be exceeded (e.g. a call
    to `generate()`). Ensure you handle `LimitExceededError` at the level of opening the context manager.

    Args:
      limit: The maximum number of seconds that can pass while the context manager is
        open. A value of None means unlimited time.
    """
    return _TimeLimit(limit)


def working_limit(limit: float | None) -> _WorkingLimit:
    """Limits the working time which can elapse.

    Working time is the wall clock time minus any waiting time e.g. waiting before
    retrying in response to rate limits or waiting on a semaphore.

    The timer starts when the context manager is opened and stops when it is closed.

    These limits can be stacked.

    When a limit is exceeded, a `LimitExceededError` is raised.

    Args:
      limit: The maximum number of seconds of working that can pass while the context
        manager is open. A value of None means unlimited time.
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

    Each node has a pointer to its parent, or None if it is a root node.

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


token_limit_tree: _Tree[_TokenLimit] = _Tree("token_limit_tree")
message_limit_tree: _Tree[_MessageLimit] = _Tree("message_limit_tree")
working_limit_tree: _Tree[_WorkingLimit] = _Tree("working_limit_tree")
time_limit_tree: _Tree[_TimeLimit] = _Tree("time_limit_tree")


class _Node:
    """Mixin for objects used as nodes in a limit tree.

    This allows us to have an "internal" parent property which is not exported as part
    of the public API.
    """

    parent: Self | None

    def _pop_and_check_identity(self, tree: _Tree[TNode]) -> None:
        popped = tree.pop()
        if popped is not self:
            raise RuntimeError(
                "The limit context manager being closed is not the leaf node in the "
                "tree. Make sure to open and close the context managers in a "
                "stack-like manner using a `with` statement."
            )


class _TokenLimit(Limit, _Node):
    def __init__(self, limit: int | None) -> None:
        from inspect_ai.model._model_output import ModelUsage

        super().__init__()
        self._validate_token_limit(limit)
        self._limit = limit
        self._usage = ModelUsage()

    def __enter__(self) -> Limit:
        super()._check_reuse()
        token_limit_tree.push(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._pop_and_check_identity(token_limit_tree)

    @property
    def usage(self) -> float:
        return self._usage.total_tokens

    @property
    def limit(self) -> int | None:
        """Get the configured token limit value."""
        return self._limit

    @limit.setter
    def limit(self, value: int | None) -> None:
        """Update the token limit value.

        This does not trigger a check of the token limit (which could now have been
        exceeded).
        """
        self._validate_token_limit(value)
        self._limit = value

    def record(self, usage: ModelUsage) -> None:
        """Record model usage for this node and its ancestor nodes."""
        if self.parent is not None:
            self.parent.record(usage)
        self._usage += usage

    def check(self) -> None:
        """Check if this token limit or any ancestor limits have been exceeded.

        The checks occur from root to leaf. This is so that if multiple limits are
        simultaneously exceeded, the outermost (closest to root) one raises the error,
        preventing certain sub-agent architectures from ending up in an infinite loop.
        """
        if self.parent is not None:
            self.parent.check()
        self._check_self()

    def _validate_token_limit(self, value: int | None) -> None:
        if value is not None and value < 0:
            raise ValueError(
                f"Token limit value must be a non-negative integer or None: {value}"
            )

    def _check_self(self) -> None:
        from inspect_ai.log._transcript import SampleLimitEvent, transcript

        if self.limit is None:
            return
        total = self._usage.total_tokens
        if total > self.limit:
            message = f"Token limit exceeded. value: {total:,}; limit: {self.limit:,}"
            transcript()._event(
                SampleLimitEvent(type="token", limit=self.limit, message=message)
            )
            raise LimitExceededError(
                "token", value=total, limit=self.limit, message=message, source=self
            )


class _MessageLimit(Limit, _Node):
    def __init__(self, limit: int | None) -> None:
        super().__init__()
        self._validate_message_limit(limit)
        self._limit = limit

    def __enter__(self) -> Limit:
        super()._check_reuse()
        message_limit_tree.push(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._pop_and_check_identity(message_limit_tree)

    @property
    def usage(self) -> float:
        raise NotImplementedError(
            "Retrieving the message count from a limit is not supported. Please query "
            "the messages property on the task or agent state instead."
        )

    @property
    def limit(self) -> int | None:
        """Get the configured message limit value."""
        return self._limit

    @limit.setter
    def limit(self, value: int | None) -> None:
        """Update the message limit value.

        This will affect the limit for all active message limit nodes derived from this
        context manager.

        This does not trigger a check of the message limit (which could now have been
        exceeded).
        """
        self._validate_message_limit(value)
        self._limit = value

    def check(self, count: int, raise_for_equal: bool) -> None:
        """Check if this message limit has been exceeded.

        Does not check ancestors.
        """
        from inspect_ai.log._transcript import SampleLimitEvent, transcript

        if self.limit is None:
            return
        if count > self.limit or (raise_for_equal and count == self.limit):
            reached_or_exceeded = "reached" if count == self.limit else "exceeded"
            message = (
                f"Message limit {reached_or_exceeded}. count: {count:,}; "
                f"limit: {self.limit:,}"
            )
            transcript()._event(
                SampleLimitEvent(type="message", limit=self.limit, message=message)
            )
            raise LimitExceededError(
                "message", value=count, limit=self.limit, message=message, source=self
            )

    def _validate_message_limit(self, value: int | None) -> None:
        if value is not None and value < 0:
            raise ValueError(
                f"Message limit value must be a non-negative integer or None: {value}"
            )


class _TimeLimit(Limit, _Node):
    def __init__(self, limit: float | None) -> None:
        super().__init__()
        _validate_time_limit("Time", limit)
        self._limit = limit
        self._start_time: float | None = None
        self._end_time: float | None = None

    def __enter__(self) -> Limit:
        super()._check_reuse()
        time_limit_tree.push(self)
        self._cancel_scope = anyio.move_on_after(self._limit)
        self._cancel_scope.__enter__()
        self._start_time = anyio.current_time()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        from inspect_ai.log._transcript import SampleLimitEvent, transcript

        self._cancel_scope.__exit__(exc_type, exc_val, exc_tb)
        self._end_time = anyio.current_time()
        self._pop_and_check_identity(time_limit_tree)
        if self._cancel_scope.cancel_called and self._limit is not None:
            message = f"Time limit exceeded. limit: {self._limit} seconds"
            assert self._start_time is not None
            # Note we've measured the elapsed time independently of anyio's cancel scope
            # so this is an approximation.
            time_elapsed = self._end_time - self._start_time
            transcript()._event(
                SampleLimitEvent(type="time", message=message, limit=self._limit)
            )
            raise LimitExceededError(
                "time",
                value=time_elapsed,
                limit=self._limit,
                message=message,
                source=self,
            ) from exc_val

    @property
    def limit(self) -> float | None:
        return self._limit

    @property
    def usage(self) -> float:
        if self._start_time is None:
            return 0.0
        if self._end_time is None:
            return anyio.current_time() - self._start_time
        return self._end_time - self._start_time


class _WorkingLimit(Limit, _Node):
    def __init__(self, limit: float | None) -> None:
        super().__init__()
        _validate_time_limit("Working time", limit)
        self._limit = limit
        self.parent: _WorkingLimit | None = None
        self._start_time: float | None = None
        self._end_time: float | None = None

    def __enter__(self) -> Limit:
        super()._check_reuse()
        self._start_time = anyio.current_time()
        self._waiting_time = 0.0
        working_limit_tree.push(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._end_time = anyio.current_time()
        self._pop_and_check_identity(working_limit_tree)

    @property
    def limit(self) -> float | None:
        return self._limit

    @property
    def usage(self) -> float:
        if self._start_time is None:
            return 0.0
        if self._end_time is None:
            return anyio.current_time() - self._start_time - self._waiting_time
        return self._end_time - self._start_time - self._waiting_time

    def record_waiting_time(self, waiting_time: float) -> None:
        """Record waiting time for this node and its ancestor nodes."""
        if self.parent is not None:
            self.parent.record_waiting_time(waiting_time)
        self._waiting_time += waiting_time

    def check(self) -> None:
        """Check if this working time limit or any ancestor limits have been exceeded.

        The checks occur from root to leaf. This is so that if multiple limits are
        simultaneously exceeded, the outermost (closest to root) one raises the error,
        preventing certain sub-agent architectures from ending up in an infinite loop.
        """
        if self.parent is not None:
            self.parent.check()
        self._check_self()

    def _check_self(self) -> None:
        from inspect_ai.log._transcript import SampleLimitEvent, transcript

        if self._limit is None:
            return
        if self.usage > self._limit:
            message = f"Working time limit exceeded. limit: {self._limit} seconds"
            transcript()._event(
                SampleLimitEvent(type="working", message=message, limit=self._limit)
            )
            raise LimitExceededError(
                "working",
                value=self.usage,
                limit=self._limit,
                message=message,
                source=self,
            )


def _validate_time_limit(name: str, value: float | None) -> None:
    if value is not None and value < 0:
        raise ValueError(
            f"{name} limit value must be a non-negative float or None: {value}"
        )
