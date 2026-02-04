import re

from ..._util.exec_any.process import Process as ExecAnyProcess
from .tool_types import InteractResult


class Process:
    @classmethod
    async def create(cls) -> "Process":
        return cls(
            await ExecAnyProcess.create(
                cmd=["/bin/bash", "-i"],
                env={"TERM": "dumb"},
                cwd=None,
            )
        )

    def __init__(self, process: ExecAnyProcess) -> None:
        self._process = process

    async def interact(
        self, input_text: str | None, wait_for_output: int, idle_timeout: float
    ) -> InteractResult:
        raw_stdout, raw_stderr = await self._process.interact(
            input_text, wait_for_output, idle_timeout
        )
        raw_output = raw_stdout
        if raw_stderr and raw_stderr != "":
            raw_output += "\n"  + raw_stderr

        # This isn't 100% correct. Just like the stream chunks could split a
        # utf-8 character, it could also split these control sequences. The
        # downside is just that a control sequence could be left in the output.
        return strip_control_characters(raw_output)

    async def terminate(self, timeout: int = 30) -> None:
        await self._process.terminate(timeout)


# Pattern matches most ANSI escape sequences and control characters
ansi_escape_pattern = re.compile(
    r"""
    \x1B  # ESC character
    (?:   # followed by...
        [@-Z\\-_]| # single character controls
        \[[0-9;]*[A-Za-z]| # CSI sequences like colors
        \]8;.*;| # OSC hyperlink sequences
        \([AB012]| # Select character set
        \[[0-9]+(?:;[0-9]+)*m # SGR sequences (colors, etc)
    )
""",
    re.VERBOSE,
)


def strip_control_characters(text: str) -> str:
    """Remove ANSI escape sequences and other control characters from text."""
    # Remove the ANSI escape sequences
    clean_text = ansi_escape_pattern.sub("", text)

    # Additionally remove other control characters except newlines and tabs
    clean_text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", clean_text)

    return clean_text
