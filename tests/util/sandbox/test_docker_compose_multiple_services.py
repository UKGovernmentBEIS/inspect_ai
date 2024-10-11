from pathlib import Path

import pytest
from test_helpers.tool_call_utils import get_tool_calls, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox

CURRENT_DIRECTORY = Path(__file__).resolve().parent


@tool
def write_file_service_1() -> Tool:
    async def execute(file: str, content: str):
        """
        Writes the contents of a file.

        Args:
          file (str): File to write.
          content(str): Content to write to the file.


        """
        await sandbox("service_1").write_file(file, content)

    return execute


@tool
def write_file_service_2() -> Tool:
    async def execute(file: str, content: str):
        """
        Writes the contents of a file.

        Args:
          file (str): File to write.
          content(str): Content to write to the file.


        """
        await sandbox("service_2").write_file(file, content)

    return execute


@tool
def read_file_service_1() -> Tool:
    async def execute(file: str) -> str:
        """
        Reads the contents of a file.

        Args:
          file (str): File to read.


        Returns:
            str: Contents of the file.

        """
        return await sandbox("service_1").read_file(file, text=True)

    return execute


@tool
def read_file_service_2() -> Tool:
    async def execute(file: str) -> str:
        """
        Reads the contents of a file.

        Args:
          file (str): File to read.


        Returns:
            str: Contents of the file.

        """
        return await sandbox("service_2").read_file(file, text=True)

    return execute


@skip_if_no_docker
@pytest.mark.slow
def test_docker_compose_multiple_services_write_file():
    dataset = [
        Sample(
            input="Writes some files please",
            target="unused",
            files={"foo.txt": "contents_of_foo.txt"},
        )
    ]
    task = Task(
        dataset=dataset,
        solver=[
            use_tools(
                [
                    write_file_service_1(),
                    write_file_service_2(),
                    read_file_service_1(),
                    read_file_service_2(),
                ]
            ),
            generate(),
        ],
        scorer=includes(),
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
            tool_name="write_file_service_1",
            tool_arguments={"file": "foo.txt", "content": "unused_1"},
        )
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="write_file_service_2",
            tool_arguments={"file": "foo.txt", "content": "unused_2"},
        )
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="read_file_service_1",
            tool_arguments={"file": "foo.txt"},
        )
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="read_file_service_2",
            tool_arguments={"file": "foo.txt"},
        )
        while True:
            yield ModelOutput.from_content(
                model="mockllm/model", content="nothing left"
            )

    result = eval(
        task,
        model=get_model("mockllm/model", custom_outputs=tool_calls()),
        message_limit=10,  # otherwise we can get into an infinite loop if the tools error
    )[0]

    assert result.status == "success"
    messages = result.samples[0].messages
    assert (
        get_tool_response(
            messages, get_tool_calls(messages, "read_file_service_1")[0]
        ).content
        == "unused_1"
    )
    assert (
        get_tool_response(
            messages, get_tool_calls(messages, "read_file_service_2")[0]
        ).content
        == "unused_2"
    )
