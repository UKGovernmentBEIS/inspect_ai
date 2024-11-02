import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser, ModelOutput, get_model
from inspect_ai.scorer import match
from inspect_ai.solver import (
    Generate,
    TaskState,
    chain_of_thought,
    generate,
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
    assert log.samples[0].output.completion == "finished"


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
