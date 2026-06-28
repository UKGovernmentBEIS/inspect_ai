import asyncio
from collections.abc import Sequence
from typing import Literal

from inspect_ai._util.content import (
    Content,
    ContentText,
)
from inspect_ai.tool import Tool, ToolDef, tool

from ._run_code_executor import (
    MontyRunCodeExecutor,
    RunCodeExecutor,
    RunCodeResult,
    StubRunCodeExecutor,
)


def _tool_defs(tools: Sequence[Tool] | None) -> list[ToolDef]:
    """Convert allowed tools into ToolDef objects."""
    return [ToolDef(tool) for tool in tools or []]


def _tool_signature(tool_def: ToolDef) -> str:
    """Return a compact signature for an allowlisted tool."""
    parameters = tool_def.parameters
    if parameters is None or parameters.properties is None:
        return f"{tool_def.name}()"

    args: list[str] = []
    required = set(parameters.required or [])

    for name, schema in parameters.properties.items():
        typ = schema.type or "any"
        optional = "" if name in required else " | None"
        args.append(f"{name}: {typ}{optional}")

    return f"await {tool_def.name}({', '.join(args)})"


def _resolve_executor(
    executor: RunCodeExecutor | Literal["monty", "stub"],
    *,
    tool_defs: list[ToolDef],
    max_inner_tool_calls: int | None,
) -> RunCodeExecutor:
    """Resolve a run_code executor name or custom executor."""
    if isinstance(executor, str):
        if executor == "monty":
            return MontyRunCodeExecutor(
                tool_defs=tool_defs,
                max_inner_tool_calls=max_inner_tool_calls,
            )
        if executor == "stub":
            return StubRunCodeExecutor()
        raise ValueError(f"Unknown run_code executor: {executor}")

    return executor


def _format_run_code_result(
    result: RunCodeResult,
    *,
    include_tool_call_trace: bool,
) -> list[Content]:
    """Format a run_code result for the model."""
    output = result.error if result.error else result.output

    content: list[Content] = (
        [ContentText(text=output)] if isinstance(output, str) else list(output)
    )

    if not include_tool_call_trace or not result.inner_tool_call_trace:
        return content

    trace_lines = ["", "Inner tool calls:"]
    for trace_entry in result.inner_tool_call_trace:
        status = "error" if trace_entry.error else "ok"
        trace_lines.append(f"- {trace_entry.name}: {status}")

        if trace_entry.args_preview != "()":
            trace_lines.append(f"  args: {trace_entry.args_preview}")
        if trace_entry.kwargs_preview != "{}":
            trace_lines.append(f"  kwargs: {trace_entry.kwargs_preview}")

        if trace_entry.error:
            trace_lines.append(f"  error: {trace_entry.error}")
        elif trace_entry.result_preview is not None:
            trace_lines.append(f"  result: {trace_entry.result_preview}")

    content.append(ContentText(text="\n".join(trace_lines)))
    return content


def _truncate_content(content: list[Content], max_chars: int | None) -> list[Content]:
    if max_chars is None:
        return content
    result: list[Content] = []
    remaining = max_chars
    for item in content:
        if not isinstance(item, ContentText):
            result.append(item)
            continue
        if remaining <= 0:
            continue
        if len(item.text) <= remaining:
            result.append(item)
            remaining -= len(item.text)
            continue
        suffix = f"... [truncated to {max_chars} chars]"
        if remaining > len(suffix):
            text = item.text[: remaining - len(suffix)] + suffix
        else:
            text = item.text[:remaining]
        result.append(ContentText(text=text))
        remaining = 0
    return result


def _tool_interface_description(tool_defs: list[ToolDef]) -> str:
    """Describe the tools that will eventually be callable from run_code."""
    if not tool_defs:
        return (
            "No inner tools are currently available. "
            "The code can only use the Python execution environment."
        )

    lines = [
        "The code may call the following allowlisted Inspect tools as async functions.",
        "Use `await` when calling them:",
        "",
    ]

    for tool_def in tool_defs:
        lines.append(f"- `{_tool_signature(tool_def)}`: {tool_def.description}")

    return "\n".join(lines)


