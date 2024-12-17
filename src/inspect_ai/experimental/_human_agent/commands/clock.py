from typing import Awaitable, Callable, Literal

from pydantic import JsonValue

from ..state import HumanAgentState
from .command import HumanAgentCommand


class StartCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "start"

    @property
    def description(self) -> str:
        return "Start the task clock (resume working)."

    @property
    def group(self) -> Literal[1, 2, 3]:
        return 2

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def start() -> None:
            state.running = True

        return start


class StopCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "stop"

    @property
    def description(self) -> str:
        return "Stop the task clock (pause working)."

    @property
    def group(self) -> Literal[1, 2, 3]:
        return 2

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def stop() -> None:
            state.running = False

        return stop
