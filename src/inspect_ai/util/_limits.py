# Contains lots of experimentation code to be removed.
# For now, very specific to token limits, but could be generalized to other limits.

# Questions:

# Is the model_usage_context_var only used for log files, or can it be used to enforce
# limits?


from __future__ import annotations

import asyncio
import functools
from collections import deque
from contextvars import ContextVar

from inspect_ai._util._async import tg_collect
from inspect_ai.model._model import (
    init_model_usage,
    init_sample_model_usage,
    sample_model_usage,
    sample_total_tokens,
)
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.solver._limit import SampleLimitExceededError

# Stores the current async context's token limit stack.
token_limit_stack_ctx_var: ContextVar[_TokenLimitStack] = ContextVar("limit_ctx_var")


def main() -> None:
    result = asyncio.run(task_run())
    print(f"Completed task with results: {result}")


class TokenLimit:
    """Limits the total number of tokens (input + output) which can be used.

    The counter starts when the context manager is opened and ends when it is closed.
    The context manager can be opened multiple times, even in different async contexts.

    These limits can be stacked.

    When a limit is exceeded, a SampleLimitExceededError is raised.

    Args:
      budget: The maximum number of tokens that can be used while the context manager is
        open. Tokens used before the context manager was opened are not counted.
    """

    def __init__(self, budget: int) -> None:
        if budget < 0:
            raise ValueError("Token limit budget must be a non-negative integer.")
        self.budget = budget

    def __enter__(self) -> None:
        current_usage = sample_total_tokens()
        limit = _TokenLimitItem(current_usage, self.budget)
        # Note that we don't store stack as in instance variable, because the context
        # manager may be used across multiple async tasks.
        stack = _TokenLimitStack.get_or_create()
        stack.push(limit)

    def __exit__(self, exc_type: type, exc_val: Exception, exc_tb: type) -> None:
        stack = _TokenLimitStack.get_or_create()
        stack.pop()


class NullTokenLimitCtx(TokenLimit):
    """A TokenLimitCtx that implements the null object pattern."""

    def __init__(self) -> None:
        pass

    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type: type, exc_val: Exception, exc_tb: type) -> None:
        pass


# TODO: Would we rather the user has to pass in a ModelUsage (or int) or should we
# always just get the total token usage from the relevant context var?
def check_token_limit() -> None:
    """Check if the current token usage exceeds any of the token limits."""
    usage = sample_total_tokens()
    _TokenLimitStack.get_or_create().check(usage)


class _TokenLimitStack:
    """A stack of token limit items."""

    def __init__(self) -> None:
        self.stack: deque[_TokenLimitItem] = deque()

    def push(self, limit: _TokenLimitItem) -> None:
        self.stack.append(limit)

    def pop(self) -> None:
        self.stack.pop()

    def check(self, usage: int) -> None:
        """Check if the current token usage exceeds any of the token limits."""
        for limit in self.stack:
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
    def __init__(self, initial_usage: int, budget: int) -> None:
        """
        Initialize a token limit item.

        Args:
          initial_usage: Snapshot of the token usage at the time the context manager was
            opened.
          budget: The maximum number of tokens that can be used while the context
            manager is open.
        """
        self.initial_usage = initial_usage
        self.budget = budget

    def check(self, usage: int) -> None:
        if usage - self.initial_usage > self.budget:
            raise SampleLimitExceededError("token", value=usage, limit=self.budget)


# Mocks of Inspect functions to facilitate development and experimentation.


async def task_run() -> str:
    init_model_usage()

    # Note that despite the fact this is initialized at the task scope, there will be
    # a budget per sample.
    limit = TokenLimit(5)
    # Run samples.
    sample_results: list[str] = await tg_collect(
        [functools.partial(task_run_sample, i, limit) for i in range(3)]
    )

    return " ".join(sample_results)


async def task_run_sample(
    sample_id: int, token_limit: TokenLimit = NullTokenLimitCtx()
) -> str:
    print(f"Starting sample {sample_id}")
    init_sample_model_usage()
    sample_model_usage()["model"] = ModelUsage()

    await asyncio.sleep(0.1)

    # Demonstrates that the user can pass us a ctx manager.
    with token_limit:
        consume_tokens(1)
        # Or, a context manager can be created in the sample (e.g. in a solver).
        with TokenLimit(10):
            consume_tokens(2)

    print(
        f"Completed sample {sample_id}. Used {sample_model_usage()['model'].total_tokens} tokens."
    )
    return f"completed-{sample_id}"


def consume_tokens(count: int) -> None:
    usage = sample_model_usage()["model"]
    usage.total_tokens += count

    _TokenLimitStack.get_or_create().check(usage)


if __name__ == "__main__":
    main()
