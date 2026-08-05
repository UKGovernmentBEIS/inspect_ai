import abc
from argparse import Namespace
from typing import Any, Awaitable, Callable, Literal, NamedTuple

from pydantic import JsonValue

from ..state import HumanAgentState


class HumanAgentCommand:
    """A command available through the human CLI agent's `task` executable."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Command name (e.g. 'submit')"""
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Command description."""
        ...

    @property
    def group(self) -> Literal[1, 2, 3]:
        """Display group in `task instructions` (1 and 2 are separated by a blank line from what follows; 3 is last, with no trailing separator)."""
        return 1

    @property
    def contexts(self) -> list[Literal["cli", "service"]]:
        """Contexts where this command runs (defaults to both cli and service)."""
        return ["cli", "service"]

    class CLIArg(NamedTuple):
        """A positional argument accepted by this command's CLI invocation."""

        name: str
        """Argument name, as displayed in help text."""

        description: str
        """Argument description, as displayed in help text."""

        required: bool = False
        """Whether the argument must be provided."""

    @property
    def cli_args(self) -> list[CLIArg]:
        """Positional command line arguments."""
        return []

    def cli(self, args: Namespace) -> None:
        """CLI command (runs in container). Required for context "cli"."""
        pass

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        """Service handler (runs in solver). Required for context "service"."""

        async def no_handler() -> None:
            pass

        return no_handler


# Dummy functions for implementation of call methods


def call_human_agent(method: str, **params: Any) -> Any:
    return None


HumanAgentCommandsFilter = Callable[[list[HumanAgentCommand]], list[HumanAgentCommand]]
"""Filter applied to the human CLI agent's command list before it is installed
(and before the instructions command is built, so `task instructions` reflects
the result)."""
