import itertools

from test_helpers.tools import list_files, read_file
from tool_call_utils import get_tool_calls, get_tool_response

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
        plan=[use_tools([read_file(), list_files()]), generate()],
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
        max_messages=5,  # otherwise we can get into an infinite loop if the tools error
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
        plan=[use_tools([read_file(), list_files()]), generate()],
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
        max_messages=5,  # otherwise we can get into an infinite loop if the tools error
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
        plan=[
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
        max_messages=5,  # otherwise we can get into an infinite loop if the tools error
    )[0]

    chat_message_tool = find_tool_call(result, "read_file")
    assert result.status == "success"
    assert chat_message_tool.error and "not found" in chat_message_tool.error.message
