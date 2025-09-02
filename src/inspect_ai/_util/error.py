import sys
from importlib.metadata import version
from types import TracebackType
from typing import Callable

from pydantic import BaseModel
from rich import print
from rich.console import RenderableType


class EvalError(BaseModel):
    """Eval error details."""

    message: str
    """Error message."""

    traceback: str
    """Error traceback."""

    traceback_ansi: str
    """Error traceback with ANSI color codes."""


def pip_dependency_error(feature: str, dependencies: list[str]) -> Exception:
    return PrerequisiteError(
        f"[bold]ERROR[/bold]: {feature} requires optional dependencies. "
        f"Install with:\n\n[bold]pip install {' '.join(dependencies)}[/bold]"
    )


def module_version_error(
    feature: str, package: str, required_version: str
) -> Exception:
    return PrerequisiteError(
        f"[bold]ERROR[/bold]: {feature} requires at least version {required_version} of package {package} "
        f"(you have version {version(package)} installed).\n\n"
        f"Upgrade with:\n\n[bold]pip install --upgrade {package}[/bold]"
    )


def module_max_version_error(feature: str, package: str, max_version: str) -> Exception:
    return PrerequisiteError(
        f"[bold]ERROR[/bold]: {feature} supports only version {max_version} and earlier of package {package} "
        f"(you have version {version(package)} installed).\n\n"
        f"Install the older version with with:\n\n[bold]pip install {package}=={max_version}[/bold]"
    )


def exception_message(ex: BaseException) -> str:
    return getattr(ex, "message", repr(ex))


class PrerequisiteError(Exception):
    def __init__(self, message: RenderableType) -> None:
        self.message = message


class WriteConflictError(Exception):
    """Exception raised when a conditional write fails due to concurrent modification.

    This error occurs when attempting to write to a log file that has been
    modified by another process since it was last read, indicating a race
    condition between concurrent evaluation runs.
    """


def aws_credentials_error(log_dir: str) -> PrerequisiteError:
    """Create a user-friendly error message for AWS credential issues."""
    return PrerequisiteError(
        f"[bold]ERROR[/bold]: AWS credentials expired/invalid for S3 directory: [bold]{log_dir}[/bold]\n\n"
        f"Fix with: [bold]aws sso login[/bold] or [bold]--log-dir ./logs[/bold]"
    )


def is_aws_credentials_error(ex: BaseException) -> bool:
    """Check if an exception is related to AWS credential issues."""
    error_text = str(ex).lower()
    error_type = type(ex).__name__.lower()

    indicators = [
        "token has expired",
        "invalidgrantexception",
        "tokenretrievalerror",
        "cannot reuse already awaited coroutine",
        "botocore",
    ]

    return any(
        indicator in error_text or indicator in error_type for indicator in indicators
    )


def exception_hook() -> Callable[..., None]:
    sys_handler = sys.excepthook

    def handler(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: TracebackType,
    ) -> None:
        if isinstance(exception, PrerequisiteError):
            print(f"\n{exception.message}\n")
        else:
            sys_handler(exception_type, exception, traceback)

    return handler


_exception_hook_set: bool = False


def set_exception_hook() -> None:
    global _exception_hook_set
    if not _exception_hook_set:
        sys.excepthook = exception_hook()
        _exception_hook_set = True
