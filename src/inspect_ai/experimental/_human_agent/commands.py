import abc
from argparse import Namespace
from pathlib import Path
from typing import Any, Awaitable, Callable, NamedTuple

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

    class Arg(NamedTuple):
        name: str
        description: str
        required: bool

    @property
    def args(self) -> list[Arg]:
        """Positional command line arguments."""
        return []

    @property
    def hidden(self) -> bool:
        return False

    @abc.abstractmethod
    def call(self, args: Namespace) -> None:
        """Command client (runs in container)"""
        ...

    def handler(
        self, state: HumanAgentState
    ) -> Callable[..., Awaitable[JsonValue]] | None:
        """Handler (runs in Inspect process). Optional (you can create call only commands)"""
        ...


def human_agent_commands(_intermediate_scoring: bool) -> list[HumanAgentCommand]:
    return [
        StatusCommand(),
        StartCommand(),
        StopCommand(),
        InstructionsCommand(),
        SubmitCommand(),
    ]


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

    def call(self, args: Namespace) -> None:
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

    def call(self, args: Namespace) -> None:
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

    def call(self, args: Namespace) -> None:
        call_human_agent("stop")

    def handler(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def stop() -> None:
            state.running = False

        return stop


class InstructionsCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "instructions"

    @property
    def description(self) -> str:
        return "Display task instructions."

    def call(self, args: Namespace) -> None:
        print("TASK INSTRUCTIONS")


class SubmitCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "submit"

    @property
    def description(self) -> str:
        return "Submit your answer for the task."

    @property
    def args(self) -> list[HumanAgentCommand.Arg]:
        return [
            HumanAgentCommand.Arg(
                name="answer",
                description="Answer to submit for scoring (optional, not required for all tasks)",
                required=False,
            )
        ]

    def call(self, args: Namespace) -> None:
        # read cli args
        call_args = vars(args)

        # collect session logs if they exist
        sessions_dir = Path("/var/tmp/user-sessions")
        if sessions_dir.exists() and sessions_dir.is_dir():
            session_logs: dict[str, str] = {}
            for file in sessions_dir.iterdir():
                if file.is_file():
                    try:
                        with open(file, "r") as f:
                            session_logs[file.name] = f.read()
                    except Exception as e:
                        print(f"Error reading file {file.name}: {e}")
                        continue
            call_args["session_logs"] = session_logs

        call_human_agent("submit", **call_args)

    def handler(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def submit(
            answer: str | None, session_logs: dict[str, str] | None = None
        ) -> None:
            state.running = False
            state.answer = answer
            state.session_logs = session_logs

        return submit
