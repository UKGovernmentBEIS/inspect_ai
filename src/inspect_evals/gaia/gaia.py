from pathlib import Path
from textwrap import dedent
from typing import Any, Literal

from inspect_ai import Task, task
from inspect_ai.solver import Solver, basic_agent, system_message
from inspect_ai.tool import bash, python, web_browser_tools

from .dataset import gaia_dataset
from .scorer import gaia_scorer


@task
def gaia(
    solver: Solver | None = None,
    input_prompt: str | None = None,
    max_attempts: int = 1,
    max_messages: int = 100,
    subset: Literal[
        "2023_all", "2023_level1", "2023_level2", "2023_level3"
    ] = "2023_all",
    split: Literal["test", "validation"] = "validation",
    instance_ids: list[str] | None = None,
) -> Task:
    # read dataset
    dataset = gaia_dataset(
        input_prompt=input_prompt,
        subset=subset,
        split=split,
    )

    # filter by instance id if requested
    if instance_ids:
        dataset = dataset.filter(lambda x: x.id in instance_ids)

    # resolve solver
    solver = solver or default_solver(max_attempts)

    # resolve scorer (test split has no answers)
    scorer = gaia_scorer() if split == "validation" else None

    # docker compose file is alongside the src file
    COMPOSE_FILE = Path(__file__).parent / "compose.yaml"

    # return task
    return Task(
        dataset=dataset,
        plan=solver,
        scorer=scorer,
        sandbox=("docker", COMPOSE_FILE.as_posix()),
        max_messages=max_messages,
    )


@task
def gaia_level1(**kwargs: Any) -> Task:
    return gaia(subset="2023_level1", **kwargs)


@task
def gaia_level2(**kwargs: Any) -> Task:
    return gaia(subset="2023_level2", **kwargs)


@task
def gaia_level3(**kwargs: Any) -> Task:
    return gaia(subset="2023_level3", **kwargs)


def default_solver(max_attempts: int, code_timeout: int = 180) -> Solver:
    return basic_agent(
        init=system_message(
            dedent("""
                You are an autonomous AI agent, consisting of a large language model and a scaffolding program that runs on a linux VM.

                You have full control over your VM through the scaffolding program's provided functions, including: writing and editing files, running bash commands, installing packages etc.. From your VM, you can access the internet.

                You are state-of-the-art, and excellent at analysis, planning and programming. You possess encyclopedic knowledge of the world. You write in a very direct and concise style.

                You are resourceful and adaptive, and you never give up. Before deciding something can't be done, you try it out. You consider multiple options and choose the best one. If your current approach doesn't work, you formulate a new plan. You are given a task you need to solve completely on your own.

                Please think step by step before calling tools. When you are ready to answer, use the submit tool to provide your final answer.
                """)
        ),
        tools=[bash(code_timeout), python(code_timeout)] + web_browser_tools(),
        max_attempts=max_attempts,
    )
