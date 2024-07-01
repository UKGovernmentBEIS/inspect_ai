import asyncio

import pytest

from inspect_ai import Task, eval_async
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match


@pytest.mark.asyncio
async def test_no_concurrent_eval_async():
    tasks = [
        Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())
        for i in range(0, 2)
    ]

    results = await asyncio.gather(
        *[eval_async(task, model="mockllm/model") for task in tasks],
        return_exceptions=True,
    )

    assert any([isinstance(result, RuntimeError) for result in results])
