from argparse import Namespace
from typing import Awaitable, Callable

from pydantic import JsonValue
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from inspect_ai._util.ansi import render_text
from inspect_ai._util.transcript import DOUBLE_LINE

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
            intro = "\nYou will be completing a task based on the instructions presented below. You can use the following commands to submit answers, manage time, and view these instructions again:\n"
            commands_table = Table(box=None, show_header=False)
            commands_table.add_column("", justify="left")
            commands_table.add_column("", justify="left")
            for command in filter(lambda c: "cli" in c.contexts, self._commands):
                commands_table.add_row(f"task {command.name}", command.description)

            header_panel = Panel(
                Group(intro, commands_table),
                title=Text.from_markup("[bold]Human Agent Task[/bold]"),
                box=DOUBLE_LINE,
                padding=(0, 0),
            )

            instructions_panel = Panel(
                f"{state.instructions.strip()}",
                title="Task Instructions",
                padding=(1, 1),
            )

            return render_text(
                ["", header_panel, instructions_panel],
                styles=False,
                no_color=True,
                width=100,
            )

        return instructions
