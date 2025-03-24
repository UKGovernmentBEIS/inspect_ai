from __future__ import annotations

import asyncio
import functools
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import ContextManager, Generator

from inspect_ai._util._async import tg_collect
from inspect_ai.model._model import (
    init_model_usage,
    init_sample_model_usage,
    sample_model_usage,
)
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.solver._limit import SampleLimitExceededError

# Stores the current async context's token limit stack.
token_limit_stack_ctx_var: ContextVar[TokenLimitStack | None] = ContextVar(
    "limit_ctx_var", default=None
)


class TokenLimitStack:
    def __init__(self) -> None:
        self.stack: deque[TokenLimit] = deque()

    def push(self, limit: TokenLimit) -> None:
        self.stack.append(limit)

    def pop(self) -> None:
        self.stack.pop()

    def check(self, usage: ModelUsage) -> None:
        print(
            f"Checking token limit stack: {[l.budget for l in self.stack]}; usage: {usage.total_tokens}"
        )
        for limit in self.stack:
            if limit.has_been_exceeded(usage):
                raise SampleLimitExceededError(
                    "token",
                    value=limit.usage_since_start(usage),
                    limit=limit.budget,
                )


class TokenLimit:
    def __init__(self, initial_usage: ModelUsage, budget: int) -> None:
        # Snapshot of the token usage at the time the context manager was opened.
        self.initial_usage = initial_usage.total_tokens
        # The maximum number of tokens that can be used while the context manager is open.
        self.budget = budget

    def has_been_exceeded(self, usage: ModelUsage) -> bool:
        return self.usage_since_start(usage) > self.budget

    def usage_since_start(self, usage: ModelUsage) -> int:
        return usage.total_tokens - self.initial_usage


def get_token_limit_stack() -> TokenLimitStack:
    stack = token_limit_stack_ctx_var.get(None)
    if stack is None:
        stack = TokenLimitStack()
        token_limit_stack_ctx_var.set(stack)
    return stack


@contextmanager
def token_limit(budget: int) -> Generator[None, None, None]:
    """Limits the total number of tokens (input + output) which can be used.

    Can be stacked.
    """
    try:
        current_usage = sample_model_usage()["model"]
        limit = TokenLimit(current_usage, budget)
        stack = get_token_limit_stack()
        stack.push(limit)
        yield
    finally:
        stack.pop()


def consume_tokens(count: int) -> None:
    usage = sample_model_usage()["model"]
    usage.total_tokens += count

    get_token_limit_stack().check(usage)


async def task_run() -> str:
    init_model_usage()

    # Run samples.
    sample_results: list[str] = await tg_collect(
        [functools.partial(task_run_sample, i, token_limit(5)) for i in range(3)]
    )

    return " ".join(sample_results)


async def task_run_sample(
    sample_id: int, sample_token_limiter: ContextManager[None]
) -> str:
    print(f"Starting sample {sample_id}")
    init_sample_model_usage()
    sample_model_usage()["model"] = ModelUsage()

    await asyncio.sleep(0.1)

    with sample_token_limiter:
        consume_tokens(1)
        with token_limit(10):
            consume_tokens(2)

    print(
        f"Completed sample {sample_id}. Used {sample_model_usage()['model'].total_tokens} tokens."
    )
    return f"completed-{sample_id}"


def main() -> None:
    result = asyncio.run(task_run())
    print(result)
    print("Done")


if __name__ == "__main__":
    main()

# Questions:
# Does opening a new context manager e.g. `with token_limit(5)` mean that A) 5 _more_
# tokens can be used, or that B) only 5 tokens can be used in total?
# A) makes more sense with the idea of using a stack.

# Unless we change how token usage is stored, our limit context managers will have to
# snapshot what the token usage was at the time the context manager was opened.

# Is the model_usage_context_var only used for log files, or can it be used to enforce
# limits?
