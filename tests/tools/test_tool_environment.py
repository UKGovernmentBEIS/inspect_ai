from test_helpers.tools import list_files, read_file

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageTool, ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools


def test_tool_environment_read_file():
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
        tool_environment="local",
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
                )
            ],
        ),
        max_messages=5,  # otherwise we can get into an infinite loop if the tools error
    )[0]

    chat_message_tool = result.samples[0].messages[-1]
    assert isinstance(chat_message_tool, ChatMessageTool)
    assert result.status == "success"
    assert chat_message_tool.text == "contents_of_foo.txt"


def test_tool_environment_list_files():
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
        tool_environment="local",
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
                )
            ],
        ),
        max_messages=5,  # otherwise we can get into an infinite loop if the tools error
    )[0]

    chat_message_tool = result.samples[0].messages[-1]
    assert isinstance(chat_message_tool, ChatMessageTool)
    assert result.status == "success"
    assert chat_message_tool.text == "bar.txt\nbaz.txt\n"
