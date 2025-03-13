from argparse import Namespace
from typing import Awaitable, Callable, Literal

from pydantic import JsonValue
from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from inspect_ai._util.ansi import render_text
from inspect_ai._util.format import format_progress_time

from ..state import HumanAgentState
from .command import HumanAgentCommand, call_human_agent


class StatusCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "status"

    @property
    def description(self) -> str:
        return "Print task status (clock, scoring, etc.)"

    @property
    def group(self) -> Literal[1, 2, 3]:
        return 2

    def cli(self, args: Namespace) -> None:
        print(call_human_agent("status"))

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def status() -> str:
            return render_status(state)

        return status


def render_status(state: HumanAgentState) -> str:
    content: list[RenderableType] = [""]
    content.append(
        f"[bold]Status:[/bold] {'Running' if state.running else 'Stopped'}  "
        + f"[bold]Time:[/bold] {format_progress_time(state.time, pad_hours=False)}"
    )

    if len(state.scorings) > 0:
        content.append("")
        content.append(Text.from_markup("[italic]Intermediate Scores[/italic]"))
        scores_table = Table(box=None, min_width=35, padding=(0, 0))
        scores_table.add_column("Answer", justify="left")
        scores_table.add_column("Score", justify="center")
        scores_table.add_column("Time", justify="right")

        for score in state.scorings:
            scores_table.add_row(
                score.scores[0].answer,
                score.scores[0].as_str(),
                format_progress_time(score.time),
            )
        content.append(scores_table)

    return render_text(content, highlight=False)
