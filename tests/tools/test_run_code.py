import sys

import anyio
import pytest

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup
else:
    from builtins import BaseExceptionGroup

from inspect_ai import Task, eval
from inspect_ai.approval import ApprovalPolicy, auto_approver
from inspect_ai.dataset import Sample
from inspect_ai.event import SpanBeginEvent, ToolEvent
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import (
    ContentImage,
    Tool,
    ToolCallContent,
    ToolCallView,
    ToolDef,
    ToolError,
    run_code,
    tool,
)


@tool
def add() -> Tool:
    async def execute(x: int, y: int) -> int:
        """Add two numbers.

        Args:
            x: First number.
            y: Second number.
        """
        return x + y

    return execute


async def test_run_code_calls_serial_tool() -> None:
    result = await run_code([add()])("value = await add(x=2, y=3)\nvalue * 2")

    assert result == 10


async def test_run_code_calls_parallel_tools_concurrently() -> None:
    entered = 0
    both_entered = anyio.Event()

    @tool(parallel=True)
    def probe() -> Tool:
        async def execute(value: int) -> int:
            """Return a value after both calls have started.

            Args:
                value: Value to return.
            """
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await both_entered.wait()
            return value

        return execute

    with anyio.fail_after(2):
        result = await run_code([probe()])(
            "import asyncio\n"
            "values = await asyncio.gather(probe(value=1), probe(value=2))\n"
            "values"
        )

    assert result == "[1,2]"
    assert entered == 2


async def test_run_code_serial_tools_remain_barriers() -> None:
    active = 0
    max_active = 0

    @tool
    def serial_probe() -> Tool:
        async def execute(value: int) -> int:
            """Return a value after a short serial operation.

            Args:
                value: Value to return.
            """
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await anyio.sleep(0.02)
            active -= 1
            return value

        return execute

    result = await run_code([serial_probe()])(
        "import asyncio\n"
        "values = await asyncio.gather("
        "serial_probe(value=1), serial_probe(value=2))\n"
        "values"
    )

    assert result == "[1,2]"
    assert max_active == 1


async def test_run_code_enforces_nested_call_limit() -> None:
    code = "first = await add(x=1, y=1)\nsecond = await add(x=2, y=2)\nsecond"

    with pytest.raises(ToolError, match="at most 1 wrapped-tool"):
        await run_code([add()], max_tool_calls=1)(code)


async def test_run_code_enforces_monty_duration_limit() -> None:
    with pytest.raises(ToolError, match="time limit exceeded"):
        await run_code([add()], max_duration_secs=0.05)("while True:\n    pass")


async def test_run_code_monty_execution_does_not_block_anyio() -> None:
    started_at = anyio.current_time()

    async def execute_cpu_loop() -> None:
        with pytest.raises(ToolError, match="time limit exceeded"):
            await run_code([add()], max_duration_secs=0.2)("while True:\n    pass")

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(execute_cpu_loop)
        await anyio.sleep(0.03)
        ticked_after = anyio.current_time() - started_at

    assert ticked_after < 0.15


async def test_run_code_cancels_cpu_bound_monty_execution_promptly() -> None:
    started_at = anyio.current_time()

    async def execute_cpu_loop() -> None:
        await run_code([add()], max_duration_secs=30)("while True:\n    pass")

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(execute_cpu_loop)
        await anyio.sleep(0.05)
        task_group.cancel_scope.cancel()

    assert anyio.current_time() - started_at < 1


async def test_run_code_has_no_host_filesystem_access() -> None:
    with pytest.raises(ToolError, match="Permission denied"):
        await run_code([add()])(
            "from pathlib import Path\nPath('blocked.txt').write_text('nope')"
        )


async def test_run_code_delivers_tool_errors_at_call_site() -> None:
    @tool
    def unreliable() -> Tool:
        async def execute() -> str:
            """Fail recoverably."""
            raise ToolError("expected failure")

        return execute

    result = await run_code([unreliable()])(
        "try:\n"
        "    await unreliable()\n"
        "except RuntimeError as ex:\n"
        "    message = str(ex)\n"
        "message"
    )

    assert result == "expected failure"


