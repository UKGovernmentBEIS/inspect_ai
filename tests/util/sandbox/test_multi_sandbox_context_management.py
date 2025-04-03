from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox
from inspect_ai.util._sandbox.context import sandbox_default

CURRENT_DIRECTORY = Path(__file__).resolve().parent


@tool
def write_file_service(environment_name: str | None = None) -> Tool:
    async def execute(file: str, content: str):
        """
        Writes the contents of a file.

        Args:
          file (str): File to write.
          content(str): Content to write to the file.


        """
        await sandbox(environment_name).write_file(file, content)

    return execute


@tool
def read_file_service(environment_name: str | None = None) -> Tool:
    async def execute(file: str) -> str:
        """
        Reads the contents of a file.

        Args:
          file (str): File to read.


        Returns:
            str: Contents of the file.

        """
        return await sandbox(environment_name).read_file(file, text=True)

    return execute


@solver
def act_in_environment(
    environment_name: str | None = None,
) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        with sandbox_default(environment_name or "default"):
            return await generate(state, tool_calls="single")

    return solve


@solver
def verify_actions() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        foo_default = await sandbox().read_file("foo_default.txt")
        assert foo_default == "default_content"

        foo_service_1 = await sandbox("service_1").read_file("foo_service_1.txt")
        assert foo_service_1 == "service_1_content"

        foo_service_2 = await sandbox("service_2").read_file("foo_service_2.txt")
        assert foo_service_2 == "service_2_content"

        # check that reaing a non-existent file fails
        with pytest.raises(FileNotFoundError):
            await sandbox().read_file("bar_default.txt")

        # check that reading from the wrong environment fails
        with pytest.raises(FileNotFoundError):
            await sandbox("service_1").read_file("foo_default.txt")

        return state

    return solve


@skip_if_no_docker
@pytest.mark.slow
def test_docker_compose_multiple_services_write_file():
    task = Task(
        dataset=[Sample(input="test dummy input")],
        solver=[
            use_tools(
                [
                    write_file_service(),
                    read_file_service(),
                ]
            ),
            generate(tool_calls="single"),  # the default, no wrapper
            act_in_environment("service_1"),
            act_in_environment("service_2"),
            act_in_environment(),  # should also use the default,
            verify_actions(),
        ],
        sandbox=(
            "docker",
            str(
                CURRENT_DIRECTORY
                / "docker_compose_multiple_services/docker-compose.yaml"
            ),
        ),
    )

    def tool_calls():
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="write_file_service",
            tool_arguments={"file": "foo_default.txt", "content": "default_content"},
        )
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="write_file_service",
            tool_arguments={
                "file": "foo_service_1.txt",
                "content": "service_1_content",
            },
        )
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="write_file_service",
            tool_arguments={
                "file": "foo_service_2.txt",
                "content": "service_2_content",
            },
        )
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="read_file_service",
            tool_arguments={"file": "foo_default.txt", "content": "default_content"},
        )

    result = eval(
        task,
        model=get_model("mockllm/model", custom_outputs=tool_calls()),
        message_limit=10,  # otherwise we can get into an infinite loop if the tools error
    )[0]
    assert result.status == "success"
