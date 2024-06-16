import os
from logging import getLogger
from pathlib import Path

import aiofiles

logger = getLogger(__name__)


async def auto_config() -> str | None:
    # compose file provides all the config we need
    if has_compose_file():
        return None

    # temporary auto-compose
    if has_auto_compose_file():
        return AUTO_COMPOSE_YAML

    # dockerfile just needs a compose.yaml synthesized
    elif has_dockerfile():
        return await auto_compose_file(COMPOSE_DOCKERFILE_YAML)

    # otherwise provide a generic python container
    else:
        return await auto_compose_file(COMPOSE_GENERIC_YAML)


def auto_config_cleanup() -> None:
    # if we have an auto-generated .compose.yaml then clean it up
    if has_auto_compose_file():
        Path(AUTO_COMPOSE_YAML).unlink(True)


def has_compose_file() -> bool:
    compose_files = [
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
    ]
    for file in compose_files:
        if os.path.isfile(file):
            return True
    return False


def has_dockerfile() -> bool:
    return os.path.isfile("Dockerfile")


def has_auto_compose_file() -> bool:
    return os.path.isfile(AUTO_COMPOSE_YAML)


AUTO_COMPOSE_YAML = ".compose.yaml"

COMPOSE_COMMENT = """# inspect auto-generated docker compose file
# (will be removed when task is complete)"""

COMPOSE_GENERIC_YAML = f"""{COMPOSE_COMMENT}
services:
  default:
    image: "python:3.12-bookworm"
    command: "tail -f /dev/null"
"""

COMPOSE_DOCKERFILE_YAML = f"""{COMPOSE_COMMENT}
services:
  default:
    build:
      context: "."
    command: "tail -f /dev/null"
"""


async def auto_compose_file(contents: str) -> str:
    async with aiofiles.open(AUTO_COMPOSE_YAML, "w", encoding="utf-8") as f:
        await f.write(contents)
    return AUTO_COMPOSE_YAML
