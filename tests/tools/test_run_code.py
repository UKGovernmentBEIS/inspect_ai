import pytest

from inspect_ai.tool import ToolDef, run_code, Tool
from inspect_ai.tool._tools._run_code import (
    _tool_defs,
    _tool_interface_description,
    _tool_signature,
)

@pytest.fixture
def anyio_backend():
    return "asyncio"

def test_run_code_tool_constructs():
    tool = run_code()
    assert callable(tool)

def test_run_code_tool_def_has_name():
    tool_def = ToolDef(run_code())
    assert tool_def.name == "run_code"

def test_run_code_accepts_empty_tools_list():
    tool = run_code(tools=[])
    assert callable(tool)

@pytest.mark.anyio
async def test_run_code_tool_executes_stub():
    tool = run_code()
    result = await tool(code="return 1")
    assert isinstance(result, str)
    assert "not implemented" in result.lower()

def dummy_tool() -> Tool:
    async def execute(value: str) -> str:
        """Echo a value.

        Args:
            value: Value to echo.
        """
        return value

    return ToolDef(
        execute,
        name="dummy_tool",
        description="Echo a value.",
    ).as_tool()


def test_run_code_accepts_wrapped_tools():
    tool = run_code(tools=[dummy_tool()])
    assert callable(tool)

def test_run_code_normalizes_wrapped_tools():
    tool_defs = _tool_defs([dummy_tool()])
    assert len(tool_defs) == 1
    assert tool_defs[0].name == "dummy_tool"

def test_tool_signature_includes_parameter_schema():
    tool_defs = _tool_defs([dummy_tool()])

    signature = _tool_signature(tool_defs[0])

    assert signature == "dummy_tool(value: string)"


def test_tool_interface_description_without_tools():
    description = _tool_interface_description([])

    assert "No inner tools" in description


def test_tool_interface_description_with_tool():
    tool_defs = _tool_defs([dummy_tool()])

    description = _tool_interface_description(tool_defs)

    assert "dummy_tool(value: string)" in description
    assert "Echo a value." in description


def test_run_code_description_mentions_wrapped_tool():
    tool = run_code(tools=[dummy_tool()])
    tool_def = ToolDef(tool)

    assert "dummy_tool(value: string)" in tool_def.description
    assert "Echo a value." in tool_def.description
