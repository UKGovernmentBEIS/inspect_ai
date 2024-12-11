import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_core import to_json
from shortuuid import uuid

from .appdirs import inspect_data_dir


class VSCodeCommand(BaseModel):
    command: str
    args: list[Any] = Field(default_factory=list)


def execute_vscode_commands(commands: VSCodeCommand | list[VSCodeCommand]) -> None:
    # resolve to list
    commands = commands if isinstance(commands, list) else [commands]

    # ensure there is someone listening
    command_dir = vs_code_commands_dir()
    if command_dir is None:
        raise NotImplementedError(
            "Not running in VS Code session or have older version of Inspect AI extension"
        )

    command_file = command_dir / uuid()
    with open(command_file, "w") as f:
        f.write(to_json(commands).decode())


def can_execute_vscode_commands() -> bool:
    return vs_code_commands_dir() is not None


def vs_code_commands_dir() -> Path | None:
    workspace_id = vscode_workspace_id()
    if workspace_id:
        workspace_dir = inspect_data_dir(os.path.join("vscode", workspace_id))
        if workspace_dir.exists():
            commands_dir = workspace_dir / "commands"
            return commands_dir if commands_dir.exists() else None
        else:
            return None
    else:
        return None


def vscode_workspace_id() -> str | None:
    return os.environ.get("INSPECT_WORKSPACE_ID", None)
