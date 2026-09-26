from typing import Literal

import pytest
from typing_extensions import Unpack

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfigArgs,
    ModelName,
    ModelOutput,
    get_model,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import init_active_model
from inspect_ai.scorer import match
from inspect_ai.solver import (
    Generate,
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


async def test_self_critique_resolves_model_per_call() -> None:
    # Regression for #4781: a self_critique solver reused across evals must use
    # the model active at call time, not the model resolved on the first call.
    # infinite output generators so an unfixed closure-cache fails on the
    # assertion below (wrong model answered) rather than on output exhaustion
    model_a = get_model(
        "mockllm/model-a",
        custom_outputs=(
            ModelOutput.from_content("mockllm/model-a", "CRITIQUE-A")
            for _ in iter(int, 1)
        ),
    )
    model_b = get_model(
        "mockllm/model-b",
        custom_outputs=(
            ModelOutput.from_content("mockllm/model-b", "CRITIQUE-B")
            for _ in iter(int, 1)
        ),
    )

    async def no_op_generate(
        state: TaskState,
        tool_calls: Literal["loop", "single", "none"] = "loop",
        **kwargs: Unpack[GenerateConfigArgs],
    ) -> TaskState:
        return state

    def make_state() -> TaskState:
        return TaskState(
            model=ModelName("mockllm/model"),
            sample_id=1,
            epoch=1,
            input="What is 2 + 2?",
            messages=[ChatMessageUser(content="What is 2 + 2?")],
            output=ModelOutput.from_content("mockllm/model", "4"),
        )

    solve = self_critique()

    init_active_model(model_a, GenerateConfig())
    state_a = await solve(make_state(), no_op_generate)
    assert "CRITIQUE-A" in state_a.messages[-1].text

    init_active_model(model_b, GenerateConfig())
    state_b = await solve(make_state(), no_op_generate)
    assert "CRITIQUE-B" in state_b.messages[-1].text
