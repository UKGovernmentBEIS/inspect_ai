"""Tests for .github/workflows/docker.yml, which publishes the computer tool image.

The job holds the Docker Hub token, and its setup steps run third-party
images in privileged containers. Those images and the Dockerfile's base
image are pinned by digest. The login comes after the setup steps and only
when pushing.
"""

import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "docker.yml"
DOCKERFILE = (
    REPO / "src" / "inspect_ai" / "tool" / "_tools" / "_computer" / "_resources"
) / "Dockerfile"
PINNED = r"\S+:\S+@sha256:[0-9a-f]{64}"


def steps() -> list[dict[str, Any]]:
    job: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())["jobs"]["build-and-push"]
    result: list[dict[str, Any]] = job["steps"]
    return result


def step_index(action: str) -> int:
    matching = [
        i for i, s in enumerate(steps()) if s.get("uses", "").startswith(f"{action}@")
    ]
    assert len(matching) == 1, action
    return matching[0]


def test_setup_images_are_pinned_by_digest() -> None:
    qemu = steps()[step_index("docker/setup-qemu-action")]
    assert re.fullmatch(PINNED, qemu["with"]["image"])
    buildx = steps()[step_index("docker/setup-buildx-action")]
    assert buildx["with"].get("driver") in (None, "docker-container")
    assert re.fullmatch(f"image={PINNED}", buildx["with"]["driver-opts"])


def test_base_image_is_pinned_by_digest() -> None:
    # A single stage. A multi-stage Dockerfile fails here until this check is
    # extended to it.
    froms = re.findall(r"^\s*FROM\b(.*)$", DOCKERFILE.read_text(), re.M | re.I)
    assert len(froms) == 1
    assert re.fullmatch(rf"\s+{PINNED}\s*", froms[0])


def test_login_follows_the_setup_steps_and_precedes_the_push() -> None:
    login = step_index("docker/login-action")
    assert login > step_index("docker/setup-qemu-action")
    assert login > step_index("docker/setup-buildx-action")
    assert login == step_index("docker/build-push-action") - 1
    # inputs.push is the boolean input; github.event.inputs.push is a string
    # and always true.
    assert steps()[login]["if"] == "inputs.push"
