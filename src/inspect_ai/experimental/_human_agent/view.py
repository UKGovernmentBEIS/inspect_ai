from typing import Protocol

from rich.console import Console

from inspect_ai.util._sandbox.environment import SandboxConnection

from .state import HumanAgentState


class HumanAgentView(Protocol):
    def connect(self, connection: SandboxConnection) -> None: ...
    def update_state(self, state: HumanAgentState) -> None: ...


class ConsoleView(HumanAgentView):
    """Fallback view for when we aren't running fullscreen UI."""

    def __init__(self, console: Console):
        self._console = console

    def connect(self, connection: SandboxConnection) -> None:
        self._console.print(
            "You are completing a task on a Linux system (task instructions will be presented "
            + "when you login). Login to the system with the following command:\n"
        )
        self._console.print(f"{connection.command}\n", highlight=False)

    def update_state(self, state: HumanAgentState) -> None:
        pass
