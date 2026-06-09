from inspect_ai.tool import Tool, ToolDef, tool
from collections.abc import Sequence
from ._run_code_executor import RunCodeExecutor, RunCodeResult, StubRunCodeExecutor, MontyRunCodeExecutor
import asyncio

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

def _format_run_code_result(
    result: RunCodeResult,
    *,
    include_tool_call_trace: bool,
) -> str:
    """Format a run_code result for the model."""
    output = result.error if result.error else result.output

    if not include_tool_call_trace or not result.inner_tool_calls:
        return output

    lines = [output, "", "Inner tool calls:"]

    for call in result.inner_tool_calls:
        status = "error" if call.error else "ok"
        lines.append(f"- {call.name}: {status}")
        if call.error:
            lines.append(f"  error: {call.error}")

    return "\n".join(lines)

def _truncate_text(text: str, max_chars: int | None) -> str:
    """Truncate text to a maximum number of characters."""
    if max_chars is None or len(text) <= max_chars:
        return text

    suffix = f"\n\n[run_code output truncated to {max_chars} characters]"
    if max_chars <= len(suffix):
        return text[:max_chars]

    return text[: max_chars - len(suffix)] + suffix

def _tool_interface_description(tool_defs: list[ToolDef]) -> str:
    """Describe the tools that will eventually be callable from run_code."""
    if not tool_defs:
        return (
            "No inner tools are currently available. "
            "The code can only use the Python execution environment."
        )

    lines = [
        "The code may call the following allowlisted Inspect tools as async functions. Use `await` when calling them:"
        "",
    ]

    for tool_def in tool_defs:
        lines.append(
            f"- `{_tool_signature(tool_def)}`: {tool_def.description}"
        )

    return "\n".join(lines)

@tool
def run_code(
    tools: Sequence[Tool] | None = None,
    timeout: int | None = None,
    executor: RunCodeExecutor | None = None,
    execute: bool = False,
    max_tool_calls: int | None = None,
    include_tool_call_trace: bool = False,
    max_output_chars: int | None = 20_000,
) -> Tool:
    """Run Python code that can orchestrate selected tools.

    Args:
        tools: Tools that code executed by run_code may eventually call.
        timeout: Maximum execution time in seconds.
    """

    tool_defs = _tool_defs(tools)
    inner_tools_description = _tool_interface_description(tool_defs)
    executor = executor or (
        MontyRunCodeExecutor(
            tool_defs=tool_defs,
            max_tool_calls=max_tool_calls,
        )
        if execute
        else StubRunCodeExecutor()
    )

    async def execute(code: str) -> str:
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
            return f"run_code execution timed out after {timeout} seconds."

        formatted = _format_run_code_result(
            result,
            include_tool_call_trace=include_tool_call_trace,
        )

        return _truncate_text(formatted, max_output_chars)

    return ToolDef(
        execute,
        name="run_code",
        description=(
            "Run Python code that can orchestrate selected tools.\n\n"
            f"{inner_tools_description}\n\n"
            "This placeholder does not execute code yet."
        ),
    ).as_tool()
