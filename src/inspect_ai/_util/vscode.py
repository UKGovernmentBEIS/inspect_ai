import os
from logging import getLogger
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_core import to_json
from semver import Version
from shortuuid import uuid

from .appdirs import inspect_data_dir

logger = getLogger(__name__)

EXTENSION_COMMAND_OPEN_SAMPLE = "open_sample"
EXTENSION_COMMAND_VERSIONS = {"inspect.openLogViewer": Version(0, 3, 61)}
EXTENSION_COMMAND_VERSIONS = {
    f"inspect.openLogViewer:{EXTENSION_COMMAND_OPEN_SAMPLE}": Version(0, 3, 62)
}


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


def can_execute_vscode_command(command: str, context: str | None = None) -> bool:
    if not can_execute_vscode_commands():
        return False

    key = command if context is None else f"{command}:{context}"
    required_version = EXTENSION_COMMAND_VERSIONS.get(key)
    if required_version is None:
        return True
    else:
        return has_vscode_version(required_version)


def has_vscode_version(required_version: Version) -> bool:
    current_version = vscode_extension_version()
    if current_version is None:
        return False
    else:
        return current_version.is_compatible(required_version)


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


def vscode_extension_version() -> Version | None:
    version = os.environ.get("INSPECT_VSCODE_EXT_VERSION", None)
    if version is not None:
        try:
            return Version.parse(version)
        except Exception:
            logger.warning(f"Invalid Inspect vscode extension version: {version}")
            return None
    else:
        return None
