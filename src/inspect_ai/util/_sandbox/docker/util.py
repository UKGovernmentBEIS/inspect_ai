import re
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path

from shortuuid import uuid

from inspect_ai._util.constants import SANDBOX

from .config import (
    COMPOSE_DOCKERFILE_YAML,
    auto_compose_file,
    ensure_auto_compose_file,
    is_dockerfile,
    resolve_compose_file,
)

logger = getLogger(__name__)


@dataclass
class ComposeProject:
    name: str
    config: str | None
    env: dict[str, str] | None

    @classmethod
    async def create(
        cls, name: str, config: str | None, env: dict[str, str] = {}
    ) -> "ComposeProject":
        # resolve config to full path if we have one
        config_path = Path(config).resolve() if config else None

        # if its a Dockerfile, then config is the auto-generated .compose.yaml
        if config_path and is_dockerfile(config_path.name):
            config = await auto_compose_file(
                COMPOSE_DOCKERFILE_YAML, config_path.parent.as_posix()
            )

        # if its another config file, just take its path
        elif config_path:
            config = config_path.as_posix()

        # no config passed, look for 'auto-config' (compose.yaml, Dockerfile, etc.)
        else:
            config = await resolve_compose_file()

        # this could be a cleanup where docker has tracked a .compose.yaml file
        # as part of its ConfigFiles and passed it back to us -- we in the
        # meantime have cleaned it up so we re-create it here as required
        await ensure_auto_compose_file(config)

        # return project
        return ComposeProject(name, config, env)

    def __init__(
        self,
        name: str,
        config: str | None,
        env: dict[str, str],
    ) -> None:
        self.name = name
        self.config = config
        self.env = env

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ComposeProject):
            return NotImplemented
        else:
            return self.name == other.name


def task_project_name(task: str) -> str:
    # ensure that task conforms to docker project name constraints
    task = task.lower()
    task = re.sub(r"[^a-z\d\-_]", "-", task)
    task = re.sub(r"-+", "-", task)
    if len(task) == 0:
        task = "task"

    return f"inspect-{task}-i{uuid().lower()}"


inspect_project_pattern = r"^inspect-[a-z\d\-_]*-i[a-z\d]{22}$"


def is_inspect_project(name: str) -> bool:
    return re.match(inspect_project_pattern, name) is not None


def sandbox_log(msg: str) -> None:
    logger.log(SANDBOX, f"DOCKER: {msg}")
