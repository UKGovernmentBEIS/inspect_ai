import pytest

from inspect_ai.tool import ToolDef, codemode

@pytest.fixture
def anyio_backend():
    return "asyncio"

def test_codemode_tool_constructs():
    tool = codemode()
    assert callable(tool)

def test_codemode_tool_def_has_name():
    tool_def = ToolDef(codemode())
    assert tool_def.name == "codemode"

@pytest.mark.anyio
async def test_codemode_tool_executes_stub():
    tool = codemode()
    result = await tool(code="return 1")
    assert isinstance(result, str)
    assert "not implemented" in result.lower()
