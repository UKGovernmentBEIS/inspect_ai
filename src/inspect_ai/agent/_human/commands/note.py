from argparse import Namespace
from typing import Awaitable, Callable, Literal

from pydantic import JsonValue

from ..state import HumanAgentState
from .command import HumanAgentCommand, call_human_agent


class NoteCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "note"

    @property
    def description(self) -> str:
        return "Record a note in the task transcript."

    @property
    def group(self) -> Literal[1, 2, 3]:
        return 1

    def cli(self, args: Namespace) -> None:
        print(
            "Enter a multiline markdown note (Press Ctrl+D on a new line to finish):\n"
        )
        lines = ["## Human Agent Note"]
        try:
            while True:
                line = input()
                lines.append(line)
        except EOFError:
            pass
        call_human_agent("note", content="\n".join(lines))

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        from inspect_ai.log._transcript import transcript

        async def note(content: str) -> None:
            transcript().info(content, source="human_agent")

        return note
