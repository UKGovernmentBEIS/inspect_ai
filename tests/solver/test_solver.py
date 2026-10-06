import asyncio
from typing import Any

import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelName,
    ModelOutput,
    get_model,
)
from inspect_ai.model._model import init_active_model
from inspect_ai.scorer import match
from inspect_ai.solver import (
    Generate,
    Solver,
    TaskState,
    chain_of_thought,
    generate,
    self_critique,
    solver,
)
from inspect_ai.solver._plan import Plan


def test_solvers_termination():
    @solver
    def user_input(input: str):
        async def solve(state: TaskState, generate: Generate):
            state.messages.append(ChatMessageUser(content=input))
            return state

        return solve

    @solver
    def complete_task():
        async def solve(state: TaskState, generate: Generate):
            state.completed = True
            return state

        return solve

    @solver
    def finish():
        async def solve(state: TaskState, generate: Generate):
            state.output = ModelOutput.from_content(
                model="mockllm/model", content="finished"
            )
            return state

        return solve

    model = get_model("mockllm/model")
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=Plan(
            [
                chain_of_thought(),
                generate(),
                user_input("How about multiplying the numbers?"),
                generate(),
                complete_task(),
                user_input("How about subtracting the numbers?"),
                generate(),
            ],
            finish=finish(),
            internal=True,
        ),
        scorer=match(),
    )

    log = eval(task, model=model)[0]
    assert len(log.samples[0].messages) == 4
    assert log.samples[0].output.completion == "finished"

    log = eval(task, model=model, message_limit=2)[0]
    assert len(log.samples[0].messages) == 2


def test_invalid_solvers_error():
    def not_async():
        def inner(state: TaskState, generate: Generate) -> TaskState:
            return state

        return inner

    class NotCallable:
        async def inner(self, state: TaskState, generate: Generate) -> TaskState:
            return state

    class NotAsyncCallable:
        def __call__(self, state: TaskState, target: Generate) -> TaskState:
            return state

    for f in [not_async, NotCallable, NotAsyncCallable]:
        with pytest.raises(TypeError):
            solver(name=f.__name__)(f)()


def test_valid_solvers_succeed():
    def is_async():
        async def inner(self, state: TaskState, generate: Generate) -> TaskState:
            return state

        return inner

    class IsAsyncCallable:
        async def __call__(self, state: TaskState, generate: Generate) -> TaskState:
            return state

    for f in [is_async, IsAsyncCallable]:
        solver(name=f.__name__)(f)()


def _repeating_model(text: str) -> Model:
    # answers every call, so a model wrongly reused for a later call shows up
    # as the wrong critique rather than as exhausted mock outputs
    return get_model(
        "mockllm/model",
        custom_outputs=lambda *_: ModelOutput.from_content("mockllm/model", text),
    )


async def _critique_under_active_models(
    critique: Solver, active_models: list[Model]
) -> list[str]:
    """Run the same solver instance once under each active model.

    Returns the critique message that the solver adds for each call.
    """

    async def passthrough(state: TaskState, *args: Any, **kwargs: Any) -> TaskState:
        return state

    async def run(active: Model) -> str:
        init_active_model(active, GenerateConfig())
        state = TaskState(
            model=ModelName("mockllm/model"),
            sample_id=1,
            epoch=1,
            input="What is 1 + 1?",
            messages=[],
            output=ModelOutput.from_content("mockllm/model", "3"),
        )
        state = await critique(state, passthrough)
        return state.messages[-1].text

    return [await run(active) for active in active_models]


def test_self_critique_instance_critiques_with_each_active_model() -> None:
    critique = self_critique()

    messages = asyncio.run(
        _critique_under_active_models(
            critique,
            [
                _repeating_model("critique from first active model"),
                _repeating_model("critique from second active model"),
            ],
        )
    )

    assert "critique from first active model" in messages[0]
    assert "critique from second active model" in messages[1]


def test_self_critique_instance_prefers_explicit_model() -> None:
    critique = self_critique(model=_repeating_model("critique from explicit model"))

    messages = asyncio.run(
        _critique_under_active_models(
            critique,
            [
                _repeating_model("critique from first active model"),
                _repeating_model("critique from second active model"),
            ],
        )
    )

    assert all("critique from explicit model" in message for message in messages)
