from typing import Literal

from test_helpers.tool_call_utils import get_tool_call, get_tool_response

from inspect_ai import Task, eval
from inspect_ai._util.text import TruncatedOutput, truncate_string_to_bytes
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver._solver import generate
from inspect_ai.solver._use_tools import use_tools
from inspect_ai.tool._tool import tool


def test_max_tool_output():
    @tool
    def output(size: int):
        async def execute():
            """
            Generate some output

            Returns:
                The output
            """
            return "x" * size

        return execute

    def mock_model():
        return get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="output",
                    tool_arguments={},
                ),
                ModelOutput.from_content(model="mockllm/model", content="content"),
            ],
        )

    task = Task(
        dataset=[
            Sample(
                input="Please call the output tool and then reply with its output in a normal assistant message."
            )
        ],
        solver=[use_tools(output(10)), generate()],
        config=GenerateConfig(max_tool_output=5),
    )

    def check_log(log: EvalLog, count: int, overflow=True):
        assert log.samples
        messages = log.samples[0].messages
        output_call = get_tool_call(messages, "output")
        assert output_call
        output_result = get_tool_response(messages, output_call)
        assert output_result
        if overflow:
            newline = "\n"
            assert f"{newline}{'x' * count}{newline}" in output_result.content
        else:
            assert "x" * count == output_result.content

    log = eval(task, mock_model())[0]
    check_log(log, 5)

    log = eval(task, mock_model(), max_tool_output=7)[0]
    check_log(log, 7)

    log = eval(task, mock_model(), max_tool_output=0)[0]
    check_log(log, 10, False)


def test_text_truncation():
    def check(output: TruncatedOutput | None, check: Literal[True] | str | None):
        if output is None:
            assert check is None
        elif check is True:
            assert output is not None
        else:
            assert output.output == check

    check(truncate_string_to_bytes("Hello", 10), None)
    check(truncate_string_to_bytes("Hello, World", 5), "Hello")
    check(truncate_string_to_bytes("Hello, 世界! 🌍", 10), True)
    check(truncate_string_to_bytes("🌍🌎🌏", 5), "🌍�")
    # 0 means no truncation
    check(truncate_string_to_bytes("Hello World!", 0), None)
    # invalid byte
    check(truncate_string_to_bytes("Invalid \x80 byte", 15), None)
    check(truncate_string_to_bytes("Invalid \x80 byte", 7), "Invalid")
    check(truncate_string_to_bytes("Invalid \x80 byte", 12), "Invalid \x80 b")
    # emoji that's 3 bytes long
    check(truncate_string_to_bytes("☺️", 2), "�")
