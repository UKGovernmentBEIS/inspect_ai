import abc
from argparse import Namespace
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, NamedTuple

from pydantic import JsonValue
from rich.console import Console

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
    def contexts(self) -> list[Literal["cli", "service"]]:
        """Contexts where this command runs (defaults to both cli and service)."""
        return ["cli", "service"]

    class CLIArg(NamedTuple):
        name: str
        description: str
        required: bool

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


def human_agent_commands(_intermediate_scoring: bool) -> list[HumanAgentCommand]:
    return [
        ClockCommand(),
        StartCommand(),
        StopCommand(),
        InstructionsCommand(),
        SubmitCommand(),
    ]


def call_human_agent(method: str, **params: Any) -> Any:
    """Dummy function for implementation of call method."""
    return None


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
            console = Console(record=True, force_terminal=True)

            # Print something with Rich styles
            console.print("Hello, [bold]World[/bold]!")

            # Export the recorded ANSI text
            return console.export_text(styles=True)

        return clock


class StartCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "start"

    @property
    def description(self) -> str:
        return "Start working on the task."

    @property
    def contexts(self) -> list[Literal["cli", "service"]]:
        return ["service"]

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


class InstructionsCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "instructions"

    @property
    def description(self) -> str:
        return "Display task instructions."

    @property
    def contexts(self) -> list[Literal["cli", "service"]]:
        return ["cli"]

    def cli(self, args: Namespace) -> None:
        print("TASK INSTRUCTIONS")


class SubmitCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "submit"

    @property
    def description(self) -> str:
        return "Submit your answer for the task."

    @property
    def cli_args(self) -> list[HumanAgentCommand.CLIArg]:
        return [
            HumanAgentCommand.CLIArg(
                name="answer",
                description="Answer to submit for scoring (optional, not required for all tasks)",
                required=False,
            )
        ]

    def cli(self, args: Namespace) -> None:
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

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def submit(
            answer: str | None, session_logs: dict[str, str] | None = None
        ) -> None:
            state.running = False
            state.answer = answer
            state.session_logs = session_logs

        return submit
