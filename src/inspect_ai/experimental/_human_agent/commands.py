import abc
import argparse
import sys
from typing import Any, Awaitable, Callable

from pydantic import JsonValue

from .state import HumanAgentState


class HumanAgentCommand:
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
    def hidden(self) -> bool:
        return False

    @abc.abstractmethod
    def call(self) -> None:
        """Command client (runs in container)"""
        ...

    @abc.abstractmethod
    def handler(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        """Handler (runs in Inspect process)"""
        ...


def human_agent_commands(_intermediate_scoring: bool) -> list[HumanAgentCommand]:
    return [StatusCommand(), StartCommand(), StopCommand(), SubmitCommand()]


def call_human_agent(method: str, **params: Any) -> Any:
    """Dummy function for implementation of call method."""
    return None


class StatusCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "status"

    @property
    def description(self) -> str:
        return "Check the current status of the task."

    def call(self) -> None:
        status = call_human_agent("status")
        print(status)

    def handler(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def status() -> dict[str, JsonValue]:
            return state.status

        return status


class StartCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "start"

    @property
    def description(self) -> str:
        return "Start working on the task."

    def call(self) -> None:
        call_human_agent("start")

    def handler(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
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

    def call(self) -> None:
        call_human_agent("stop")

    def handler(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def stop() -> None:
            state.running = False

        return stop


class SubmitCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "submit"

    @property
    def description(self) -> str:
        return "Submit your answer for the task."

    def call(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "answer",
            nargs="?",
            help="Answer to submit for scoring (optional, not required for all tasks)",
        )
        args = parser.parse_args(sys.argv[2:])
        call_human_agent("submit", **vars(args))

    def handler(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def submit(answer: str | None) -> None:
            state.running = False
            state.answer = answer

        return submit
