import asyncio
import functools
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

limit_ctx_var: ContextVar[int] = ContextVar("limit_ctx_var")


@contextmanager
def token_limit(maximum: int) -> Generator[None, None, None]:
    try:
        token = limit_ctx_var.set(maximum)
        yield
    finally:
        limit_ctx_var.reset(token)


def consume_tokens(count: int) -> None:
    usage = sample_model_usage()["model"]
    usage.total_tokens += count

    limit = limit_ctx_var.get(None)
    if limit is not None:
        if usage.total_tokens > limit:
            print(f"Exceeded: {usage} > {limit}")
            raise SampleLimitExceededError(
                "token", value=usage.total_tokens, limit=limit
            )


async def task_run() -> str:
    init_model_usage()

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

    with sample_token_limiter:
        consume_tokens(1)
        consume_tokens(2)

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
