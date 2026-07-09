from __future__ import annotations

import abc
import ast
import logging
import math
import operator
import re
from contextlib import AbstractContextManager, ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Callable,
    Generic,
    Iterator,
    Literal,
    Mapping,
    NamedTuple,
    TypeVar,
)

import anyio
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing_extensions import Self, override

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
        type: Literal[
            "message", "time", "working", "token", "turn", "cost", "operator", "custom"
        ],
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
        self.message = message or f"Exceeded {type} limit: {limit:,}"
        self.source = source
        super().__init__(self.message)

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

    cost: Limit
    """Cost limit."""

    message: Limit
    """Message limit."""

    turn: Limit
    """Turn limit."""

    working: Limit
    """Working limit."""

    time: Limit
    """Time limit."""


def sample_limits() -> SampleLimits:
    """Get the top-level limits applied to the current `Sample`."""
    # if there is _sample_limit_data recorded then the limit trees have
    # gone out of scope for the sample so we just return that snapshot
    limit_data = _sample_limit_data.get()
    if limit_data is not None:
        return limit_data

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
        cost=get_root_node(cost_limit_tree.get(), "cost"),
        message=get_root_node(message_limit_tree.get(), "message"),
        turn=get_root_node(turn_limit_tree.get(), "turn"),
        working=get_root_node(working_limit_tree.get(), "working"),
        time=get_root_node(time_limit_tree.get(), "time"),
    )


def record_sample_limit_data(message_usage: float) -> None:
    current_limits = sample_limits()
    _sample_limit_data.set(
        SampleLimits(
            token=_LimitData(current_limits.token),
            cost=_LimitData(current_limits.cost),
            message=_LimitData(current_limits.message, usage=message_usage),
            turn=_LimitData(current_limits.turn),
            working=_LimitData(current_limits.working),
            time=_LimitData(current_limits.time),
        )
    )


_sample_limit_data: ContextVar[SampleLimits | None] = ContextVar(
    "SampleLimitData", default=None
)


_TOKEN_FORMULA_VARS = ("input", "output")
"""Variables available in a token limit metering formula."""

_TOKEN_FORMULA_BINOPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_TOKEN_FORMULA_UNARYOPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _compile_token_formula(
    formula: str,
) -> Callable[[Mapping[str, float]], float]:
    """Parse and validate an arithmetic token metering formula.

    Supports `+ - * /`, parentheses, unary minus, numeric literals, and the
    variables in `_TOKEN_FORMULA_VARS`. The formula is validated eagerly (so an
    invalid formula raises `ValueError` at construction, not mid-run) and a
    closure evaluating it against a variable mapping is returned.

    Args:
      formula: Arithmetic expression, e.g. "(input * 0.1) + output".
    """
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as ex:
        raise ValueError(f"token limit: invalid formula {formula!r}: {ex.msg}") from ex

    def validate(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            validate(node.body)
        elif isinstance(node, ast.BinOp) and type(node.op) in _TOKEN_FORMULA_BINOPS:
            validate(node.left)
            validate(node.right)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in _TOKEN_FORMULA_UNARYOPS:
            validate(node.operand)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            pass
        elif isinstance(node, ast.Name):
            if node.id not in _TOKEN_FORMULA_VARS:
                raise ValueError(
                    f"token limit: unknown variable {node.id!r} in formula "
                    f"{formula!r} (allowed: {', '.join(_TOKEN_FORMULA_VARS)})"
                )
        else:
            raise ValueError(
                f"token limit: unsupported expression in formula {formula!r}"
            )

    validate(tree)

    def evaluate(node: ast.AST, vars: Mapping[str, float]) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body, vars)
        if isinstance(node, ast.BinOp):
            return _TOKEN_FORMULA_BINOPS[type(node.op)](
                evaluate(node.left, vars), evaluate(node.right, vars)
            )
        if isinstance(node, ast.UnaryOp):
            return _TOKEN_FORMULA_UNARYOPS[type(node.op)](evaluate(node.operand, vars))
        if isinstance(node, ast.Constant):
            assert isinstance(node.value, (int, float))
            return float(node.value)
        assert isinstance(node, ast.Name)
        return vars[node.id]

    def compiled(vars: Mapping[str, float]) -> float:
        try:
            return evaluate(tree, vars)
        except ZeroDivisionError as ex:
            raise ValueError(
                f"token limit: division by zero evaluating formula {formula!r}"
            ) from ex

    return compiled


