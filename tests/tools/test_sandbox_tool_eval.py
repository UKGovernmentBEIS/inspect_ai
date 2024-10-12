import itertools
from pathlib import Path
from typing import Generator

import pytest
from test_helpers.tool_call_utils import get_tool_calls, get_tool_response
from test_helpers.tools import command_exec, list_files, read_file
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools


def find_tool_call(result, tool_call_id: str):
    messages = result.samples[0].messages
    return get_tool_response(messages, get_tool_calls(messages, tool_call_id)[0])


def test_sandbox_environment_read_file():
    dataset = [
        Sample(
            input="What are the contents of file foo.txt?",
            target="unused",
            files={"foo.txt": "contents_of_foo.txt"},
        )
    ]
    task = Task(
        dataset=dataset,
        solver=[use_tools([read_file(), list_files()]), generate()],
        scorer=includes(),
        sandbox="local",
    )
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="read_file",
                    tool_arguments={"file": "foo.txt"},
                ),
                ModelOutput.from_content(
                    model="mockllm/model", content="Contents of foo.txt."
                ),
            ],
        ),
        message_limit=5,  # otherwise we can get into an infinite loop if the tools error
    )[0]

    chat_message_tool = find_tool_call(result, "read_file")
    assert result.status == "success"
    assert chat_message_tool.text == "contents_of_foo.txt"


def test_sandbox_environment_list_files():
    dataset = [
        Sample(
            input="What files are there?",
            target="Hello",
            files={"bar.txt": "contents_of_bar.txt", "baz.txt": "contents_of_baz.txt"},
        )
    ]
    task = Task(
        dataset=dataset,
        solver=[use_tools([read_file(), list_files()]), generate()],
        scorer=includes(),
        sandbox="local",
    )
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="list_files",
                    tool_arguments={"dir": "."},
                ),
                ModelOutput.from_content(
                    model="mockllm/model", content="Lots of files!"
                ),
            ],
        ),
        message_limit=5,  # otherwise we can get into an infinite loop if the tools error
    )[0]

    chat_message_tool = find_tool_call(result, "list_files")
    assert result.status == "success"
    assert chat_message_tool.text == "bar.txt\nbaz.txt\n"


def test_sandbox_environment_read_file_error():
    dataset = [
        Sample(
            input="What are the contents of file nonexistent.txt?",
            target="unused",
        )
    ]
    task = Task(
        dataset=dataset,
        solver=[
            use_tools(
                [
                    read_file(),
                ]
            ),
            generate(),
        ],
        scorer=includes(),
        sandbox="local",
    )
    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=itertools.chain(
                [
                    ModelOutput.for_tool_call(
                        model="mockllm/model",
                        tool_name="read_file",
                        tool_arguments={"file": "nonexistent.txt"},
                    )
                ],
                (
                    ModelOutput.from_content(model="mockllm/model", content="finished")
                    for i in range(10)
                ),
            ),
        ),
        message_limit=5,  # otherwise we can get into an infinite loop if the tools error
    )[0]

    chat_message_tool = find_tool_call(result, "read_file")
    assert result.status == "success"
    assert chat_message_tool.error and "not found" in chat_message_tool.error.message


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_environment_nonroot_files():
    """Checks the file passed in as part of the Sample is actually readable by the Docker user in the container."""
    dataset = [
        Sample(
            input="What are the contents of file bar.txt?",
            files={"bar.txt": "hello"},
            target="unused",
        )
    ]
    task = Task(
        dataset=dataset,
        solver=[
            use_tools(
                [
                    command_exec(),
                    read_file(),
                ]
            ),
            generate(),
        ],
        scorer=includes(),
        sandbox=("docker", str(Path(__file__) / ".." / "test_sandbox_compose.yaml")),
    )

    def custom_outputs() -> Generator[ModelOutput, None, None]:
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="command_exec",
            tool_arguments={"command": "id"},
        )
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="read_file",
            tool_arguments={"file": "bar.txt"},
        )
        while True:
            yield ModelOutput.from_content(
                model="mockllm/model",
                content="finished",
            )

    result = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=custom_outputs(),
        ),
        message_limit=5,
        sandbox_cleanup=False,
    )[0]

    assert result.status == "success"
    id_chat_message_tool = find_tool_call(result, "command_exec")
    # the test is broken if it's ended up as the root user;
    # the point is to check the non-root user from the test_sandbox_compose config
    assert "uid=0(root)" not in id_chat_message_tool.text

    read_file_chat_message_tool = find_tool_call(result, "read_file")
    assert not read_file_chat_message_tool.error
    assert "hello" in read_file_chat_message_tool.text
