from argparse import Namespace
from typing import Awaitable, Callable

from pydantic import JsonValue

from ..state import HumanAgentState
from .command import (
    HumanAgentCommand,
    call_human_agent,
)


class ClockCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "clock"

    @property
    def description(self) -> str:
        return "Check the time taken so far on this task."

    def cli(self, args: Namespace) -> None:
        status = call_human_agent("clock")
        print(status)

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def clock() -> str:
            return str(state.status)

        return clock


class StartCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "start"

    @property
    def description(self) -> str:
        return "Start working on the task."

    def cli(self, args: Namespace) -> None:
        call_human_agent("start")

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
        return "Stop working on the task."

    def cli(self, args: Namespace) -> None:
        call_human_agent("stop")

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def stop() -> None:
            state.running = False

        return stop
