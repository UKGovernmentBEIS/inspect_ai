from inspect_ai._util.text import truncate_string_to_bytes
from inspect_ai.util._subprocess import ExecResult


class SandboxEnvironmentLimits:
    """Encapsulates limits for sandbox environments."""

    MAX_EXEC_OUTPUT_SIZE = 1024**2
    MAX_EXEC_OUTPUT_SIZE_STR = "1 MiB"


class SandboxOutputLimitExceededError(Exception):
    """Exception raised when an exec() output stream exceeds the size limit."""

    def __init__(self, truncated_result: ExecResult[str]) -> None:
        self.limit_str = SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE_STR
        self.truncated_result = truncated_result
        super().__init__(
            f"The sandbox output stream limit of {self.limit_str} was exceeded for "
            "stdout and/or stderr."
        )


def verify_exec_result_size(exec_result: ExecResult[str]) -> None:
    """Verify the size of the output streams in an `ExecResult`.

    Raises:
      SandboxOutputLimitExceededError: If an output stream exceeds the 1 MiB limit.
    """
    limit = SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE
    stdout_truncated = truncate_string_to_bytes(exec_result.stdout, limit)
    stderr_truncated = truncate_string_to_bytes(exec_result.stderr, limit)
    if not stdout_truncated and not stderr_truncated:
        return
    raise SandboxOutputLimitExceededError(
        truncated_result=ExecResult(
            success=exec_result.success,
            returncode=exec_result.returncode,
            stdout=stdout_truncated.output if stdout_truncated else exec_result.stdout,
            stderr=stderr_truncated.output if stderr_truncated else exec_result.stderr,
        ),
    )