async def test_run_code_preserves_fatal_tool_errors() -> None:
    @tool
    def broken() -> Tool:
        async def execute() -> str:
            """Fail fatally."""
            raise ValueError("fatal failure")

        return execute

    with pytest.raises(ValueError, match="fatal failure"):
        await run_code([broken()])("await broken()")

    from inspect_ai.log._transcript import transcript

    inner_event = next(
        event
        for event in reversed(transcript().events)
        if isinstance(event, ToolEvent) and event.function == "broken"
    )
    assert inner_event.error is None
    assert inner_event.failed is True


async def test_run_code_fatal_parallel_error_cancels_siblings() -> None:
    sibling_started = anyio.Event()
    sibling_cancelled = anyio.Event()

    @tool(parallel=True)
    def broken_parallel() -> Tool:
        async def execute() -> str:
            """Fail after the sibling starts."""
            await sibling_started.wait()
            raise ValueError("parallel fatal failure")

        return execute

    @tool(parallel=True)
    def blocked_parallel() -> Tool:
        async def execute() -> str:
            """Wait forever until a sibling fails."""
            sibling_started.set()
            try:
                await anyio.sleep_forever()
            finally:
                sibling_cancelled.set()
            raise AssertionError("unreachable")

        return execute

    with anyio.fail_after(2):
        with pytest.raises(ValueError, match="parallel fatal failure"):
            await run_code([broken_parallel(), blocked_parallel()])(
                "import asyncio\n"
                "await asyncio.gather(broken_parallel(), blocked_parallel())"
            )

    assert sibling_cancelled.is_set()


async def test_run_code_cancellation_cleans_up_inner_calls() -> None:
    started = anyio.Event()
    cleaned_up = anyio.Event()

    @tool(parallel=True)
    def wait_forever() -> Tool:
        async def execute() -> str:
            """Wait until cancelled."""
            started.set()
            try:
                await anyio.sleep_forever()
            finally:
                cleaned_up.set()
            raise AssertionError("unreachable")

        return execute

    async def invoke() -> None:
        await run_code([wait_forever()])("await wait_forever()")

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(invoke)
        await started.wait()
        task_group.cancel_scope.cancel()

    assert cleaned_up.is_set()


async def test_run_code_inner_tool_supports_operator_cancellation() -> None:
    from inspect_ai.log._transcript import transcript

    @tool
    def cancellable() -> Tool:
        async def execute() -> str:
            """Cancel this wrapped tool call."""
            inner_event = next(
                event
                for event in reversed(transcript().events)
                if isinstance(event, ToolEvent)
                and event.function == "cancellable"
                and event.pending
            )
            inner_event._cancel()
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

        return execute

    result = await run_code([cancellable()])(
        "try:\n"
        "    await cancellable()\n"
        "except RuntimeError as ex:\n"
        "    message = str(ex)\n"
        "message"
    )

    assert result == "Command timed out before completing."
    inner_event = next(
        event
        for event in reversed(transcript().events)
        if isinstance(event, ToolEvent) and event.function == "cancellable"
    )
    assert inner_event.cancelled
    assert inner_event.error is not None
    assert inner_event.error.type == "timeout"


async def test_run_code_round_trips_content_results() -> None:
    @tool
    def image() -> Tool:
        async def execute() -> ContentImage:
            """Return an image."""
            return ContentImage(image="data:image/png;base64,AAAA")

        return execute

    result = await run_code([image()])("await image()")

    assert isinstance(result, ContentImage)
    assert result.image == "data:image/png;base64,AAAA"


async def test_run_code_preserves_wrapped_tool_output_limits() -> None:
    @tool(max_output=8)
    def long_output() -> Tool:
        async def execute() -> str:
            """Return more text than the declared output limit."""
            return "x" * 100

        return execute

    result = await run_code([long_output()])("await long_output()")

    assert isinstance(result, str)
    assert "truncated version" in result
    assert "xxxxxxxx" in result
    assert "x" * 9 not in result


async def test_run_code_applies_wrapped_tool_output_limits_to_scalars() -> None:
    @tool(max_output=8)
    def large_number() -> Tool:
        async def execute() -> int:
            """Return a number longer than the declared output limit."""
            return 123456789012

        return execute

    result = await run_code([large_number()])("await large_number()")

    assert isinstance(result, str)
    assert "truncated version" in result
    assert "12349012" in result
    assert "123456789012" not in result


