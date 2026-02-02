import os
from logging import getLogger
from pathlib import Path

import yaml

from inspect_ai._util.appdirs import inspect_data_dir

from ..compose import AUTO_COMPOSE_YAML, COMPOSE_FILES, DOCKERFILE

logger = getLogger(__name__)

AUTO_COMPOSE_SUBDIR = "docker-compose"


def auto_compose_dir() -> Path:
    """Get the directory for storing auto-generated compose files."""
    return inspect_data_dir(AUTO_COMPOSE_SUBDIR)


def resolve_compose_file(parent: str = "", project_name: str | None = None) -> str:
    """Resolve compose file, creating auto-compose if needed.

    Args:
        parent: Directory to search for existing compose/Dockerfile
        project_name: If provided, auto-compose files go to central directory
    """
    # existing compose file provides all the config we need
    compose = find_compose_file(parent)
    if compose is not None:
        return Path(os.path.join(parent, compose)).resolve().as_posix()

    # temporary auto-compose in local dir (legacy pattern)
    if has_auto_compose_file(parent):
        return Path(os.path.join(parent, AUTO_COMPOSE_YAML)).resolve().as_posix()

    # dockerfile just needs a compose.yaml synthesized
    if has_dockerfile(parent):
        if project_name:
            return auto_compose_file(
                COMPOSE_DOCKERFILE_YAML.format(dockerfile=DOCKERFILE),
                project_name,
                base_dir=Path(parent).resolve().as_posix() if parent else os.getcwd(),
            )
        # Fallback for calls without project_name
        return _auto_compose_file_local(
            COMPOSE_DOCKERFILE_YAML.format(dockerfile=DOCKERFILE), parent
        )

    # otherwise provide a generic python container
    if project_name:
        return auto_compose_file(COMPOSE_GENERIC_YAML, project_name)
    return _auto_compose_file_local(COMPOSE_GENERIC_YAML, parent)


def find_compose_file(parent: str = "") -> str | None:
    for file in COMPOSE_FILES:
        if os.path.isfile(os.path.join(parent, file)):
            return file
    return None


def has_dockerfile(parent: str = "") -> bool:
    return os.path.isfile(os.path.join(parent, DOCKERFILE))


def has_auto_compose_file(parent: str = "") -> bool:
    return os.path.isfile(os.path.join(parent, AUTO_COMPOSE_YAML))


def is_auto_compose_file(file: str) -> bool:
    """Check if a file is an auto-generated compose file.

    Recognizes both patterns:
    - New pattern: file is in the central auto-compose directory
    - Legacy pattern: filename is .compose.yaml
    """
    path = Path(file)
    # New pattern: file is in the auto-compose directory
    if path.parent == auto_compose_dir():
        return True
    # Legacy pattern: filename is .compose.yaml
    return path.name == AUTO_COMPOSE_YAML


def ensure_auto_compose_file(file: str | None, project_name: str | None = None) -> None:
    """Ensure auto-compose file exists, recreating if necessary.

    Args:
        file: Path to the compose file
        project_name: Project name for central directory files
    """
    if file is not None and is_auto_compose_file(file) and not os.path.exists(file):
        path = Path(file)
        # For central directory files, we need project_name to recreate
        if project_name and path.parent == auto_compose_dir():
            resolve_compose_file(project_name=project_name)
        else:
            # Legacy local file - recreate in place
            resolve_compose_file(os.path.dirname(file))


def safe_cleanup_auto_compose(file: str | None) -> None:
    if file:
        try:
            if is_auto_compose_file(file) and os.path.exists(file):
                os.unlink(file)
        except Exception as ex:
            logger.warning(f"Error cleaning up compose file: {ex}")


COMPOSE_COMMENT = """# inspect auto-generated docker compose file
# (will be removed when task is complete)"""

COMPOSE_GENERIC_YAML = f"""{COMPOSE_COMMENT}
services:
  default:
    image: "aisiuk/inspect-tool-support"
    command: "tail -f /dev/null"
    init: true
    network_mode: none
    stop_grace_period: 1s
"""

COMPOSE_DOCKERFILE_YAML = f"""{COMPOSE_COMMENT}
services:
  default:
    build:
      context: "."
      dockerfile: "{{dockerfile}}"
    command: "tail -f /dev/null"
    init: true
    network_mode: none
    stop_grace_period: 1s
"""


def auto_compose_file(
    contents: str, project_name: str, base_dir: str | None = None
) -> str:
    """Write auto-compose file for a project to the central directory.

    Args:
        contents: The YAML content to write
        project_name: Unique project name (used as filename)
        base_dir: Directory to resolve relative build paths against (e.g., CWD)

    Returns:
        Absolute path to the created compose file
    """
    if base_dir:
        contents = _update_build_context(contents, base_dir)

    compose_dir = auto_compose_dir()
    path = compose_dir / f"{project_name}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        f.write(contents)
    return path.resolve().as_posix()


def _auto_compose_file_local(contents: str, parent: str = "") -> str:
    """Fallback: Write auto-compose file to local directory (for backward compat)."""
    path = os.path.join(parent, AUTO_COMPOSE_YAML)
    with open(path, "w", encoding="utf-8") as f:
        f.write(contents)
    return Path(path).resolve().as_posix()


def _update_build_context(yaml_content: str, base_dir: str) -> str:
    """Resolve relative build.context paths to absolute paths.

    When auto-compose files are stored in a central directory, relative paths
    like "." won't work. This resolves relative paths against base_dir,
    leaving absolute paths unchanged.

    Args:
        yaml_content: The YAML content to update
        base_dir: Base directory to resolve relative paths against (e.g., CWD)

    Returns:
        Updated YAML content with absolute build context paths
    """
    data = yaml.safe_load(yaml_content)
    if data and "services" in data:
        for service in data["services"].values():
            if "build" in service:
                if isinstance(service["build"], dict):
                    ctx = service["build"].get("context", ".")
                    if not Path(ctx).is_absolute():
                        # Resolve relative path against base_dir
                        service["build"]["context"] = str(Path(base_dir) / ctx)
                elif isinstance(service["build"], str):
                    # build is just a context path string
                    ctx = service["build"]
                    if not Path(ctx).is_absolute():
                        service["build"] = {"context": str(Path(base_dir) / ctx)}
    return yaml.dump(data, default_flow_style=False, sort_keys=False)