class _TokenMetering:
    """Derives the metered token count for a token limit `type`.

    `type` is either a keyword ("all" → total tokens, "output" → output tokens)
    or an arithmetic formula over `input`/`output` (see `_compile_token_formula`).
    """

    def __init__(self, type: str) -> None:
        self._type = type
        self._formula: Callable[[Mapping[str, float]], float] | None = (
            None if type in ("all", "output") else _compile_token_formula(type)
        )

    def value(self, usage: ModelUsage) -> int:
        if self._type == "all":
            return usage.total_tokens
        if self._type == "output":
            return usage.output_tokens
        assert self._formula is not None
        # `input` is the true prompt size (including cached tokens, which the
        # `input_tokens` field excludes); `output` includes reasoning tokens.
        input_tokens = (
            usage.input_tokens
            + (usage.input_tokens_cache_read or 0)
            + (usage.input_tokens_cache_write or 0)
        )
        return math.floor(
            self._formula({"input": input_tokens, "output": usage.output_tokens})
        )


class TokenLimit(BaseModel):
    """Specification of a token limit (count plus which tokens are metered)."""

    model_config = ConfigDict(extra="forbid")

    tokens: int = Field(ge=0)
    """Maximum number of tokens."""

    type: str = Field(default="all")
    """Which tokens are metered.

    Either a keyword ("all" counts total tokens, "output" counts only output
    tokens, which include reasoning tokens) or an arithmetic formula over the
    variables `input` and `output`, e.g. "(input * 0.1) + output". In a formula,
    `input` is the true prompt size (including cached tokens) and `output`
    includes reasoning tokens; the result is floored to an integer.
    """

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        # constructs the metering (compiling any formula) to reject invalid
        # types/formulas at model construction rather than mid-run
        _TokenMetering(value)
        return value


_TOKEN_COUNT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmb]?)\s*$", re.IGNORECASE)
_TOKEN_LIMIT_UNITS = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def parse_token_limit(value: str) -> int | TokenLimit:
    """Parse a token limit string.

    The format is `[<type>:]<number>[k|m|b]` (case-insensitive), e.g.
    `500000`, `500k`, `1m`, or `output:1m`. Suffixes are decimal
    (`k` = 1,000, `m` = 1,000,000, `b` = 1,000,000,000) and decimal numbers
    are allowed as long as the result is a whole number of tokens.

    `<type>` is either a keyword (`all` or `output`) or an arithmetic formula
    over `input`/`output` (see `TokenLimit`), e.g. `(input*0.1)+output:1m`.

    Args:
      value: String to parse.

    Returns:
      A plain `int` for limits which meter all tokens, otherwise a `TokenLimit`.
    """
    # a formula never contains a colon, so the type/formula (if any) is
    # everything before the final colon and the count is everything after
    if ":" in value:
        type_prefix, count = value.rsplit(":", 1)
        type_prefix = type_prefix.strip()
    else:
        type_prefix, count = "all", value

    m = _TOKEN_COUNT_RE.match(count)
    if m is None:
        raise ValueError(
            f"token limit: expected [<type>:]<number>[k|m|b], got {value!r}"
        )
    number, unit = m.groups()
    tokens = float(number) * (_TOKEN_LIMIT_UNITS[unit.lower()] if unit else 1)
    if not tokens.is_integer():
        raise ValueError(
            f"token limit: must resolve to a whole number of tokens, got {value!r}"
        )

    if type_prefix.lower() == "all":
        return int(tokens)
    # "output" keyword (case-insensitive) or a formula; _TokenMetering validates
    type = "output" if type_prefix.lower() == "output" else type_prefix
    return TokenLimit(tokens=int(tokens), type=type)


def resolve_token_limit(
    value: int | str | TokenLimit | None,
) -> int | TokenLimit | None:
    """Normalize a token limit value to its canonical form.

    Strings are parsed with `parse_token_limit()`; a `TokenLimit` which meters
    all tokens is collapsed to a plain `int` (so that e.g. serialized configs
    only carry the richer form when output-metering is actually used).

    Args:
      value: Token limit value to normalize.
    """
    if isinstance(value, str):
        value = parse_token_limit(value)
    if isinstance(value, TokenLimit) and value.type == "all":
        return value.tokens
    return value


