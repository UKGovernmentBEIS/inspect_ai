import sys
from asyncio import CancelledError
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


# Backend cancellation exceptions are recorded as their repr, e.g.
# "CancelledError('Cancelled via cancel scope ...')" (asyncio) or
# "Cancelled()" (trio). A sample cancelled because a sibling failed or the
# eval was torn down for a retry isn't a genuine error.
_CANCELLED_EXC_NAMES = ("CancelledError", "Cancelled")


def is_cancellation_message(message: str | None) -> bool:
    """Whether an error message is a backend cancellation exception repr."""
    return message is not None and any(
        message.startswith(f"{name}(") for name in _CANCELLED_EXC_NAMES
    )


def pip_dependency_error(feature: str, dependencies: list[str]) -> Exception:
    return PrerequisiteError(
        f"[bold]ERROR[/bold]: {feature} requires optional dependencies. "
        f"Install with:\n\n[bold]pip install {' '.join(dependencies)}[/bold]"
    )


def module_version_error(
    feature: str, package: str, required_version: str
) -> Exception:
    return PrerequisiteError(
        f"ERROR: {feature} requires at least version {required_version} of package {package} "
        f"(you have version {version(package)} installed).\n\n"
        f"Upgrade with: pip install --upgrade {package}"
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


class SilentException(Exception):
    pass


class WriteConflictError(Exception):
    """Exception raised when a conditional write fails due to concurrent modification.

    This error occurs when attempting to write to a log file that has been
    modified by another process since it was last read, indicating a race
    condition between concurrent evaluation runs.
    """


def exception_hook() -> Callable[..., None]:
    sys_handler = sys.excepthook

    def handler(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: TracebackType,
    ) -> None:
        if isinstance(exception, PrerequisiteError):
            print(f"\n{exception.message}\n")
        elif isinstance(exception, (CancelledError, KeyboardInterrupt)):
            # User-initiated interruption (Ctrl-C → SIGINT, or an inner
            # CancelledError re-raised from the task group to preserve
            # structured concurrency). The per-task display panel
            # already printed a friendly "Task interrupted" footer; a
            # traceback here just confuses the user. Exit with the
            # conventional SIGINT code so shells / supervisors see the
            # interrupt for what it is.
            sys.exit(130)
        elif not isinstance(exception, SilentException):
            sys_handler(exception_type, exception, traceback)
        else:
            sys.exit(1)

    return handler


_exception_hook_set: bool = False


def set_exception_hook() -> None:
    global _exception_hook_set
    if not _exception_hook_set:
        sys.excepthook = exception_hook()
        _exception_hook_set = True
