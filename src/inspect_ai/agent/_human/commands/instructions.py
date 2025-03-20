from argparse import Namespace
from typing import Awaitable, Callable, Literal

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

    @property
    def group(self) -> Literal[1, 2, 3]:
        return 3

    def cli(self, args: Namespace) -> None:
        print(call_human_agent("instructions", **vars(args)))

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def instructions() -> str:
            intro = "\nYou will be completing a task based on the instructions presented below. You can use the following commands as you work on the task:\n"
            commands_table = Table(box=None, show_header=False)
            commands_table.add_column("", justify="left")
            commands_table.add_column("", justify="left")

            def add_command_group(group: int) -> None:
                for command in filter(
                    lambda c: "cli" in c.contexts and c.group == group, self._commands
                ):
                    commands_table.add_row(f"task {command.name}", command.description)
                if group != 3:
                    commands_table.add_row("", "")

            for i in range(1, 4):
                add_command_group(i)

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
                width=90,
            )

        return instructions
