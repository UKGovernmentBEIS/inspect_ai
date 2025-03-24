from __future__ import annotations

import asyncio
import functools
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import ContextManager, Generator

from inspect_ai._util._async import tg_collect
from inspect_ai.model._model import (
    init_model_usage,
    init_sample_model_usage,
    sample_model_usage,
)
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.solver._limit import SampleLimitExceededError

# Tracks current async context's token limit.
token_limit_ctx_var: ContextVar[TokenLimit] = ContextVar("limit_ctx_var")


@dataclass
class TokenLimit:
    # Snapshot of the token usage at the time the context manager was opened.
    initial_usage: ModelUsage
    # The maximum number of tokens that can be used while the context manager is open.
    budget: int

    def has_been_exceeded(self, usage: ModelUsage) -> bool:
        return self.usage_since_start(usage) > self.budget

    def usage_since_start(self, usage: ModelUsage) -> int:
        return usage.total_tokens - self.initial_usage.total_tokens


@contextmanager
def token_limit(budget: int) -> Generator[None, None, None]:
    """Limits the total number of tokens (input + output) which can be used."""
    try:
        current_usage = sample_model_usage()["model"]
        limit = TokenLimit(current_usage, budget)
        token = token_limit_ctx_var.set(limit)
        yield
    finally:
        token_limit_ctx_var.reset(token)


def consume_tokens(count: int) -> None:
    usage = sample_model_usage()["model"]
    usage.total_tokens += count

    # Check if the token limit has been exceeded.
    limit = token_limit_ctx_var.get(None)
    if limit is not None:
        if limit.has_been_exceeded(usage):
            raise SampleLimitExceededError(
                "token", value=limit.usage_since_start(usage), limit=limit.budget
            )


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
    print(f"Starting task {sample_id}")
    init_sample_model_usage()
    sample_model_usage()["model"] = ModelUsage()

    await asyncio.sleep(0.1)

    with sample_token_limiter:
        consume_tokens(1)
        consume_tokens(2)

    print(
        f"Completed task {sample_id}; used {sample_model_usage()['model'].total_tokens} tokens"
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
