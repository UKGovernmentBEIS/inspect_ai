import json
import os
from pathlib import Path
from typing import Any

from shortuuid import uuid

from .appdirs import inspect_data_dir


def vscode_workspace_id() -> str | None:
    return os.environ.get("INSPECT_WORKSPACE_ID", None)


def execute_vscode_command(command: str, args: list[Any] = []) -> None:
    command_dir = vs_code_commands_dir()
    if command_dir is None:
        raise NotImplementedError(
            "Not running in VS Code session or have older version of Inspect AI extension"
        )

    command_file = command_dir / uuid()
    with open(command_file, "w") as f:
        f.write(json.dumps({"command": command, "args": args}))


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
