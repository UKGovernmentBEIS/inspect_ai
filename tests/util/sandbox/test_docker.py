import textwrap
from typing import Any

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox


@solver
def exec_solver(exec_args: list[dict[str, Any]]) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        results: list[str] = []
        for args in exec_args:
            result = await sandbox().exec(**args)
            results.append(result.stdout.strip())
        state.output.completion = "\n".join(results)
        return state

    return solve


@task
def custom_task(solver: Solver, setup: str | None = None) -> Task:
    return Task(
        dataset=[Sample(input="irrelevant", setup=setup)],
        plan=[solver],
        sandbox="docker",
    )


def run_eval(task: Task) -> str:
    result = eval(task, model="mockllm/model")[0]
    assert result.samples is not None
    content = result.samples[0].output.choices[0].message.content
    assert isinstance(content, str)
    return content


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_env() -> None:
    echo_solver = exec_solver([{"cmd": ["echo", "Hello, World!"]}])
    echo_task = custom_task(echo_solver)
    message = run_eval(echo_task)
    assert message == "Hello, World!"


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_users() -> None:
    whoami_solver = exec_solver(
        [
            {"cmd": ["whoami"], "user": "root"},
            {"cmd": ["whoami"], "user": "myuser"},
        ]
    )
    add_user_script = textwrap.dedent(
        """#!/bin/bash
        useradd -m myuser"""
    )
    whoami_task = custom_task(whoami_solver, setup=add_user_script)
    message = run_eval(whoami_task)
    expected_output = "root\nmyuser"
    assert message == expected_output, f"Expected '{expected_output}', got '{message}'"


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_nonexistent_user() -> None:
    nonexistent_solver = exec_solver(
        [
            {"cmd": ["whoami"], "user": "nonexistent"},
        ]
    )
    nonexistent_task = custom_task(nonexistent_solver)
    message = run_eval(nonexistent_task)
    expected_error = (
        "unable to find user nonexistent: no matching entries in passwd file"
    )
    assert expected_error in message
