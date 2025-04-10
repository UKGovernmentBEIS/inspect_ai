from argparse import Namespace
from typing import Awaitable, Callable, Literal

from pydantic import JsonValue

from inspect_ai._util.format import format_progress_time

from ..state import HumanAgentState
from .command import HumanAgentCommand, call_human_agent
from .status import render_status


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

    def cli(self, args: Namespace) -> None:
        print(call_human_agent("start"))

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def start() -> str:
            if not state.running:
                state.running = True
                clock_action_event("start", state)
            return render_status(state)

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

    def cli(self, args: Namespace) -> None:
        print(call_human_agent("stop"))

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def stop() -> str:
            if state.running:
                state.running = False
                clock_action_event("stop", state)
            return render_status(state)

        return stop


def clock_action_event(
    action: Literal["start", "stop"], state: HumanAgentState
) -> None:
    from inspect_ai.log._transcript import transcript

    transcript().info(
        {
            "action": action,
            "total_time": format_progress_time(state.time, False),
        },
        source="human_agent",
    )
