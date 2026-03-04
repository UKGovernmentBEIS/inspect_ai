from contextvars import ContextVar, Token
from pathlib import Path

_DEFAULT_MAX_EXEC_OUTPUT_SIZE = 10 * 1024**2
_DEFAULT_MAX_READ_FILE_SIZE = 100 * 1024**2

_max_exec_output_size_var: ContextVar[int] = ContextVar(
    "max_exec_output_size", default=_DEFAULT_MAX_EXEC_OUTPUT_SIZE
)
_max_read_file_size_var: ContextVar[int] = ContextVar(
    "max_read_file_size", default=_DEFAULT_MAX_READ_FILE_SIZE
)


def _human_readable_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string like '100 MiB'."""
    if size_bytes >= 1024**3 and size_bytes % 1024**3 == 0:
        return f"{size_bytes // 1024**3} GiB"
    elif size_bytes >= 1024**2 and size_bytes % 1024**2 == 0:
        return f"{size_bytes // 1024**2} MiB"
    elif size_bytes >= 1024 and size_bytes % 1024 == 0:
        return f"{size_bytes // 1024} KiB"
    else:
        return f"{size_bytes} bytes"


class _LimitDescriptor:
    """Descriptor that reads from a ContextVar, allowing class-level access."""

    def __init__(self, var: ContextVar[int]) -> None:
        self._var = var

    def __get__(self, obj: object, objtype: type | None = None) -> int:
        return self._var.get()

    def __set__(self, obj: object, value: int) -> None:
        self._var.set(value)


class _LimitStrDescriptor:
    """Descriptor that derives a human-readable string from a ContextVar."""

    def __init__(self, var: ContextVar[int]) -> None:
        self._var = var

    def __get__(self, obj: object, objtype: type | None = None) -> str:
        return _human_readable_size(self._var.get())


class SandboxEnvironmentLimits:
    """Encapsulates limits for sandbox environments.

    Limits are stored in context variables so they are safe for concurrent
    async tasks. Use `set_sandbox_limits()` / `reset_sandbox_limits()` to
    override per-task.
    """

    MAX_EXEC_OUTPUT_SIZE: int = _LimitDescriptor(_max_exec_output_size_var)  # type: ignore[assignment]
    MAX_EXEC_OUTPUT_SIZE_STR: str = _LimitStrDescriptor(_max_exec_output_size_var)  # type: ignore[assignment]

    MAX_READ_FILE_SIZE: int = _LimitDescriptor(_max_read_file_size_var)  # type: ignore[assignment]
    MAX_READ_FILE_SIZE_STR: str = _LimitStrDescriptor(_max_read_file_size_var)  # type: ignore[assignment]


def set_sandbox_limits(
    *,
    max_read_file_size: int | None = None,
    max_exec_output_size: int | None = None,
) -> list[Token[int]]:
    """Override sandbox limits for the current async context.

    Returns tokens that can be passed to `reset_sandbox_limits()` to restore
    previous values.

    Args:
        max_read_file_size: Override for MAX_READ_FILE_SIZE (in bytes).
        max_exec_output_size: Override for MAX_EXEC_OUTPUT_SIZE (in bytes).
    """
    tokens: list[Token[int]] = []
    if max_read_file_size is not None:
        tokens.append(_max_read_file_size_var.set(max_read_file_size))
    if max_exec_output_size is not None:
        tokens.append(_max_exec_output_size_var.set(max_exec_output_size))
    return tokens


def reset_sandbox_limits(tokens: list[Token[int]]) -> None:
    """Restore sandbox limits from tokens returned by `set_sandbox_limits()`."""
    for token in tokens:
        token.var.reset(token)


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
      OutputLimitExceededError: If the file size exceeds the limit.
    """
    file_size = Path(file).stat().st_size
    if file_size > SandboxEnvironmentLimits.MAX_READ_FILE_SIZE:
        raise OutputLimitExceededError(
            limit_str=SandboxEnvironmentLimits.MAX_READ_FILE_SIZE_STR,
            # The potentially large, and potentially binary content is not included.
            truncated_output=None,
        )