class TokenLimitFields(NamedTuple):
    """Decomposed form of a token limit (numeric limit plus metering type).

    Used for config storage where the numeric limit must remain a plain `int`
    for backwards compatibility (e.g. `EvalConfig`).
    """

    tokens: int | None
    type: str | None
    """Metering type (None indicates "all")."""


def token_limit_fields(value: int | str | TokenLimit | None) -> TokenLimitFields:
    """Decompose a token limit into a numeric limit and metering type.

    The type field is None (rather than "all") when all tokens are metered, so
    that serialized configs only carry a type when output-metering is used.

    Args:
      value: Token limit value to decompose.
    """
    resolved = resolve_token_limit(value)
    if isinstance(resolved, TokenLimit):
        return TokenLimitFields(tokens=resolved.tokens, type=resolved.type)
    return TokenLimitFields(tokens=resolved, type=None)


def token_limit(
    limit: int | TokenLimit | None,
    type: str = "all",
) -> _TokenLimit:
    """Limits the total number of tokens which can be used.

    The counter starts when the context manager is opened and ends when it is closed.

    These limits can be stacked.

    This relies on "cooperative" checking - consumers must call `check_token_limit()`
    themselves whenever tokens are consumed.

    When a limit is exceeded, a `LimitExceededError` is raised.

    Args:
      limit: The maximum number of tokens that can be used while the context manager is
        open. Tokens used before the context manager was opened are not counted. A value
        of None means unlimited tokens. Can also be a `TokenLimit` which specifies both
        the count and the metering type (in which case `type` may not also be passed).
      type: Which tokens are metered. Either a keyword ("all" — total tokens, the
        default; "output" — output tokens only, which include reasoning tokens) or an
        arithmetic formula over the variables `input` and `output`, e.g.
        "(input * 0.1) + output". In a formula, `input` is the true prompt size
        (including cached tokens) and `output` includes reasoning tokens; the result is
        floored to an integer.
    """
    if isinstance(limit, TokenLimit):
        if type != "all":
            raise ValueError(
                "Pass 'type' via either TokenLimit or the 'type' parameter, not both."
            )
        return _TokenLimit(limit.tokens, type=limit.type)
    return _TokenLimit(limit, type=type)


def record_model_usage(usage: ModelUsage) -> None:
    """Record model usage against any active token limits.

    Does not check if the limit has been exceeded.

    No-op when token limits are suspended (see `suspend_token_limit()`).
    """
    if token_limit_tree.is_suspended():
        return
    node = token_limit_tree.get()
    if node is None:
        return
    node.record(usage)


def check_token_limit() -> None:
    """Check if the current token usage exceeds _any_ of the token limits.

    Within the current execution context (e.g. async task) and its parent contexts only.

    Note that all active token limits are checked, not just the most recent one.

    No-op when token limits are suspended (see `suspend_token_limit()`).
    """
    if token_limit_tree.is_suspended():
        return
    node = token_limit_tree.get()
    if node is None:
        return
    node.check()


def suspend_token_limit() -> AbstractContextManager[None]:
    """Suspend token limit metering within a block of code.

    While this context manager is open:

    - Token usage is not recorded against any active `token_limit()` scope
      (including sample-level, agent-scoped, and arbitrary block limits).
    - Calls to `check_token_limit()` are no-ops.
    - This applies to any `token_limit()` contexts opened inside the block
      as well — suspension wins over nested limits.

    Useful for running code whose token usage should not count against an
    agent's budget, e.g. one-shot summarization, routing, or auxiliary
    planning calls.

    Example:
        with token_limit(10_000):
            # tokens count against the 10k budget
            await generate()
            with suspend_token_limit():
                # tokens here do not count
                await expensive_summary()
            # tokens count again
            await generate()
    """
    return token_limit_tree.suspended()


def cost_limit(limit: float | None) -> _CostLimit:
    """Limits the total cost (in dollars) which can be used.

    The counter starts when the context manager is opened and ends when it is closed.

    These limits can be stacked.

    This relies on "cooperative" checking - consumers must call `check_cost_limit()`
    themselves whenever cost is recorded.

    When a limit is exceeded, a `LimitExceededError` is raised.

    Args:
      limit: The maximum cost (in dollars) that can be used while the context manager is
        open. A value of None means unlimited cost.
    """
    return _CostLimit(limit)


