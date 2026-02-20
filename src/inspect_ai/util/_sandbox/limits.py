from pathlib import Path


class SandboxEnvironmentLimits:
    """Encapsulates limits for sandbox environments."""

    MAX_EXEC_OUTPUT_SIZE = 10 * 1024**2
    MAX_EXEC_OUTPUT_SIZE_STR = "10 MiB"

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
