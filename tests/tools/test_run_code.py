import pytest

from inspect_ai.tool import Tool, ToolDef, run_code
from inspect_ai.tool._tools._run_code._run_code import (
    _tool_defs,
    _tool_interface_description,
    _tool_signature,
)
from inspect_ai.tool._tools._run_code._run_code_executor import RunCodeResult

from inspect_ai.tool._tools._run_code._bridge import (
    RunCodeToolBridge,
    external_functions_for_tool_defs,
)

from inspect_ai.tool._tools._run_code._run_code import _format_run_code_result
from inspect_ai.tool._tools._run_code._bridge import RunCodeInnerToolCall
import asyncio
from inspect_ai.tool._tools._run_code._bridge import _preview

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


@pytest.mark.anyio
async def test_run_code_bridge_records_inner_tool_call():
    bridge = RunCodeToolBridge(_tool_defs([dummy_tool()]))

    external_functions = bridge.external_functions()
    result = await external_functions["dummy_tool"]("hello")

    assert result == "hello"
    assert len(bridge.calls) == 1
    assert bridge.calls[0].name == "dummy_tool"
    assert bridge.calls[0].args_preview == "('hello',)"
    assert bridge.calls[0].kwargs_preview == "{}"
    assert bridge.calls[0].result_preview == "'hello'"
    assert bridge.calls[0].error is None

@pytest.mark.anyio
async def test_run_code_bridge_enforces_max_tool_calls():
    bridge = RunCodeToolBridge(
        _tool_defs([dummy_tool()]),
        max_tool_calls=1,
    )

    external_functions = bridge.external_functions()

    assert await external_functions["dummy_tool"]("first") == "first"

    with pytest.raises(RuntimeError, match="Maximum run_code inner tool calls exceeded"):
        await external_functions["dummy_tool"]("second")

    assert len(bridge.calls) == 1

def failing_tool() -> Tool:
    async def execute(value: str) -> str:
        """Fail.

        Args:
            value: Ignored value.
        """
        raise RuntimeError("inner boom")

    return ToolDef(
        execute,
        name="failing_tool",
        description="Always fails.",
    ).as_tool()

@pytest.mark.anyio
async def test_run_code_bridge_records_inner_tool_error():
    bridge = RunCodeToolBridge(_tool_defs([failing_tool()]))

    external_functions = bridge.external_functions()

    with pytest.raises(RuntimeError, match="inner boom"):
        await external_functions["failing_tool"]("x")

    assert len(bridge.calls) == 1
    assert bridge.calls[0].name == "failing_tool"
    assert bridge.calls[0].error == "inner boom"

@pytest.mark.anyio
async def test_run_code_monty_enforces_max_tool_calls():
    pytest.importorskip("pydantic_monty")

    tool = run_code(
        tools=[dummy_tool()],
        execute=True,
        max_tool_calls=1,
    )

    result = await tool(
        code="""
await dummy_tool("first")
await dummy_tool("second")
"""
    )

    assert "Maximum run_code inner tool calls exceeded" in result

def test_format_run_code_result_without_trace():
    result = RunCodeResult(
        output="hello",
        inner_tool_calls=[
            RunCodeInnerToolCall(
                name="dummy_tool",
                args_preview="('x',)",
                kwargs_preview="{}",
                result_preview="'x'",
            )
        ],
    )

    formatted = _format_run_code_result(
        result,
        include_tool_call_trace=False,
    )

    assert formatted == "hello"


def test_format_run_code_result_with_trace():
    result = RunCodeResult(
        output="hello",
        inner_tool_calls=[
            RunCodeInnerToolCall(
                name="dummy_tool",
                args_preview="('x',)",
                kwargs_preview="{}",
                result_preview="'x'",
            )
        ],
    )

    formatted = _format_run_code_result(
        result,
        include_tool_call_trace=True,
    )

    assert "hello" in formatted
    assert "Inner tool calls:" in formatted
    assert "- dummy_tool: ok" in formatted

def test_format_run_code_result_with_error_trace():
    result = RunCodeResult(
        output="",
        error="boom",
        inner_tool_calls=[
            RunCodeInnerToolCall(name="dummy_tool", error="inner boom")
        ],
    )

    formatted = _format_run_code_result(
        result,
        include_tool_call_trace=True,
    )

    assert "boom" in formatted
    assert "- dummy_tool: error" in formatted
    assert "inner boom" in formatted

@pytest.mark.anyio
async def test_run_code_can_include_inner_tool_trace_with_monty():
    pytest.importorskip("pydantic_monty")

    tool = run_code(
        tools=[dummy_tool()],
        execute=True,
        include_tool_call_trace=True,
    )

    result = await tool(code='await dummy_tool("hello")')

    assert "hello" in result
    assert "Inner tool calls:" in result
    assert "- dummy_tool: ok" in result

class SlowRunCodeExecutor:
    async def execute(self, code: str) -> RunCodeResult:
        await asyncio.sleep(1)
        return RunCodeResult(output="finished")

@pytest.mark.anyio
async def test_run_code_enforces_timeout():
    tool = run_code(
        executor=SlowRunCodeExecutor(),
        timeout=0.01,
    )

    result = await tool(code="slow")

    assert "timed out" in result

class LargeOutputRunCodeExecutor:
    async def execute(self, code: str) -> RunCodeResult:
        return RunCodeResult(output="x" * 100)

@pytest.mark.anyio
async def test_run_code_truncates_output():
    tool = run_code(
        executor=LargeOutputRunCodeExecutor(),
        max_output_chars=50,
    )

    result = await tool(code="large")

    assert len(result) <= 50
    assert "truncated" in result

def test_run_code_preview_truncates_long_values():
    preview = _preview("x" * 100, max_chars=30)

    assert len(preview) <= 30
    assert "truncated" in preview

def test_run_code_preview_handles_bad_repr():
    class BadRepr:
        def __repr__(self) -> str:
            raise RuntimeError("bad repr")

    preview = _preview(BadRepr())

    assert "unrepresentable" in preview