def _tool_def_by_name(tool_defs: list[ToolDef]) -> dict[str, ToolDef]:
    """Return tool definitions indexed by name.

    Raises:
        ValueError: If more than one allowlisted tool has the same name.
    """
    tool_def_by_name: dict[str, ToolDef] = {}

    for tool_def in tool_defs:
        if tool_def.name in tool_def_by_name:
            raise ValueError(f"Duplicate run_code inner tool name: {tool_def.name}")
        tool_def_by_name[tool_def.name] = tool_def

    return tool_def_by_name


def _run_code_usage_description(tool_defs: list[ToolDef]) -> str:
    """Return model-facing instructions for using run_code."""
    lines = [
        "Write Python code to solve the task.",
        "The code is executed by Pydantic Monty, which supports only a restricted Python subset. Do not define classes.",
        "Use ordinary functions, variables, loops, conditionals, comprehensions, and async/await.",
        "Only a limited set of standard-library imports is available, such as asyncio, json, re, math, and datetime. Tool calls must be awaited.",
        "The final expression is returned as the run_code result.",
        "",
    ]

    if tool_defs:
        lines.extend(
            [
                "You may call the allowlisted tools listed below, but ONLY from within the Python code passed to run_code.",
                "Do NOT call them directly as regular tools — they are only available inside the Python execution environment.",
                "",
                "Use `await` when calling these tools, or `asyncio.gather(...)` to run multiple calls concurrently.",
                "",
                "Example:",
                "```python",
                "import asyncio",
                "",
                "results = await asyncio.gather(",
                '    tool_name(arg="value"),',
                '    another_tool(arg="value"),',
                ")",
                "results",
                "```",
                "",
                _tool_interface_description(tool_defs),
            ]
        )
    else:
        lines.extend(
            [
                "No inner Inspect tools are available.",
                "The code can only use the Python execution environment.",
            ]
        )

    return "\n".join(lines)


@tool
def run_code(
    tools: Sequence[Tool] | None = None,
    timeout: int | None = None,
    executor: RunCodeExecutor | Literal["monty", "stub"] = "stub",
    max_inner_tool_calls: int | None = None,
    include_tool_call_trace: bool = False,
    max_output_chars: int | None = 20_000,
) -> Tool:
    """Run Python code that can orchestrate selected tools.

    Args:
        tools: Tools that code executed by run_code may call.
        timeout: Maximum execution time in seconds.
        executor: Executor used to run code. Use "stub" for the placeholder executor,
            "monty" for the Pydantic Monty-backed executor, or pass a custom
            RunCodeExecutor for tests / alternative backends.
        max_inner_tool_calls: Maximum number of allowlisted tool calls from inside run_code.
        include_tool_call_trace: Whether to include a compact trace of inner tool calls in the result.
        max_output_chars: Maximum number of characters returned by run_code.
    """
    tool_defs = _tool_defs(tools)
    tool_def_by_name = _tool_def_by_name(tool_defs)
    tool_defs = list(tool_def_by_name.values())
    usage_description = _run_code_usage_description(tool_defs)
    executor = _resolve_executor(
        executor,
        tool_defs=tool_defs,
        max_inner_tool_calls=max_inner_tool_calls,
    )

    async def execute(code: str) -> list[Content]:
        """Run Python code.

        Args:
            code: Python code to execute.
        """
        try:
            if timeout is None:
                result = await executor.execute(code)
            else:
                result = await asyncio.wait_for(
                    executor.execute(code),
                    timeout=timeout,
                )
        except asyncio.TimeoutError:
            return [
                ContentText(
                    text=f"run_code execution timed out after {timeout} seconds."
                )
            ]

        formatted = _format_run_code_result(
            result,
            include_tool_call_trace=include_tool_call_trace,
        )

        return _truncate_content(formatted, max_output_chars)

    return ToolDef(
        execute,
        name="run_code",
        description=(
            "Run Python code that can orchestrate selected tools.\n\n"
            f"{usage_description}"
        ),
    ).as_tool()
