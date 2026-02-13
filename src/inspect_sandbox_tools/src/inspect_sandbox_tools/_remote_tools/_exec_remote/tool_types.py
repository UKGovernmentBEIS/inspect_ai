from typing import Literal

from pydantic import BaseModel


class SubmitParams(BaseModel):
    """Parameters for exec_remote_start."""

    command: str
    input: str | None = None
    """Standard input to send to the command (as a string)."""
    stdin_open: bool = False
    """If True, keep stdin open after writing initial input for later writes."""
    env: dict[str, str] | None = None
    """Additional environment variables (merged with the current environment)."""
    cwd: str | None = None
    """Working directory for command execution."""
    model_config = {"extra": "forbid"}


class PollParams(BaseModel):
    """Parameters for exec_remote_poll."""

    pid: int
    model_config = {"extra": "forbid"}


class KillParams(BaseModel):
    """Parameters for exec_remote_kill."""

    pid: int
    model_config = {"extra": "forbid"}


class SubmitResult(BaseModel):
    """Result from exec_remote_start."""

    pid: int


class PollResult(BaseModel):
    """Result from exec_remote_poll.

    Fields:
        state: Job lifecycle state - "running", "completed", or "killed"
        exit_code: Process exit code (only present when state is "completed")
        stdout: Standard output since last poll (incremental)
        stderr: Standard error since last poll (incremental)
    """

    state: Literal["running", "completed", "killed"]
    exit_code: int | None = None
    stdout: str
    stderr: str


class OutputResult(BaseModel):
    """Base result containing incremental stdout/stderr since the last read.

    Used by kill, write_stdin, and close_stdin results so that every
    round-trip also delivers any buffered output.
    """

    stdout: str
    stderr: str


class KillResult(OutputResult):
    """Result from exec_remote_kill."""

    pass


class WriteStdinParams(BaseModel):
    """Parameters for exec_remote_write_stdin."""

    pid: int
    data: str
    model_config = {"extra": "forbid"}


class WriteStdinResult(OutputResult):
    """Result from exec_remote_write_stdin."""

    pass


class CloseStdinParams(BaseModel):
    """Parameters for exec_remote_close_stdin."""

    pid: int
    model_config = {"extra": "forbid"}


class CloseStdinResult(OutputResult):
    """Result from exec_remote_close_stdin."""

    pass
