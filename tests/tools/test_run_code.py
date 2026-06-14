import asyncio

import pytest

from inspect_ai.approval import ApprovalPolicy, approval, auto_approver
from inspect_ai.tool import Tool, ToolDef, ToolError, run_code
from inspect_ai.tool._tools._run_code._bridge import (
    RunCodeInnerToolCall,
    RunCodeToolBridge,
    _preview,
    external_functions_for_tool_defs,
)
from inspect_ai.tool._tools._run_code._run_code import (
    _format_run_code_result,
    _run_code_usage_description,
    _tool_def_by_name,
    _tool_defs,
    _tool_interface_description,
    _tool_signature,
)
from inspect_ai.tool._tools._run_code._run_code_executor import RunCodeResult


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

    assert "Use `await`" in tool_def.description
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

    tool = run_code(execute_code=True)
    result = await tool(code="1 + 1")

    assert result == "2"


@pytest.mark.anyio
async def test_run_code_reports_monty_error():
    pytest.importorskip("pydantic_monty")

    tool = run_code(execute_code=True)
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

    tool = run_code(tools=[dummy_tool()], execute_code=True)

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
        max_inner_tool_calls=1,
    )

    external_functions = bridge.external_functions()

    assert await external_functions["dummy_tool"]("first") == "first"

    with pytest.raises(
        RuntimeError, match="Maximum run_code inner tool calls exceeded"
    ):
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
        execute_code=True,
        max_inner_tool_calls=1,
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
        inner_tool_calls=[RunCodeInnerToolCall(name="dummy_tool", error="inner boom")],
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
        execute_code=True,
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


def test_run_code_rejects_duplicate_wrapped_tool_names():
    tool_defs = _tool_defs([dummy_tool(), dummy_tool()])

    with pytest.raises(ValueError, match="Duplicate run_code inner tool name"):
        _tool_def_by_name(tool_defs)


def test_run_code_rejects_duplicate_wrapped_tool_names_at_construction():
    with pytest.raises(ValueError, match="Duplicate run_code inner tool name"):
        run_code(tools=[dummy_tool(), dummy_tool()])


def test_run_code_usage_description_without_tools():
    description = _run_code_usage_description([])

    assert "Write Python code" in description
    assert "No inner Inspect tools are available" in description


def test_run_code_usage_description_with_tools_mentions_await():
    tool_defs = _tool_defs([dummy_tool()])

    description = _run_code_usage_description(tool_defs)

    assert "Use `await`" in description
    assert "await dummy_tool(value: string)" in description
    assert "Echo a value." in description


def second_dummy_tool() -> Tool:
    async def execute(value: str) -> str:
        """Echo a second value.

        Args:
            value: Value to echo.
        """
        return f"second:{value}"

    return ToolDef(
        execute,
        name="second_dummy_tool",
        description="Echo a second value.",
    ).as_tool()


@pytest.mark.anyio
async def test_run_code_bridge_can_call_multiple_wrapped_tools():
    bridge = RunCodeToolBridge(_tool_defs([dummy_tool(), second_dummy_tool()]))

    external_functions = bridge.external_functions()

    result_1 = await external_functions["dummy_tool"]("a")
    result_2 = await external_functions["second_dummy_tool"]("b")

    assert result_1 == "a"
    assert result_2 == "second:b"

    assert len(bridge.calls) == 2
    assert bridge.calls[0].name == "dummy_tool"
    assert bridge.calls[1].name == "second_dummy_tool"


@pytest.mark.anyio
async def test_run_code_can_call_multiple_wrapped_tools_with_monty():
    pytest.importorskip("pydantic_monty")

    tool = run_code(
        tools=[dummy_tool(), second_dummy_tool()],
        execute_code=True,
    )

    result = await tool(
        code="""
a = await dummy_tool("x")
b = await second_dummy_tool("y")
[a, b]
"""
    )

    assert "x" in result
    assert "second:y" in result


@pytest.mark.anyio
async def test_run_code_can_call_wrapped_tools_with_asyncio_gather():
    pytest.importorskip("pydantic_monty")

    tool = run_code(
        tools=[dummy_tool(), second_dummy_tool()],
        execute_code=True,
        include_tool_call_trace=True,
    )

    result = await tool(
        code="""
import asyncio

results = await asyncio.gather(
    dummy_tool("x"),
    second_dummy_tool("y"),
)
results
"""
    )

    assert "x" in result
    assert "second:y" in result
    assert "Inner tool calls:" in result
    assert "dummy_tool" in result
    assert "second_dummy_tool" in result


def test_run_code_usage_description_mentions_asyncio_gather():
    tool_defs = _tool_defs([dummy_tool()])
    description = _run_code_usage_description(tool_defs)

    assert "asyncio.gather" in description


def typed_count_tool(calls: list[int]) -> Tool:
    async def execute(count: int) -> str:
        """Echo a count.

        Args:
            count: Count to echo.
        """
        calls.append(count)
        return f"count:{count}"

    return ToolDef(
        execute,
        name="typed_count_tool",
        description="Echo a typed count.",
    ).as_tool()


@pytest.mark.anyio
async def test_run_code_bridge_uses_inspect_argument_validation():
    calls: list[int] = []
    bridge = RunCodeToolBridge(_tool_defs([typed_count_tool(calls)]))

    external_functions = bridge.external_functions()
    result = await external_functions["typed_count_tool"]("not-an-int")

    assert calls == []
    assert isinstance(result, str)
    assert result
    assert "validation errors parsing tool input arguments" in result
    assert "not-an-int" in result
    assert "integer" in result


def tool_error_tool() -> Tool:
    async def execute(value: str) -> str:
        """Raise a ToolError.

        Args:
            value: Ignored value.
        """
        raise ToolError("bad inner input")

    return ToolDef(
        execute,
        name="tool_error_tool",
        description="Always raises ToolError.",
    ).as_tool()


@pytest.mark.anyio
async def test_run_code_bridge_surfaces_inner_tool_error():
    bridge = RunCodeToolBridge(_tool_defs([tool_error_tool()]))

    external_functions = bridge.external_functions()
    result = await external_functions["tool_error_tool"]("x")

    assert isinstance(result, str)
    assert "bad inner input" in result


@pytest.mark.anyio
async def test_run_code_bridge_uses_inspect_approval_for_inner_tool_calls():
    calls: list[str] = []

    def approval_probe_tool() -> Tool:
        async def execute(value: str) -> str:
            """Record a value.

            Args:
                value: Value to record.
            """
            calls.append(value)
            return f"approved:{value}"

        return ToolDef(
            execute,
            name="approval_probe_tool",
            description="Tool used to test approval.",
        ).as_tool()

    bridge = RunCodeToolBridge(_tool_defs([approval_probe_tool()]))

    external_functions = bridge.external_functions()

    with approval(
        [
            ApprovalPolicy(
                approver=auto_approver(decision="reject"),
                tools="approval_probe_tool",
            )
        ]
    ):
        result = await external_functions["approval_probe_tool"]("secret")

    assert calls == []
    assert isinstance(result, str)
    assert result == "approval: Automatic decision."