def record_model_cost(cost: float) -> None:
    """Record model cost against any active cost limits.

    Does not check if the limit has been exceeded.
    """
    node = cost_limit_tree.get()
    if node is None:
        return
    node.record(cost)


def check_cost_limit() -> None:
    """Check if the current cost exceeds _any_ of the cost limits.

    Within the current execution context (e.g. async task) and its parent contexts only.

    Note that all active cost limits are checked, not just the most recent one.
    """
    node = cost_limit_tree.get()
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


def turn_limit(limit: int | None) -> _TurnLimit:
    """Limits the number of turns (model generations) which can be used.

    A "turn" is a single top-level model generation (one call to the model
    that produces an assistant message). This mirrors the upstream notion of
    an agent "turn budget" — distinct from `message_limit()`, which counts all
    messages in the conversation (user, assistant, tool, etc.).

    The counter starts when the context manager is opened and ends when it is
    closed.

    These limits can be stacked.

    This relies on "cooperative" checking - the model generation path calls
    `record_turn()` once per completed generation, which also checks the limit.

    When a limit is exceeded, a `LimitExceededError` is raised.

    Args:
      limit: The maximum number of turns that can be used while the context
        manager is open. Turns used before the context manager was opened are
        not counted. A value of None means unlimited turns.
    """
    return _TurnLimit(limit)


def record_turn() -> None:
    """Record a turn (model generation) against any active turn limits.

    Records the turn for the most recent turn limit and its ancestors, then
    checks whether any of them have been exceeded (raising
    `LimitExceededError` if so).

    No-op when turn limits are suspended (see `suspend_turn_limit()`).
    """
    if turn_limit_tree.is_suspended():
        return
    node = turn_limit_tree.get()
    if node is None:
        return
    node.record()
    node.check()


def check_turn_limit() -> None:
    """Check if the current turn count exceeds _any_ of the turn limits.

    Within the current execution context (e.g. async task) and its parent
    contexts only.

    Note that all active turn limits are checked, not just the most recent one.

    No-op when turn limits are suspended (see `suspend_turn_limit()`).
    """
    if turn_limit_tree.is_suspended():
        return
    node = turn_limit_tree.get()
    if node is None:
        return
    node.check()


def suspend_turn_limit() -> AbstractContextManager[None]:
    """Suspend turn limit metering within a block of code.

    While this context manager is open:

    - Turns are not recorded against any active `turn_limit()` scope
      (including sample-level, agent-scoped, and arbitrary block limits).
    - Calls to `check_turn_limit()` are no-ops.
    - This applies to any `turn_limit()` contexts opened inside the block
      as well — suspension wins over nested limits.

    Useful for running model generations whose turns should not count against
    an agent's budget, e.g. one-shot summarization, routing, or auxiliary
    planning calls.

    Example:
        with turn_limit(10):
            # generations count against the 10 turn budget
            await generate()
            with suspend_turn_limit():
                # generations here do not count
                await auxiliary_generate()
            # generations count again
            await generate()
    """
    return turn_limit_tree.suspended()


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
    from inspect_ai.event._sample_limit import SampleLimitEvent
    from inspect_ai.log._transcript import transcript

    error = working_limit_exceeded()
    if error is not None:
        transcript()._event(
            SampleLimitEvent(type="working", message=error.message, limit=error.limit)
        )

        raise error


def monitor_working_limit(interval: float = 1) -> None:
    from inspect_ai.log._samples import has_active_model_event, sample_active

    # get the active sample
    sample = sample_active()
    if sample is None:
        raise RuntimeError(
            "monitor_working_limit() must be called from a running sample."
        )
    if sample.tg is None:
        raise RuntimeError(
            "monitor_working_limit() must be called after sample has been started."
        )

    # check every second
    async def run() -> None:
        while True:
            await anyio.sleep(interval)

            # don't continue after the sample is completed
            if sample.completed:
                return

            # don't check if there is an active model event
            # (need to wait until it completes for the working time
            # computation to be done)
            if has_active_model_event():
                continue

            error = working_limit_exceeded()
            if error is not None:
                sample.limit_exceeded(error)
                return

    # kick it off
    sample.tg.start_soon(run)


def working_limit_exceeded() -> LimitExceededError | None:
    node = working_limit_tree.get()
    if node is None:
        return None
    return node.check()


