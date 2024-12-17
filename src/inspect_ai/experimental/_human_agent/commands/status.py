from argparse import Namespace
from typing import Awaitable, Callable, Literal

from pydantic import JsonValue

from ..state import HumanAgentState
from .command import (
    HumanAgentCommand,
    call_human_agent,
)


class StatusCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "status"

    @property
    def description(self) -> str:
        return "Print task clock status."

    @property
    def group(self) -> Literal[1, 2, 3]:
        return 2

    def cli(self, args: Namespace) -> None:
        status = call_human_agent("status")
        print(status)

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def status() -> str:
            return str(state.status)

        return status
