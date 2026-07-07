import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Literal

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


class _LimitStrDescriptor:
    """Descriptor that derives a human-readable string from a ContextVar."""

    def __init__(self, var: ContextVar[int]) -> None:
        self._var = var

    def __get__(self, obj: object, objtype: type | None = None) -> str:
        return _human_readable_size(self._var.get())


class SandboxEnvironmentLimits:
    """Encapsulates limits for sandbox environments."""

    MAX_EXEC_OUTPUT_SIZE: int = _LimitDescriptor(_max_exec_output_size_var)  # type: ignore[assignment]
    MAX_EXEC_OUTPUT_SIZE_STR: str = _LimitStrDescriptor(_max_exec_output_size_var)  # type: ignore[assignment]

    MAX_READ_FILE_SIZE: int = _LimitDescriptor(_max_read_file_size_var)  # type: ignore[assignment]
    MAX_READ_FILE_SIZE_STR: str = _LimitStrDescriptor(_max_read_file_size_var)  # type: ignore[assignment]


def _parse_limit_env_var(name: str, value: str) -> int:
    """Parse and validate a sandbox limit environment variable."""
    try:
        limit = int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer (bytes), got '{value}'.")
    if limit <= 0:
        raise ValueError(f"{name} must be a positive integer (bytes), got {limit}.")
    return limit


def set_sandbox_limits() -> list[Token[int]]:
    """Override sandbox limits for the current async context.

    Override limits using the `INSPECT_SANDBOX_MAX_READ_FILE_SIZE` and `INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE`.

    Returns tokens that can be passed to `reset_sandbox_limits()` to restore
    previous values.
    """
    tokens: list[Token[int]] = []
    max_read_file_size = os.getenv("INSPECT_SANDBOX_MAX_READ_FILE_SIZE", None)
    if max_read_file_size is not None:
        tokens.append(
            _max_read_file_size_var.set(
                _parse_limit_env_var(
                    "INSPECT_SANDBOX_MAX_READ_FILE_SIZE", max_read_file_size
                )
            )
        )
    max_exec_output_size = os.getenv("INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE", None)
    if max_exec_output_size is not None:
        tokens.append(
            _max_exec_output_size_var.set(
                _parse_limit_env_var(
                    "INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE", max_exec_output_size
                )
            )
        )
    return tokens


def reset_sandbox_limits(tokens: list[Token[int]]) -> None:
    """Restore sandbox limits from tokens returned by `set_sandbox_limits()`."""
    for token in tokens:
        token.var.reset(token)


@contextmanager
def override_max_exec_output_size(limit: int) -> Iterator[None]:
    """Temporarily override the max exec output size for the current context.

    Use this to read output that is legitimately larger than the default exec
    output cap (e.g. a sandbox service request payload) without raising the
    limit for unrelated exec calls. The override is scoped to the current
    async context and restored on exit.

    Args:
        limit: Output size limit (in bytes) to apply within the context.
    """
    token = _max_exec_output_size_var.set(limit)
    try:
        yield
    finally:
        _max_exec_output_size_var.reset(token)


@contextmanager
def override_max_read_file_size(limit: int) -> Iterator[None]:
    """Temporarily override the max read file size for the current context.

    Use this to read a file that is legitimately larger than the default
    read file cap (e.g. a checkpoint egress tarball) without raising the
    limit for unrelated reads. The override is scoped to the current async
    context and restored on exit.

    Args:
        limit: File size limit (in bytes) to apply within the context.
    """
    token = _max_read_file_size_var.set(limit)
    try:
        yield
    finally:
        _max_read_file_size_var.reset(token)


@contextmanager
def override_sandbox_output_limit(
    limit: int, *targets: Literal["exec", "read_file"]
) -> Iterator[None]:
    """Temporarily override sandbox output limits for the current context.

    Convenience wrapper that delegates to `override_max_exec_output_size`
    and/or `override_max_read_file_size`, applying `limit` to each named
    target. The overrides are scoped to the current async context and
    restored on exit.

    Args:
        limit: Size limit (in bytes) to apply within the context.
        *targets: Which limits to override — `"exec"` (exec output) and/or
            `"read_file"` (file reads). If omitted, both are overridden.
    """
    overrides = {
        "exec": override_max_exec_output_size,
        "read_file": override_max_read_file_size,
    }
    selected = targets or ("exec", "read_file")
    with ExitStack() as stack:
        for target in selected:
            stack.enter_context(overrides[target](limit))
        yield


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
