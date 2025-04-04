# Temporary tests to understand how subtasks, forks and agents affect token counting.
import asyncio
from typing import Generator

import pytest

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.agent import run
from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.solver._fork import fork
from inspect_ai.solver._solver import Generate, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._counter import get_model_usage
from inspect_ai.util._subtask import subtask

# TODO: Also assert get_scoped_model_usage().


@pytest.fixture
def model() -> Model:
    def repeat_forever(output: ModelOutput) -> Generator[ModelOutput, None, None]:
        while True:
            yield output

    return get_model(
        "mockllm/model",
        custom_outputs=repeat_forever(ModelOutput(usage=ModelUsage(total_tokens=1))),
    )


def test_parallel_subtasks(model: Model) -> None:
    @solver
    def subtask_solver():
        async def solve(state: TaskState, generate: Generate):
            assert _leaf_total_tokens() == 0

            await model.generate("")
            assert _leaf_total_tokens() == 1

            subtasks = [my_subtask() for _ in range(3)]
            await asyncio.gather(*subtasks)
            assert _leaf_total_tokens() == 4

            await model.generate("")
            assert _leaf_total_tokens() == 5

            return state

        return solve

    @subtask
    async def my_subtask() -> str:
        """Consumes 1 token."""
        assert _leaf_total_tokens() == 0

        await model.generate("")
        assert _leaf_total_tokens() == 1

        return ""

    result = eval(Task(solver=subtask_solver()))[0]

    assert result.status == "success"
    assert result.stats.model_usage["mockllm/model"].total_tokens == 5


def test_nested_subtasks(model: Model) -> None:
    @solver
    def nested_subtask_solver():
        async def solve(state: TaskState, generate: Generate):
            assert _leaf_total_tokens() == 0

            await model.generate("")
            assert _leaf_total_tokens() == 1

            subtasks = [outer_subtask() for _ in range(3)]
            await asyncio.gather(*subtasks)
            assert _leaf_total_tokens() == 16

            await model.generate("")
            assert _leaf_total_tokens() == 17

            return state

        return solve

    @subtask
    async def outer_subtask() -> str:
        """Consumes 2 tokens itself, and 1 for each of the 3 inner subtasks."""
        assert _leaf_total_tokens() == 0

        await model.generate("")
        assert _leaf_total_tokens() == 1

        inner_subtasks = [inner_subtask() for _ in range(3)]
        await asyncio.gather(*inner_subtasks)

        await model.generate("")
        assert _leaf_total_tokens() == 5

        return ""

    @subtask
    async def inner_subtask() -> str:
        """Consumes 1 token."""
        assert _leaf_total_tokens() == 0

        await model.generate("")
        assert _leaf_total_tokens() == 1

        return ""

    eval(Task(solver=nested_subtask_solver()))


def test_parallel_forks(model: Model):
    @solver
    def forking_solver():
        async def solve(state: TaskState, generate: Generate):
            assert _leaf_total_tokens() == 0

            await model.generate("")
            assert _leaf_total_tokens() == 1

            await fork(state, [forked_solver() for _ in range(3)])
            assert _leaf_total_tokens() == 4

            await model.generate("")
            assert _leaf_total_tokens() == 5

            return state

        return solve

    @solver
    def forked_solver():
        async def solve(state: TaskState, generate: Generate):
            """Consumes 1 token."""
            assert _leaf_total_tokens() == 0

            await model.generate("")
            assert _leaf_total_tokens() == 1

            return state

        return solve

    result = eval(Task(solver=forking_solver()))[0]

    assert result.status == "success"
    assert result.stats.model_usage["mockllm/model"].total_tokens == 5


def test_parallel_agents(model: Model) -> None:
    @solver
    def agent_solver():
        async def solve(state: TaskState, generate: Generate):
            assert _leaf_total_tokens() == 0

            await model.generate("")
            assert _leaf_total_tokens() == 1

            await asyncio.gather(*[run(my_agent(), "") for _ in range(3)])
            assert _leaf_total_tokens() == 4

            await model.generate("")
            assert _leaf_total_tokens() == 5

            return state

        return solve

    @agent
    def my_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            assert _leaf_total_tokens() == 0

            await model.generate("")
            assert _leaf_total_tokens() == 1

            return state

        return execute

    result = eval(Task(solver=agent_solver()))[0]

    assert result.status == "success"
    assert result.stats.model_usage["mockllm/model"].total_tokens == 5


def _leaf_total_tokens() -> int:
    usage = get_model_usage()
    return sum(x.total_tokens for x in usage.values())
