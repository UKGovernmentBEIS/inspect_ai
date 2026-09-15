import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import ToolDef, tool


@tool(prompt="Use this tool when addition is required.")
def prompted_addition():
    async def execute(x: int, y: int) -> int:
        """
        Add two numbers.

        Args:
            x (int): First number.
            y (int): Second number.
        """
        return x + y

    return execute


def test_tool_def() -> None:
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="addition2",
                tool_arguments={"x": 1, "y": 1},
            ),
            ModelOutput.from_content("mockllm/model", content="2"),
        ],
    )

    async def addition(x: int, y: int):
        return x + y

    addition_tool = ToolDef(
        tool=addition,
        name="addition2",
        description="Add two numbers",
        parameters={"x": "Integer", "y": "Integer"},
    )

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[use_tools(addition_tool.as_tool()), generate()],
        scorer=match(numeric=True),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"


def test_tool_def_does_not_duplicate_prompt_text() -> None:
    tool = prompted_addition()

    first = ToolDef(tool)
    second = ToolDef(tool)

    assert first.description == second.description
    assert second.description.count("Use this tool when addition is required.") == 1


def test_tool_def_max_output_round_trips() -> None:
    async def addition(x: int, y: int):
        return x + y

    tool_def = ToolDef(
        tool=addition,
        name="addition",
        description="Add two numbers",
        parameters={"x": "Integer", "y": "Integer"},
        max_output=0,
    )
    assert ToolDef(tool_def.as_tool()).max_output == 0


def test_tool_max_output_declaration_inherited_by_outer_tool() -> None:
    @tool(max_output=0)
    def inner():
        async def execute(x: int) -> int:
            """Echo an integer.

            Args:
                x: The integer.
            """
            return x

        return execute

    # an unspecified outer max_output inherits the inner declaration
    @tool
    def outer():
        return inner()

    # an explicit outer max_output overrides it
    @tool(max_output=64)
    def overriding():
        return inner()

    assert ToolDef(inner()).max_output == 0
    assert ToolDef(outer()).max_output == 0
    assert ToolDef(overriding()).max_output == 64


def test_negative_max_output_rejected() -> None:
    # a negative value would silently disable truncation (truncate_string_to_bytes
    # short-circuits on max_bytes <= 0) rather than cap it, so reject it up front
    async def noop(x: int) -> int:
        return x

    with pytest.raises(ValueError, match="max_output must be"):

        @tool(max_output=-1)
        def bad():
            return noop

    with pytest.raises(ValueError, match="max_output must be"):
        ToolDef(
            tool=noop,
            name="noop",
            description="Noop",
            parameters={"x": "Integer"},
            max_output=-1,
        )