class _Tree(Generic[TNode]):
    """A tree data structure of limit nodes.

    Each node has a pointer to its parent, or None if it is a root node.

    Each additional context manager inserts a new child node into the tree. The fact
    that there can be multiple execution contexts is what makes this a tree rather than
    a stack and why a context variable is used to store the leaf node.
    """

    def __init__(self, id: str) -> None:
        self._leaf_node: ContextVar[TNode | None] = ContextVar(id, default=None)
        self._suspended: ContextVar[int] = ContextVar(f"{id}_suspended", default=0)

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

    def is_suspended(self) -> bool:
        return self._suspended.get() > 0

    @contextmanager
    def suspended(self) -> Iterator[None]:
        token = self._suspended.set(self._suspended.get() + 1)
        try:
            yield
        finally:
            self._suspended.reset(token)


token_limit_tree: _Tree[_TokenLimit] = _Tree("token_limit_tree")
cost_limit_tree: _Tree[_CostLimit] = _Tree("cost_limit_tree")
message_limit_tree: _Tree[_MessageLimit] = _Tree("message_limit_tree")
turn_limit_tree: _Tree[_TurnLimit] = _Tree("turn_limit_tree")
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
    def __init__(self, limit: int | None, type: str = "all") -> None:
        from inspect_ai.model._model_output import ModelUsage

        super().__init__()
        self._validate_token_limit(limit)
        # constructs (and validates) the metering; raises ValueError on an
        # invalid type keyword or formula
        self._metering = _TokenMetering(type)
        self._limit = limit
        self._type = type
        self._usage = ModelUsage()

    def __enter__(self) -> _TokenLimit:
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
        return self._metering.value(self._usage)

    @property
    def type(self) -> str:
        """Which tokens are metered by this limit."""
        return self._type

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
        from inspect_ai.event._sample_limit import SampleLimitEvent
        from inspect_ai.log._transcript import transcript

        if self.limit is None:
            return
        total = self._metering.value(self._usage)
        if total > self.limit:
            if self._type == "all":
                message = (
                    f"Token limit exceeded. value: {total:,}; limit: {self.limit:,}"
                )
            elif self._type == "output":
                message = f"Output token limit exceeded. value: {total:,}; limit: {self.limit:,}"
            else:
                message = f"Token limit exceeded ({self._type}). value: {total:,}; limit: {self.limit:,}"
            transcript()._event(
                SampleLimitEvent(type="token", limit=self.limit, message=message)
            )
            raise LimitExceededError(
                "token", value=total, limit=self.limit, message=message, source=self
            )


