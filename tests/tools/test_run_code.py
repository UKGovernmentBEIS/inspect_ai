import pytest

from inspect_ai.tool import Tool, ToolDef, run_code
from inspect_ai.tool._tools._run_code._run_code import (
    _tool_defs,
    _tool_interface_description,
    _tool_signature,
)
from inspect_ai.tool._tools._run_code._run_code_executor import RunCodeResult

from inspect_ai.tool._tools._run_code._bridge import external_functions_for_tool_defs

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

    assert signature == "await dummy_tool(value: string)"


def test_tool_interface_description_without_tools():
    description = _tool_interface_description([])

    assert "No inner tools" in description


def test_tool_interface_description_with_tool():
    tool_defs = _tool_defs([dummy_tool()])

    description = _tool_interface_description(tool_defs)

    assert "await dummy_tool(value: string)" in description
    assert "Echo a value." in description


def test_run_code_description_mentions_wrapped_tool():
    tool = run_code(tools=[dummy_tool()])
    tool_def = ToolDef(tool)

    assert "await dummy_tool(value: string)" in tool_def.description
    assert "Echo a value." in tool_def.description

class FakeRunCodeExecutor:
    async def execute(self, code: str) -> RunCodeResult:
        return RunCodeResult(output=f"executed: {code}")


@pytest.mark.anyio
async def test_run_code_uses_injected_executor():
    tool = run_code(executor=FakeRunCodeExecutor())

    result = await tool(code="x = 1")

    assert result == "executed: x = 1"


class ErrorRunCodeExecutor:
    async def execute(self, code: str) -> RunCodeResult:
        return RunCodeResult(output="", error="boom")


@pytest.mark.anyio
async def test_run_code_returns_executor_error():
    tool = run_code(executor=ErrorRunCodeExecutor())

    result = await tool(code="raise Exception()")

    assert result == "boom"


@pytest.mark.anyio
async def test_run_code_executes_simple_code_with_monty():
    pytest.importorskip("pydantic_monty")

    tool = run_code(execute=True)
    result = await tool(code="1 + 1")

    assert result == "2"

@pytest.mark.anyio
async def test_run_code_reports_monty_error():
    pytest.importorskip("pydantic_monty")

    tool = run_code(execute=True)
    result = await tool(code="raise Exception('boom')")

    assert "boom" in result

@pytest.mark.anyio
async def test_external_functions_call_wrapped_tool():
    tool_defs = _tool_defs([dummy_tool()])
    external_functions = external_functions_for_tool_defs(tool_defs)

    assert "dummy_tool" in external_functions

    result = await external_functions["dummy_tool"]("hello")

    assert result == "hello"

def test_external_functions_reject_duplicate_tool_names():
    tool_defs = _tool_defs([dummy_tool(), dummy_tool()])

    with pytest.raises(ValueError, match="Duplicate"):
        external_functions_for_tool_defs(tool_defs)

@pytest.mark.anyio
async def test_run_code_can_call_wrapped_tool_with_monty():
    pytest.importorskip("pydantic_monty")

    tool = run_code(tools=[dummy_tool()], execute=True)

    result = await tool(code='await dummy_tool("hello")')

    assert result == "hello"
