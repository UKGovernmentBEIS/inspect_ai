import os
from argparse import Namespace
from typing import Awaitable, Callable

from pydantic import JsonValue
from rich.console import Console

from ..state import HumanAgentState
from .command import HumanAgentCommand, call_human_agent


class InstructionsCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "instructions"

    @property
    def description(self) -> str:
        return "Display task instructions."

    @property
    def cli_args(self) -> list[HumanAgentCommand.CLIArg]:
        return [
            HumanAgentCommand.CLIArg(
                name="--no-ansi",
                description="Do not use ANSI escape sequences in display",
            )
        ]

    def cli(self, args: Namespace) -> None:
        print(call_human_agent("instructions", **vars(args)))

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def instructions(no_ansi: bool = False) -> str:
            # use rich styles
            with open(os.devnull, "w") as f:
                console = Console(record=True, file=f, force_terminal=True)
                console.print("Hello, [bold]World[/bold]!")
                return console.export_text(styles=not no_ansi)

        return instructions