class _TurnLimit(Limit, _Node):
    def __init__(self, limit: int | None) -> None:
        super().__init__()
        self._validate_turn_limit(limit)
        self._limit = limit
        self._turns = 0

    def __enter__(self) -> Limit:
        super()._check_reuse()
        turn_limit_tree.push(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._pop_and_check_identity(turn_limit_tree)

    @property
    def usage(self) -> float:
        return self._turns

    @property
    def limit(self) -> int | None:
        """Get the configured turn limit value."""
        return self._limit

    @limit.setter
    def limit(self, value: int | None) -> None:
        """Update the turn limit value.

        This does not trigger a check of the turn limit (which could now have
        been exceeded).
        """
        self._validate_turn_limit(value)
        self._limit = value

    def record(self) -> None:
        """Record a turn for this node and its ancestor nodes."""
        if self.parent is not None:
            self.parent.record()
        self._turns += 1

    def check(self) -> None:
        """Check if this turn limit or any ancestor limits have been exceeded.

        The checks occur from root to leaf. This is so that if multiple limits are
        simultaneously exceeded, the outermost (closest to root) one raises the error,
        preventing certain sub-agent architectures from ending up in an infinite loop.
        """
        if self.parent is not None:
            self.parent.check()
        self._check_self()

    def _validate_turn_limit(self, value: int | None) -> None:
        if value is not None and value < 0:
            raise ValueError(
                f"Turn limit value must be a non-negative integer or None: {value}"
            )

    def _check_self(self) -> None:
        from inspect_ai.event._sample_limit import SampleLimitEvent
        from inspect_ai.log._transcript import transcript

        if self.limit is None:
            return
        if self._turns > self.limit:
            message = (
                f"Turn limit exceeded. value: {self._turns:,}; limit: {self.limit:,}"
            )
            transcript()._event(
                SampleLimitEvent(type="turn", limit=self.limit, message=message)
            )
            raise LimitExceededError(
                "turn",
                value=self._turns,
                limit=self.limit,
                message=message,
                source=self,
            )


class _CostLimit(Limit, _Node):
    def __init__(self, limit: float | None) -> None:
        super().__init__()
        self._validate_cost_limit(limit)
        self._limit = limit
        self._cost: float = 0.0

    def __enter__(self) -> Limit:
        super()._check_reuse()
        cost_limit_tree.push(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._pop_and_check_identity(cost_limit_tree)

    @property
    def usage(self) -> float:
        return self._cost

    @property
    def limit(self) -> float | None:
        """Get the configured cost limit value."""
        return self._limit

    @limit.setter
    def limit(self, value: float | None) -> None:
        """Update the cost limit value.

        This does not trigger a check of the cost limit (which could now have been
        exceeded).
        """
        self._validate_cost_limit(value)
        self._limit = value

    def record(self, cost: float) -> None:
        """Record cost for this node and its ancestor nodes."""
        if self.parent is not None:
            self.parent.record(cost)
        self._cost += cost

    def check(self) -> None:
        """Check if this cost limit or any ancestor limits have been exceeded.

        The checks occur from root to leaf. This is so that if multiple limits are
        simultaneously exceeded, the outermost (closest to root) one raises the error,
        preventing certain sub-agent architectures from ending up in an infinite loop.
        """
        if self.parent is not None:
            self.parent.check()
        self._check_self()

    def _validate_cost_limit(self, value: float | None) -> None:
        if value is not None and value < 0:
            raise ValueError(
                f"Cost limit value must be a non-negative float or None: {value}"
            )

    def _check_self(self) -> None:
        from inspect_ai.event._sample_limit import SampleLimitEvent
        from inspect_ai.log._transcript import transcript

        if self.limit is None:
            return
        if self._cost > self.limit:
            message = f"Cost limit exceeded. value: ${self._cost:,.4f}; limit: ${self.limit:,.4f}"
            transcript()._event(
                SampleLimitEvent(type="cost", limit=self.limit, message=message)
            )
            raise LimitExceededError(
                "cost",
                value=self._cost,
                limit=self.limit,
                message=message,
                source=self,
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
        from inspect_ai.event._sample_limit import SampleLimitEvent
        from inspect_ai.log._transcript import transcript

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
        from inspect_ai.event._sample_limit import SampleLimitEvent
        from inspect_ai.log._transcript import transcript

        self._cancel_scope.__exit__(exc_type, exc_val, exc_tb)
        self._end_time = anyio.current_time()
        self._pop_and_check_identity(time_limit_tree)
        # use cancelled_caught (not cancel_called): if the deadline fired but
        # the body raised a non-Cancelled exception (e.g. cleanup in `finally`
        # crashed), the cancel scope did not catch a Cancelled and we must let
        # the original exception propagate rather than masking it.
        if self._cancel_scope.cancelled_caught and self._limit is not None:
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

    def check(self) -> LimitExceededError | None:
        """Check if this working time limit or any ancestor limits have been exceeded.

        The checks occur from root to leaf. This is so that if multiple limits are
        simultaneously exceeded, the outermost (closest to root) one raises the error,
        preventing certain sub-agent architectures from ending up in an infinite loop.
        """
        if self.parent is not None:
            error = self.parent.check()
            if error is not None:
                return error
        return self._check_self()

    def _check_self(self) -> LimitExceededError | None:
        if self._limit is None:
            return None
        if self.usage > self._limit:
            message = f"Working time limit exceeded. limit: {self._limit} seconds"
            return LimitExceededError(
                "working",
                value=self.usage,
                limit=self._limit,
                message=message,
                source=self,
            )
        else:
            return None


def _validate_time_limit(name: str, value: float | None) -> None:
    if value is not None and value < 0:
        raise ValueError(
            f"{name} limit value must be a non-negative float or None: {value}"
        )


class _LimitData(Limit):
    """Limit which copies its values from another limit."""

    def __init__(self, limit: Limit, *, usage: float | None = None) -> None:
        self._limit = limit.limit
        self._usage = usage if usage is not None else limit.usage

    @override
    def __enter__(self) -> Limit:
        return self

    @override
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    @property
    @override
    def limit(self) -> float | None:
        return self._limit

    @property
    @override
    def usage(self) -> float:
        return self._usage
