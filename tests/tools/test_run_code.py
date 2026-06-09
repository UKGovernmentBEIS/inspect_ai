import pytest

from inspect_ai.tool import ToolDef, run_code, Tool

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
