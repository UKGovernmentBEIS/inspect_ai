"""Long-running test task for exercising the socket display attach/detach lifecycle.

Uses mockllm with artificial delays — no API keys needed.
Run with: inspect eval src/inspect_ai/_display/socket/test_task.py --model mockllm/model --display=socket --max-samples=1
"""

import asyncio

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, Solver, TaskState, solver


@solver
def slow_solver(delay: float = 3.0, steps: int = 3) -> Solver:
    async def _solve(state: TaskState, generate: Generate) -> TaskState:
        for step in range(steps):
            await asyncio.sleep(delay / steps)
            state = await generate(state)
        return state

    return _solve


NUM_SAMPLES = 15
DELAY_PER_SAMPLE = 3.0
STEPS_PER_SAMPLE = 3


def _make_samples(n: int = NUM_SAMPLES) -> list[Sample]:
    samples = []
    for i in range(n):
        target = "Default output from mockllm/model" if i % 3 == 0 else f"answer_{i}"
        samples.append(
            Sample(
                id=f"sample_{i:03d}",
                input=f"Question {i + 1}: What is the answer?",
                target=target,
            )
        )
    return samples


@task
def slow_counting(
    num_samples: int = NUM_SAMPLES,
    delay: float = DELAY_PER_SAMPLE,
    steps: int = STEPS_PER_SAMPLE,
) -> Task:
    return Task(
        dataset=_make_samples(num_samples),
        solver=[slow_solver(delay=delay, steps=steps)],
        scorer=match(),
    )


@task
def interactive_counting(
    num_samples: int = 8,
    delay: float = DELAY_PER_SAMPLE,
    steps: int = STEPS_PER_SAMPLE,
) -> Task:
    from inspect_ai._event_bus.ask_human import ask_human

    return Task(
        dataset=_make_samples(num_samples),
        solver=[
            slow_solver(delay=delay, steps=steps),
            ask_human("The agent has processed some samples. Should it continue with the same approach, or try something different?"),
            slow_solver(delay=delay, steps=steps),
        ],
        scorer=match(),
    )