def test_run_code_description_includes_tools_and_limits() -> None:
    run_code_def = ToolDef(run_code([add()], max_tool_calls=7))

    assert run_code_def.name == "run_code"
    assert "`async def add(*, x: int, y: int) -> int: ...`" in run_code_def.description
    assert "At most 7 wrapped-tool calls" in run_code_def.description
    assert "fresh interpreter state" in run_code_def.description


async def test_run_code_sanitizes_wrapped_tool_names() -> None:
    renamed = ToolDef(add(), name="math-add")

    result = await run_code([renamed])("await math_add(x=20, y=22)")

    assert result == 42
    assert "Inspect tool `math-add`" in ToolDef(run_code([renamed])).description


def test_run_code_rejects_sanitized_name_collisions() -> None:
    with pytest.raises(ValueError, match="both map to Python identifier"):
        run_code(
            [
                ToolDef(add(), name="math-add"),
                ToolDef(add(), name="math_add"),
            ]
        )


@pytest.mark.parametrize("name", ["len", "open", "print"])
def test_run_code_rejects_monty_builtin_name_collisions(name: str) -> None:
    with pytest.raises(ValueError, match="reserved Python name"):
        run_code([ToolDef(add(), name=name)])


async def test_run_code_type_checks_wrapped_tool_calls() -> None:
    with pytest.raises(ToolError, match="Type error in code"):
        await run_code([add()])("await add(x='not an integer', y=2)")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("b'abc'", "abc"),
        ("{1, 2}", [1, 2]),
        (
            "import datetime\ndatetime.datetime(2020, 1, 2, 3, 4, 5)",
            "2020-01-02T03:04:05",
        ),
    ],
)
async def test_run_code_serializes_supported_final_values(
    code: str, expected: object
) -> None:
    import json

    result = await run_code([add()])(code)

    assert isinstance(result, str)
    assert json.loads(result) == expected


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_tool_calls": 0}, "max_tool_calls"),
        ({"max_duration_secs": 0}, "max_duration_secs"),
        ({"max_memory": 0}, "max_memory"),
    ],
)
def test_run_code_rejects_invalid_limits(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        run_code([add()], **kwargs)


def test_run_code_records_inner_tool_events_under_outer_span() -> None:
    def viewer(call: object) -> ToolCallView:
        return ToolCallView(
            call=ToolCallContent(title="Nested add", format="text", content=str(call))
        )

    viewed_add = ToolDef(add(), viewer=viewer)
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                "run_code",
                {"code": "await add(x=20, y=22)"},
            ),
            ModelOutput.from_content("mockllm/model", "42"),
        ],
        memoize=False,
    )
    task = Task(
        dataset=[Sample(input="Add the values")],
        solver=[use_tools(run_code([viewed_add])), generate()],
    )

    log = eval(task, model=model)[0]

    assert log.samples
    events = log.samples[0].events
    run_code_span = next(
        event
        for event in events
        if isinstance(event, SpanBeginEvent) and event.name == "run_code"
    )
    inner_event = next(
        event
        for event in events
        if isinstance(event, ToolEvent) and event.function == "add"
    )
    assert inner_event.result == "42"
    assert inner_event.view is not None
    assert inner_event.view.title == "Nested add"
    assert inner_event.span_id == run_code_span.id


def test_run_code_applies_inner_tool_approval() -> None:
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                "run_code",
                {"code": "await add(x=20, y=22)"},
            ),
            ModelOutput.from_content("mockllm/model", "The call was denied."),
        ],
        memoize=False,
    )
    task = Task(
        dataset=[Sample(input="Add the values")],
        solver=[use_tools(run_code([add()])), generate()],
        approval=[
            ApprovalPolicy(auto_approver("approve"), tools="run_code"),
            ApprovalPolicy(auto_approver("reject"), tools="add"),
        ],
    )

    log = eval(task, model=model)[0]

    assert log.samples
    inner_event = next(
        event
        for event in log.samples[0].events
        if isinstance(event, ToolEvent) and event.function == "add"
    )
    assert inner_event.error is not None
    assert inner_event.error.type == "approval"


async def test_run_code_detects_panics_inside_exception_groups() -> None:
    from inspect_ai.tool._tools._run_code_monty import _is_sandbox_panic

    class PanicException(BaseException):
        pass

    panic = BaseExceptionGroup("task group", [PanicException("boom")])

    assert _is_sandbox_panic(panic)
