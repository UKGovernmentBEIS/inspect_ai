import re
from dataclasses import dataclass
from logging import getLogger

from shortuuid import uuid

from inspect_ai._util.constants import TOOLS

from .config import auto_compose, ensure_auto_compose_file

logger = getLogger(__name__)


@dataclass
class ComposeProject:
    name: str
    config: str | None
    env: dict[str, str] | None
    working_dir: str

    @classmethod
    async def create(
        cls,
        name: str,
        config: str | None,
        env: dict[str, str] = {},
        working_dir: str = "/",
    ) -> "ComposeProject":
        # ensure we have an auto-compose file if we need one
        config = config if config else await auto_compose()
        await ensure_auto_compose_file(config)

        # return project
        return ComposeProject(name, config, env, working_dir)

    def __init__(
        self,
        name: str,
        config: str | None,
        env: dict[str, str],
        working_dir: str,
    ) -> None:
        self.name = name
        self.config = config
        self.env = env
        self.working_dir = working_dir

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


def tools_log(msg: str) -> None:
    logger.log(TOOLS, f"DOCKER: {msg}")
