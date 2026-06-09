from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class RunCodeResult:
    """Result of a run_code execution."""

    output: str
    error: str | None = None


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
            output="run_code execution is not implemented yet",
        )
class MontyRunCodeExecutor:
    """Run code using Pydantic Monty.

    This executor does not expose inner Inspect tools yet.
    """

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
                output="",
                error=(
                    "pydantic-monty is not installed. "
                    "Install it to use run_code execution."
                ),
            )

        try:
            monty = pydantic_monty.Monty(
                code,
                script_name="run_code.py",
                type_check=False,
            )
            output = await monty.run_async()
            return RunCodeResult(output=str(output))
        except Exception as exc:
            return RunCodeResult(output="", error=str(exc))
