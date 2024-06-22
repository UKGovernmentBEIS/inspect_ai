import os
from logging import getLogger
from pathlib import Path

import aiofiles

logger = getLogger(__name__)


async def auto_compose(parent: str = "") -> str | None:
    # compose file provides all the config we need
    if has_compose_file(parent):
        return None

    # temporary auto-compose
    if has_auto_compose_file(parent):
        return Path(os.path.join(parent, AUTO_COMPOSE_YAML)).resolve().as_posix()

    # dockerfile just needs a compose.yaml synthesized
    elif has_dockerfile(parent):
        return await auto_compose_file(COMPOSE_DOCKERFILE_YAML, parent)

    # otherwise provide a generic python container
    else:
        return await auto_compose_file(COMPOSE_GENERIC_YAML, parent)


def has_compose_file(parent: str = "") -> bool:
    compose_files = [
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
    ]
    for file in compose_files:
        if os.path.isfile(os.path.join(parent, file)):
            return True
    return False


def has_dockerfile(parent: str = "") -> bool:
    return os.path.isfile(os.path.join(parent, "Dockerfile"))


def has_auto_compose_file(parent: str = "") -> bool:
    return os.path.isfile(os.path.join(parent, AUTO_COMPOSE_YAML))


def is_auto_compose_file(file: str) -> bool:
    return os.path.basename(file) == AUTO_COMPOSE_YAML


async def ensure_auto_compose_file(file: str | None) -> None:
    if file is not None and is_auto_compose_file(file) and not os.path.exists(file):
        await auto_compose(os.path.dirname(file))


def safe_cleanup_auto_compose(file: str | None) -> None:
    if file:
        try:
            if is_auto_compose_file(file) and os.path.exists(file):
                os.unlink(file)
        except Exception as ex:
            logger.warning(f"Error cleaning up compose file: {ex}")


AUTO_COMPOSE_YAML = ".compose.yaml"

COMPOSE_COMMENT = """# inspect auto-generated docker compose file
# (will be removed when task is complete)"""

COMPOSE_NETWORKS = """
    networks:
      - no-internet
networks:
  no-internet:
    driver: bridge
    internal: true
"""

COMPOSE_GENERIC_YAML = f"""{COMPOSE_COMMENT}
services:
  default:
    image: "python:3.12-bookworm"
    command: "tail -f /dev/null"{COMPOSE_NETWORKS}
"""

COMPOSE_DOCKERFILE_YAML = f"""{COMPOSE_COMMENT}
services:
  default:
    build:
      context: "."
    command: "tail -f /dev/null"{COMPOSE_NETWORKS}
"""


async def auto_compose_file(contents: str, parent: str = "") -> str:
    path = os.path.join(parent, AUTO_COMPOSE_YAML)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(contents)
    return Path(path).resolve().as_posix()
