from pathlib import Path

from inspect_ai._util.text import truncate_string_to_bytes
from inspect_ai.util._subprocess import ExecResult


class SandboxEnvironmentLimits:
    """Encapsulates limits for sandbox environments."""

    MAX_EXEC_OUTPUT_SIZE = 1024**2
    MAX_EXEC_OUTPUT_SIZE_STR = "1 MiB"

    MAX_READ_FILE_SIZE = 100 * 1024**2
    MAX_READ_FILE_SIZE_STR = "100 MiB"


class OutputLimitExceededError(Exception):
    """Exception raised when a sandbox invocation results in excessive output."""

    def __init__(self, limit_str: str, truncated_output: str | None) -> None:
        self.limit_str = limit_str
        self.truncated_output = truncated_output
        super().__init__(
            f"The sandbox output stream limit of {self.limit_str} was exceeded."
        )


def verify_exec_result_size(exec_result: ExecResult[str]) -> None:
    """Verify the size of the output streams in an `ExecResult`.

    Raises:
      OutputLimitExceededError: If an output stream exceeds the 1 MiB limit.
    """
    limit = SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE
    stdout_truncated = truncate_string_to_bytes(exec_result.stdout, limit)
    stderr_truncated = truncate_string_to_bytes(exec_result.stderr, limit)
    if not stdout_truncated and not stderr_truncated:
        return
    stdout = stdout_truncated.output if stdout_truncated else exec_result.stdout
    stderr = stderr_truncated.output if stderr_truncated else exec_result.stderr
    raise OutputLimitExceededError(
        limit_str=SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE_STR,
        truncated_output=f"{stdout}{stderr}",
    )


def verify_read_file_size(file: str) -> None:
    """Verify the size of a file to be read into memory.

    Raises:
      OutputLimitExceededError: If the file size exceeds the 100 MiB limit.
    """
    file_size = Path(file).stat().st_size
    if file_size > SandboxEnvironmentLimits.MAX_READ_FILE_SIZE:
        raise OutputLimitExceededError(
            limit_str=SandboxEnvironmentLimits.MAX_READ_FILE_SIZE_STR,
            # The potentially large, and potentially binary content is not included.
            truncated_output=None,
        )
