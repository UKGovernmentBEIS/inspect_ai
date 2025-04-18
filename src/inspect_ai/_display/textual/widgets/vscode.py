from textual.widget import Widget
from textual.widgets import Link, Static

from inspect_ai._util.vscode import (
    VSCodeCommand,
    can_execute_vscode_command,
    execute_vscode_commands,
)


def conditional_vscode_link(
    text: str, command: VSCodeCommand, context: str | None = None
) -> Widget:
    if can_execute_vscode_command(command.command, context=context):
        vscode_link = VSCodeLink(text)
        vscode_link.commands = [command]
        return vscode_link
    else:
        return Static()


class VSCodeLink(Link):
    def __init__(
        self,
        text: str,
        *,
        url: str | None = None,
        tooltip: str | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            text,
            url=url,
            tooltip=tooltip,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self.commands: list[VSCodeCommand] = []

    def on_click(self) -> None:
        execute_vscode_commands(self.commands)

    def action_open_link(self) -> None:
        # Workaround to prevent the default action of opening the link in a browser
        return None
