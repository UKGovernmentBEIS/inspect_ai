from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample

COMPOSE_FILE = Path(__file__).parent / "compose.dynamic-image.yaml"


@pytest.mark.slow
@skip_if_no_docker
def test_docker_dynamic_image():
    task = Task(
        dataset=[
            Sample(
                input="Say hello.",
                metadata=dict(docker_image="python:3.12-bookworm"),
            ),
            Sample(
                input="Say hello, world",
                metadata=dict(docker_image="python:3.13-bookworm"),
            ),
        ],
        sandbox=("docker", COMPOSE_FILE.as_posix()),
    )
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"
