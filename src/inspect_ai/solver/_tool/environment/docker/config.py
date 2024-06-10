import os
import tempfile
from logging import getLogger
from pathlib import Path

import aiofiles

logger = getLogger(__name__)


async def auto_config(temp_dir: str) -> str | None:
    # compose file provides all the config we need
    if has_compose_file():
        return None

    # dockerfile just needs a compose.yaml synthesized
    elif has_dockerfile():
        return await dockerfile_compose(Path(), temp_dir)

    # otherwise provide a generic python container
    else:
        return await generic_container_compose(temp_dir)


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


# Our default compose.yaml
COMPOSE_GENERIC_YAML = """
services:
  default:
    image: "python:3.12-bookworm"
    command: tail -f /dev/null
"""


async def generic_container_compose(directory: str) -> str:
    return await default_compose_file(directory, COMPOSE_GENERIC_YAML)


async def dockerfile_compose(context: Path, directory: str) -> str:
    # Template for a DockerFile
    compose_dockerfile_yaml = f"""
services:
  default:
    build:
      context: {context.resolve().as_posix()}
    command: tail -f /dev/null
    """

    return await default_compose_file(directory, compose_dockerfile_yaml)


# Provide the path to a default compose file
async def default_compose_file(directory: str, contents: str) -> str:
    with tempfile.NamedTemporaryFile(
        dir=directory, suffix=".yaml", delete=False
    ) as compose_file:
        async with aiofiles.open(compose_file.name, "w", encoding="utf-8") as f:
            await f.write(contents)
        return compose_file.name
