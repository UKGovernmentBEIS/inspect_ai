from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from inspect_ai._util.content import Content, ContentText
from inspect_ai.tool import ToolDef

from ._bridge import RunCodeInnerToolCall, RunCodeToolBridge


@dataclass
class RunCodeResult:
    """Result of a run_code execution."""

    output: list[Content]
    error: str | None = None
    inner_tool_calls: list[RunCodeInnerToolCall] = field(default_factory=list)


class RunCodeExecutor(Protocol):
    """Executor for run_code."""

    async def execute(self, code: str) -> RunCodeResult:
        """Execute code.

        Args:
            code: Python code to execute.

        Returns:
            Result of the code execution.
        """
        ...


class StubRunCodeExecutor:
    """Placeholder executor used until real code execution is implemented."""

    async def execute(self, code: str) -> RunCodeResult:
        """Execute code.

        Args:
            code: Python code to execute.

        Returns:
            Placeholder execution result.
        """
        return RunCodeResult(
            output=[ContentText(text="run_code execution is not implemented yet")]
        )


class MontyRunCodeExecutor:
    """Run code using Pydantic Monty."""

    def __init__(
        self,
        tool_defs: list[ToolDef] | None = None,
        *,
        max_inner_tool_calls: int | None = None,
    ) -> None:
        self.tool_defs = tool_defs or []
        self.max_tool_calls = max_inner_tool_calls

    async def execute(self, code: str) -> RunCodeResult:
        """Execute code.

        Args:
            code: Python code to execute.

        Returns:
            Result of the code execution.
        """
        try:
            import pydantic_monty
        except ImportError:
            return RunCodeResult(
                output=[],
                error=(
                    "pydantic-monty is not installed. "
                    "Install inspect-ai[code-mode] to use run_code execution."
                ),
            )

        bridge = RunCodeToolBridge(
            self.tool_defs,
            max_inner_tool_calls=self.max_tool_calls,
        )

        try:
            monty = pydantic_monty.Monty(
                code,
                script_name="run_code.py",
                type_check=False,
            )
            output = await monty.run_async(
                external_functions=bridge.external_functions(),
            )

            contents: list[Content] = []

            if output:
                contents.append(ContentText(text=str(output)))

            contents.extend(bridge.artifacts)

            return RunCodeResult(
                output=contents,
                inner_tool_calls=bridge.calls,
            )
        except Exception as exc:
            return RunCodeResult(
                output=[],
                error=str(exc),
                inner_tool_calls=bridge.calls,
            )
