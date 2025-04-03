# Temporary tests to understand how subtasks, forks and agents affect token counting.
import asyncio

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.agent import run
from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.model._model import (
    Model,
    get_model,
    sample_total_tokens,
)
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.solver._fork import fork
from inspect_ai.solver._solver import Generate, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._subtask import subtask


def test_parallel_subtasks() -> None:
    @solver
    def my_solver(model: Model):
        async def solve(state: TaskState, generate: Generate):
            await model.generate("input")  # use 20 tokens
            subtasks = [my_subtask(model) for _ in range(3)]
            await asyncio.gather(*subtasks)
            return state

        return solve

    @subtask
    async def my_subtask(model: Model) -> str:
        # init_sample_model_usage()

        print(f"Before generating, usage: {sample_total_tokens()}")
        await model.generate("input")
        print(f"After generating, usage: {sample_total_tokens()}")
        return ""

    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput(usage=ModelUsage(total_tokens=20))] * 10,
    )

    eval(Task(solver=my_solver(model)))

    print(f"After running agents, usage: {sample_total_tokens()}")


def test_parallel_forks():
    @solver
    def my_solver(model: Model):
        async def solve(state: TaskState, generate: Generate):
            await model.generate("input")  # use 20 tokens
            await fork(state, [my_fork_solver(model) for _ in range(3)])
            return state

        return solve

    @solver
    def my_fork_solver(model: Model):
        async def solve(state: TaskState, generate: Generate):
            print(f"Before generating, usage: {sample_total_tokens()}")
            await model.generate("input")
            print(f"After generating, usage: {sample_total_tokens()}")
            return state

        return solve

    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput(usage=ModelUsage(total_tokens=20))] * 10,
    )

    eval(Task(solver=my_solver(model)))


def test_parallel_agents() -> None:
    @solver
    def my_solver(model: Model):
        async def solve(state: TaskState, generate: Generate):
            await model.generate("input")  # use 20 tokens
            await asyncio.gather(*[run(my_agent(model), "input") for _ in range(3)])
            return state

        return solve

    @agent
    def my_agent(model: Model) -> Agent:
        async def execute(state: AgentState) -> AgentState:
            # init_sample_model_usage()

            print(f"Before generating, usage: {sample_total_tokens()}")
            await model.generate("input")
            print(f"After generating, usage: {sample_total_tokens()}")

            return state

        return execute

    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput(usage=ModelUsage(total_tokens=20))] * 10,
    )

    eval(Task(solver=my_solver(model)))

    # What should the token usage be now?
    print(f"After running agents, usage: {sample_total_tokens()}")
