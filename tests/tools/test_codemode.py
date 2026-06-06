import pytest

from inspect_ai.tool import codemode


def test_codemode_tool_constructs():
    tool = codemode()
    assert callable(tool)


@pytest.mark.anyio
async def test_codemode_tool_executes_stub():
    tool = codemode()
    result = await tool(code="return 1")
    assert isinstance(result, str)
    assert "not implemented" in result.lower()
