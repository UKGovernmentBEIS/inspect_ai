from typing import Protocol

from inspect_ai.util import SandboxConnection

from .state import HumanAgentState


class HumanAgentView(Protocol):
    def connect(self, connection: SandboxConnection) -> None: ...
    def update_state(self, state: HumanAgentState) -> None: ...


class ConsoleView(HumanAgentView):
    """Fallback view for when we aren't running fullscreen UI."""

    def connect(self, connection: SandboxConnection) -> None:
        print(
            "You are completing a task on a Linux system (task instructions will be presented "
            + "when you login). Login to the system with the following command:\n"
        )
        print(f"{connection.command}\n")

    def update_state(self, state: HumanAgentState) -> None:
        pass
