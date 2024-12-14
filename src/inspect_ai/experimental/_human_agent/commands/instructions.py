import os
from argparse import Namespace
from typing import Awaitable, Callable

from pydantic import JsonValue
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from inspect_ai._display.core.rich import rich_no_color

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
                console = Console(
                    record=True,
                    file=f,
                    force_terminal=True,
                    no_color=rich_no_color(),
                    width=100,
                )

                def print_heading(text: str) -> None:
                    console.print("")
                    console.rule(
                        f"[blue][bold]{text}[/bold][/blue]",
                        style="blue bold",
                    )
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
                    table.add_row(
                        f"[bold]task {command.name}[/bold]", command.description
                    )
                console.print(table)

                print_heading("Task Instructions")
                console.print(state.instructions, highlight=False)
                console.print("")
                console.print(Rule("", style="blue", align="left", characters="․"))
                console.print("")
                console.print(
                    "Use the [bold]task submit[/bold] command to submit your answer. You can view these instructions at any time with the [bold]task instructions[/bold] command or in the [bold]instructions.txt[/bold] file in your login directory."
                )

                return console.export_text(styles=not no_ansi)

        return instructions
