import tempfile
from dataclasses import dataclass
from logging import getLogger

from shortuuid import uuid

from inspect_ai._util.constants import TOOLS

logger = getLogger(__name__)


@dataclass
class ComposeProject:
    name: str
    config: str | None
    env: dict[str, str]
    working_dir: str
    temp_dir: tempfile.TemporaryDirectory[str]

    def __init__(
        self,
        name: str,
        config: str | None,
        env: dict[str, str],
        working_dir: str,
        temp_dir: tempfile.TemporaryDirectory[str],
    ) -> None:
        self.name = name
        self.config = config
        self.env = env
        self.working_dir = working_dir
        self.temp_dir = temp_dir

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ComposeProject):
            return NotImplemented
        else:
            return self.name == other.name


def task_project_name(task: str) -> str:
    return f"inspect-{task.lower()}-{uuid().lower()}"


def tools_log(msg: str) -> None:
    logger.log(TOOLS, f"DOCKER: {msg}")
