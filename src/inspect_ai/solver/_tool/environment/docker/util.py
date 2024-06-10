from logging import getLogger

from shortuuid import uuid

from inspect_ai._util.constants import TOOLS

logger = getLogger(__name__)


def to_project(task: str) -> str:
    return f"inspect-{task.lower()}-{uuid().lower()}"


def tools_log(msg: str) -> None:
    logger.log(TOOLS, f"DOCKER: {msg}")
