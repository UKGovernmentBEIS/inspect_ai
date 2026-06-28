import asyncio

import pytest

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.approval import ApprovalPolicy, approval, auto_approver
from inspect_ai.tool import Tool, ToolDef, ToolError, run_code
from inspect_ai.tool._tools._run_code._bridge import (
    RunCodeInnerToolCallTraceEntry,
    RunCodeMaxToolCallsExceededError,
    RunCodeToolBridge,
    _preview,
)
from inspect_ai.tool._tools._run_code._run_code import (
    _format_run_code_result,
    _run_code_usage_description,
    _tool_def_by_name,
    _tool_defs,
    _tool_interface_description,
    _tool_signature,
    _truncate_content,
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
    assert isinstance(result, list)
    assert "not implemented" in result[0].text.lower()


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
        return RunCodeResult(output=[ContentText(text=f"executed: {code}")])


@pytest.mark.anyio
async def test_run_code_uses_injected_executor():
    tool = run_code(executor=FakeRunCodeExecutor())

    result = await tool(code="x = 1")

    assert result == [ContentText(text="executed: x = 1")]


class ErrorRunCodeExecutor:
    async def execute(self, code: str) -> RunCodeResult:
        return RunCodeResult(output=[ContentText(text="")], error="boom")


@pytest.mark.anyio
async def test_run_code_returns_executor_error():
    tool = run_code(executor=ErrorRunCodeExecutor())

    result = await tool(code="raise Exception()")

    assert result == [ContentText(text="boom")]


@pytest.mark.anyio
async def test_run_code_executes_simple_code_with_monty():
    pytest.importorskip("pydantic_monty")

    tool = run_code(executor="monty")
    result = await tool(code="1 + 1")

    assert "2" in result[0].text


@pytest.mark.anyio
async def test_run_code_raises_tool_error_on_monty_syntax_error():
    pytest.importorskip("pydantic_monty")

    tool = run_code(executor="monty")

    with pytest.raises(ToolError) as exc_info:
        await tool(code="def foo(:")

    assert "parameter" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_run_code_raises_tool_error_on_monty_runtime_error():
    pytest.importorskip("pydantic_monty")

    tool = run_code(executor="monty")

    with pytest.raises(ToolError) as exc_info:
        await tool(code="1/0")

    assert "ZeroDivisionError" in str(exc_info.value)


@pytest.mark.anyio
async def test_run_code_returns_falsy_results():
    pytest.importorskip("pydantic_monty")

    tool = run_code(executor="monty")

    for code, expected in [
        ("0", "0"),
        ("1 - 1", "0"),
        ("False", "False"),
        ("[]", "[]"),
    ]:
        result = await tool(code=code)
        assert result
        assert result[0].text == expected


@pytest.mark.anyio
async def test_external_functions_call_wrapped_tool():
    tool_defs = _tool_defs([dummy_tool()])
    bridge = RunCodeToolBridge(tool_defs)
    external_functions = bridge.external_functions()

    assert "dummy_tool" in external_functions

    result = await external_functions["dummy_tool"]("hello")

    assert result == "hello"


def test_external_functions_reject_duplicate_tool_names():
    tool_defs = _tool_defs([dummy_tool(), dummy_tool()])
    bridge = RunCodeToolBridge(tool_defs)

    with pytest.raises(ValueError, match="Duplicate"):
        bridge.external_functions()


@pytest.mark.anyio
async def test_run_code_can_call_wrapped_tool_with_monty():
    pytest.importorskip("pydantic_monty")

    tool = run_code(tools=[dummy_tool()], executor="monty")

    result = await tool(code='await dummy_tool("hello")')

    print(result)

    assert "hello" in result[0].text


@pytest.mark.anyio
async def test_run_code_bridge_records_inner_tool_call():
    bridge = RunCodeToolBridge(_tool_defs([dummy_tool()]))

    external_functions = bridge.external_functions()
    result = await external_functions["dummy_tool"]("hello")

    assert result == "hello"
    assert len(bridge.call_trace) == 1
    assert bridge.call_trace[0].name == "dummy_tool"
    assert bridge.call_trace[0].args_preview == "('hello',)"
    assert bridge.call_trace[0].kwargs_preview == "{}"
    assert "hello" in bridge.call_trace[0].result_preview
    assert "artifacts=0" in bridge.call_trace[0].result_preview
    assert bridge.call_trace[0].error is None


@pytest.mark.anyio
async def test_run_code_bridge_enforces_max_tool_calls():
    bridge = RunCodeToolBridge(
        _tool_defs([dummy_tool()]),
        max_inner_tool_calls=1,
    )

    external_functions = bridge.external_functions()
    result = await external_functions["dummy_tool"]("first")
    assert result == "first"

    with pytest.raises(
        RuntimeError, match="Maximum run_code inner tool calls exceeded"
    ):
        await external_functions["dummy_tool"]("second")

    assert len(bridge.call_trace) == 1


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

    assert len(bridge.call_trace) == 1
    assert bridge.call_trace[0].name == "failing_tool"
    assert bridge.call_trace[0].error == "inner boom"


@pytest.mark.anyio
async def test_run_code_monty_raises_tool_error_on_max_tool_calls():
    pytest.importorskip("pydantic_monty")

    tool = run_code(
        tools=[dummy_tool()],
        executor="monty",
        max_inner_tool_calls=1,
    )

    with pytest.raises(ToolError) as exc_info:
        await tool(
            code="""
await dummy_tool("first")
await dummy_tool("second")
"""
        )

    assert "Maximum run_code inner tool calls exceeded" in str(exc_info.value)


def test_format_run_code_result_without_trace():
    result = RunCodeResult(
        output=[ContentText(text="hello")],
        inner_tool_call_trace=[
            RunCodeInnerToolCallTraceEntry(
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

    assert formatted == [ContentText(text="hello")]


def test_format_run_code_result_with_trace():
    result = RunCodeResult(
        output=[ContentText(text="hello")],
        inner_tool_call_trace=[
            RunCodeInnerToolCallTraceEntry(
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

    assert "hello" in formatted[0].text
    assert "Inner tool calls:" in formatted[1].text
    assert "- dummy_tool: ok" in formatted[1].text


def test_format_run_code_result_with_error_trace():
    result = RunCodeResult(
        output=[],
        error="boom",
        inner_tool_call_trace=[
            RunCodeInnerToolCallTraceEntry(name="dummy_tool", error="inner boom")
        ],
    )

    formatted = _format_run_code_result(
        result,
        include_tool_call_trace=True,
    )

    assert "boom" in formatted[0].text
    assert "- dummy_tool: error" in formatted[1].text
    assert "inner boom" in formatted[1].text


@pytest.mark.anyio
async def test_run_code_can_include_inner_tool_trace_with_monty():
    pytest.importorskip("pydantic_monty")

    tool = run_code(
        tools=[dummy_tool()],
        executor="monty",
        include_tool_call_trace=True,
    )

    result = await tool(code='await dummy_tool("hello")')

    assert "hello" in result[0].text
    assert "Inner tool calls:" in result[1].text
    assert "- dummy_tool: ok" in result[1].text


class SlowRunCodeExecutor:
    async def execute(self, code: str) -> RunCodeResult:
        await asyncio.sleep(1)
        return RunCodeResult(output=[ContentText(text="finished")])


@pytest.mark.anyio
async def test_run_code_enforces_timeout():
    tool = run_code(
        executor=SlowRunCodeExecutor(),
        timeout=0.01,
    )

    result = await tool(code="slow")

    assert "timed out" in result[0].text


class LargeOutputRunCodeExecutor:
    async def execute(self, code: str) -> RunCodeResult:
        return RunCodeResult(output=[ContentText(text="x" * 100)])


@pytest.mark.anyio
async def test_run_code_truncates_output():
    tool = run_code(
        executor=LargeOutputRunCodeExecutor(),
        max_output_chars=50,
    )

    result = await tool(code="large")

    assert len(result[0].text) <= 50
    assert "truncated" in result[0].text


@pytest.mark.anyio
async def test_run_code_does_not_truncate_output_by_default():
    long_text = "x" * 25_000

    class LongOutputExecutor:
        async def execute(self, code: str) -> RunCodeResult:
            return RunCodeResult(output=[ContentText(text=long_text)])

    tool = run_code(executor=LongOutputExecutor())

    result = await tool(code="ignored")

    assert result == [ContentText(text=long_text)]


def test_truncate_content_preserves_trailing_image():
    content = [
        ContentText(text="x" * 100),
        ContentImage(image="data:image/png;base64,AAAA"),
    ]

    result = _truncate_content(content, max_chars=10)

    assert any(isinstance(item, ContentImage) for item in result)


def test_truncate_content_stays_within_limit_across_text_blocks():
    content = [ContentText(text="a" * 30), ContentText(text="b" * 30)]

    result = _truncate_content(content, max_chars=30)

    total = sum(len(item.text) for item in result if isinstance(item, ContentText))
    assert total <= 30


def test_truncate_content_handles_max_chars_below_suffix():
    result = _truncate_content([ContentText(text="a" * 100)], max_chars=5)

    total = sum(len(item.text) for item in result if isinstance(item, ContentText))
    assert total <= 5


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

    assert len(bridge.call_trace) == 2
    assert bridge.call_trace[0].name == "dummy_tool"
    assert bridge.call_trace[1].name == "second_dummy_tool"


@pytest.mark.anyio
async def test_run_code_can_call_multiple_wrapped_tools_with_monty():
    pytest.importorskip("pydantic_monty")

    tool = run_code(
        tools=[dummy_tool(), second_dummy_tool()],
        executor="monty",
    )

    result = await tool(
        code="""
a = await dummy_tool("x")
b = await second_dummy_tool("y")
[a, b]
"""
    )

    assert "x" in result[0].text
    assert "second:y" in result[0].text


def add_numbers_tool() -> Tool:
    async def execute(a: int, b: int) -> int:
        """Add two integers.

        Args:
            a: First integer.
            b: Second integer.
        """
        return a + b

    return ToolDef(
        execute,
        name="add_numbers",
        description="Add two integers.",
    ).as_tool()


@pytest.mark.anyio
async def test_external_functions_preserve_scalar_return_type():
    bridge = RunCodeToolBridge(_tool_defs([add_numbers_tool()]))
    external_functions = bridge.external_functions()

    result = await external_functions["add_numbers"](2, 3)

    assert result == 5
    assert isinstance(result, int)


@pytest.mark.anyio
async def test_run_code_chains_typed_tool_results_with_monty():
    pytest.importorskip("pydantic_monty")

    # the first result feeds the second call; the int must survive the
    # Monty boundary so the second call validates against the int schema
    tool = run_code(tools=[add_numbers_tool()], executor="monty")

    result = await tool(
        code="""
x = await add_numbers(a=1, b=2)
await add_numbers(a=x, b=40)
"""
    )

    assert result[0].text == "43"


def list_channels_tool() -> Tool:
    async def execute() -> list:
        """List channel names.

        Returns:
            Channel names.
        """
        return ["general", "random", "engineering"]

    return ToolDef(
        execute, name="list_channels", description="List channels."
    ).as_tool()


def transactions_tool() -> Tool:
    async def execute() -> list:
        """List transactions.

        Returns:
            Transactions.
        """
        return [{"id": 1, "amount": 10}, {"id": 2, "amount": 32}]

    return ToolDef(
        execute, name="get_transactions", description="List transactions."
    ).as_tool()


@pytest.mark.anyio
async def test_external_functions_preserve_structured_return_type():
    bridge = RunCodeToolBridge(_tool_defs([list_channels_tool()]))
    external_functions = bridge.external_functions()

    result = await external_functions["list_channels"]()

    assert result == ["general", "random", "engineering"]
    assert isinstance(result, list)


@pytest.mark.anyio
async def test_run_code_iterates_structured_tool_result_with_monty():
    pytest.importorskip("pydantic_monty")

    tool = run_code(tools=[transactions_tool()], executor="monty")

    result = await tool(
        code="""
txs = await get_transactions()
total = sum(t["amount"] for t in txs)
f"{len(txs)} txs total={total}"
"""
    )

    assert result[0].text == "2 txs total=42"


def test_project_result_raises_on_unprojectable_value():
    # Neither scalar, Content, nor JSON-serializable: raise instead of
    # degrading to text, and leave artifacts untouched.
    bridge = RunCodeToolBridge([])
    circular: dict = {}
    circular["self"] = circular

    with pytest.raises(ToolError):
        bridge._project_result(circular, "demo_tool")

    assert bridge.artifacts == []


@pytest.mark.anyio
async def test_run_code_can_call_wrapped_tools_with_asyncio_gather():
    pytest.importorskip("pydantic_monty")

    tool = run_code(
        tools=[dummy_tool(), second_dummy_tool()],
        executor="monty",
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

    assert "x" in result[0].text
    assert "second:y" in result[0].text
    assert "Inner tool calls:" in result[1].text
    assert "dummy_tool" in result[1].text
    assert "second_dummy_tool" in result[1].text


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
    assert "approval: Automatic decision." in result


@pytest.mark.anyio
async def test_run_code_monty_uses_inspect_approval_for_inner_tool_calls():
    pytest.importorskip("pydantic_monty")

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

    tool = run_code(
        tools=[approval_probe_tool()],
        executor="monty",
    )

    with approval(
        [
            ApprovalPolicy(
                approver=auto_approver(decision="reject"),
                tools="approval_probe_tool",
            )
        ]
    ):
        result = await tool(code='await approval_probe_tool("secret")')

    assert calls == []
    assert isinstance(result, list)
    assert result[0].text == "approval: Automatic decision."


@pytest.mark.anyio
async def test_run_code_monty_runs_inner_tool_when_approval_allows_it():
    pytest.importorskip("pydantic_monty")

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

    tool = run_code(
        tools=[approval_probe_tool()],
        executor="monty",
    )

    with approval(
        [
            ApprovalPolicy(
                approver=auto_approver(decision="approve"),
                tools="approval_probe_tool",
            )
        ]
    ):
        result = await tool(code='await approval_probe_tool("secret")')

    assert calls == ["secret"]
    assert result[0].text == "approved:secret"


def image_tool() -> Tool:
    async def execute() -> list[Content]:
        """Return an image.

        Returns:
            Image content.
        """
        return [
            ContentText(text="here is your image"),
            ContentImage(image="data:image/png;base64,abc123"),
        ]

    return ToolDef(
        execute,
        name="image_tool",
        description="Return an image.",
    ).as_tool()


@pytest.mark.anyio
async def test_run_code_bridge_collects_image_artifacts():
    bridge = RunCodeToolBridge(_tool_defs([image_tool()]))
    external_functions = bridge.external_functions()

    result = await external_functions["image_tool"]()

    assert result == "here is your image"

    assert len(bridge.artifacts) == 1
    assert isinstance(bridge.artifacts[0], ContentImage)
    assert bridge.artifacts[0].image == "data:image/png;base64,abc123"


@pytest.mark.anyio
async def test_run_code_artifacts_appear_in_result():
    pytest.importorskip("pydantic_monty")
    tool = run_code(tools=[image_tool()], executor="monty")

    result = await tool(code="await image_tool()")

    assert any(
        isinstance(item, ContentText) and "here is your image" in item.text
        for item in result
    )

    assert any(isinstance(item, ContentImage) for item in result)


@pytest.mark.anyio
async def test_run_code_bridge_propagates_terminate_sample_error():
    bridge = RunCodeToolBridge(_tool_defs([dummy_tool()]))
    external_functions = bridge.external_functions()

    with approval(
        [
            ApprovalPolicy(
                approver=auto_approver(decision="terminate"),
                tools="dummy_tool",
            )
        ]
    ):
        with pytest.raises(TerminateSampleError):
            await external_functions["dummy_tool"]("secret")


def file_not_found_tool() -> Tool:
    async def execute(path: str) -> str:
        """Raise FileNotFoundError.

        Args:
            path: Path to open.
        """
        raise FileNotFoundError(2, "No such file or directory", path)

    return ToolDef(
        execute,
        name="file_not_found_tool",
        description="Always raises FileNotFoundError.",
    ).as_tool()


@pytest.mark.anyio
async def test_run_code_bridge_converts_recoverable_tool_errors():
    bridge = RunCodeToolBridge(_tool_defs([file_not_found_tool()]))
    external_functions = bridge.external_functions()

    result = await external_functions["file_not_found_tool"]("missing.txt")

    assert isinstance(result, str)
    assert "file_not_found:" in result
    assert "missing.txt" in result


@pytest.mark.anyio
async def test_run_code_bridge_raises_custom_error_on_max_tool_calls():
    bridge = RunCodeToolBridge(
        _tool_defs([dummy_tool()]),
        max_inner_tool_calls=1,
    )
    external_functions = bridge.external_functions()

    await external_functions["dummy_tool"]("first")

    with pytest.raises(RunCodeMaxToolCallsExceededError) as exc_info:
        await external_functions["dummy_tool"]("second")

    assert exc_info.value.max_tool_calls == 1
    assert "Maximum run_code inner tool calls exceeded: 1" in str(exc_info.value)
