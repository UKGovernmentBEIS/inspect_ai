import os
from argparse import Namespace
from typing import Awaitable, Callable

from pydantic import JsonValue
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from ..state import HumanAgentState
from .command import HumanAgentCommand, call_human_agent


class InstructionsCommand(HumanAgentCommand):
    def __init__(self, commands: list[HumanAgentCommand]) -> None:
        self._commands = commands.copy() + [self]

    @property
    def name(self) -> str:
        return "instructions"

    @property
    def description(self) -> str:
        return "Display task commands and instructions."

    def cli(self, args: Namespace) -> None:
        print(call_human_agent("instructions", **vars(args)))

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def instructions() -> str:
            # use rich styles
            with open(os.devnull, "w") as f:
                console = Console(
                    record=True,
                    file=f,
                    force_terminal=True,
                    no_color=True,
                    width=100,
                )

                def print_heading(text: str) -> None:
                    console.rule(f"{text}")
                    console.print("")

                print_heading("Inspect Agent Task")
                console.print(
                    "You will be completing a task as a human agent based on the instructions presented below. You can use the following commands to submit answers, manage time, and view instructions:"
                )
                console.print("")
                table = Table(box=None, show_header=False)
                table.add_column("", justify="left")
                table.add_column("", justify="left")
                for command in filter(lambda c: "cli" in c.contexts, self._commands):
                    table.add_row(f"task {command.name}", command.description)
                console.print(table)
                console.print("")

                print_heading("Task Instructions")
                console.print(state.instructions, highlight=False)
                console.print("")
                console.print(Rule("", style="blue", align="left", characters="․"))
                console.print("")
                console.print(
                    "When ready, submit your answer using the 'task submit' command. View these instructions with the 'task instructions' command or in the 'instructions.txt' file."
                )

                return console.export_text()

        return instructions
