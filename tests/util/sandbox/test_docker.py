import textwrap
from typing import Callable, NamedTuple

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox


class CommandAndUser(NamedTuple):
    command: list[str]
    user: str | None = None


def create_exec_solver(
    command_user_pairs: list[CommandAndUser],
) -> Callable[..., Solver]:
    @solver
    def exec_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            results: list[str] = []
            for command, user in command_user_pairs:
                result = await sandbox().exec(command, user=user)
                results.append(result.stdout.strip())
            state.output.completion = "\n".join(results)
            return state

        return solve

    return exec_solver


def create_task(solver: Solver, setup: str | None = None) -> Callable[..., Task]:
    @task
    def custom_task() -> Task:
        return Task(
            dataset=[Sample(input="irrelevant", setup=setup)],
            plan=[solver],
            sandbox="docker",
        )

    return custom_task


def run_eval(task: Callable[..., Task]) -> str:
    result = eval(task, model="mockllm/model")[0]
    assert result.samples is not None
    content = result.samples[0].output.choices[0].message.content
    assert isinstance(content, str)
    return content


def test_docker_sandbox_env() -> None:
    echo_solver = create_exec_solver(
        [CommandAndUser(["echo", "Hello, World!"], None)],
    )
    echo_task = create_task(echo_solver())
    message = run_eval(echo_task)
    assert message == "Hello, World!"


def test_docker_sandbox_users() -> None:
    whoami_solver = create_exec_solver(
        [
            CommandAndUser(["whoami"], "root"),
            CommandAndUser(["whoami"], "myuser"),
        ]
    )
    add_user_script = textwrap.dedent(
        """#!/bin/bash
        useradd -m myuser"""
    )
    whoami_task = create_task(whoami_solver(), setup=add_user_script)
    message = run_eval(whoami_task)
    expected_output = "root\nmyuser"
    assert message == expected_output, f"Expected '{expected_output}', got '{message}'"


def test_docker_sandbox_nonexistent_user() -> None:
    nonexistent_solver = create_exec_solver(
        [
            CommandAndUser(["whoami"], "nonexistent"),
        ]
    )
    nonexistent_task = create_task(nonexistent_solver())
    message = run_eval(nonexistent_task)
    expected_error = (
        "unable to find user nonexistent: no matching entries in passwd file"
    )
    assert expected_error in message
