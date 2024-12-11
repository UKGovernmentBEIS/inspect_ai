from typing import Literal

import pytest
from test_helpers.tools import addition, list_files, read_file
from test_helpers.utils import simple_task_state
from typing_extensions import Unpack

from inspect_ai.model import CachePolicy, GenerateConfigArgs
from inspect_ai.solver import TaskState, use_tools


def null_generate(
    state: TaskState,
    tool_calls: Literal["loop", "single", "none"] = "loop",
    cache: bool | CachePolicy = False,
    **kwargs: Unpack[GenerateConfigArgs],
) -> TaskState:
    return state


@pytest.mark.asyncio
async def test_use_tools():
    state = simple_task_state()

    addition_tool = addition()
    read_file_tool = read_file()

    state = await (use_tools([addition_tool, read_file_tool]))(state, null_generate)
    assert state.tools == [addition_tool, read_file_tool]

    state = await (use_tools([addition_tool, read_file_tool]))(state, null_generate)
    assert state.tools == [addition_tool, read_file_tool]

    state = await (use_tools(addition_tool, read_file_tool))(state, null_generate)
    assert state.tools == [addition_tool, read_file_tool]

    state = await (use_tools([addition_tool]))(state, null_generate)
    assert state.tools == [addition_tool]

    state = await (use_tools(addition_tool))(state, null_generate)
    assert state.tools == [addition_tool]

    state = await (use_tools(tool_choice="auto"))(state, null_generate)
    assert state.tools == [addition_tool]
    assert state.tool_choice == "auto"


@pytest.mark.asyncio
async def test_use_tools_append():
    state = simple_task_state()

    addition_tool = addition()
    read_file_tool = read_file()
    list_files_tool = list_files()

    state = await (use_tools([addition_tool, read_file_tool]))(state, null_generate)
    assert state.tools == [addition_tool, read_file_tool]

    # append to the tools
    state = await (use_tools([list_files_tool], append=True))(state, null_generate)
    assert state.tools == [addition_tool, read_file_tool, list_files_tool]

    # now replace the tools
    state = await (use_tools([addition_tool]))(state, null_generate)
    assert state.tools == [addition_tool]
