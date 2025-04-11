from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.agent._human.agent import human_cli


@pytest.mark.slow
@skip_if_no_docker
def test_human_cli():
    task = Task(
        solver=human_cli(),
        sandbox=("docker", (Path(__file__).parent / "compose.yaml").as_posix()),
    )
    log = eval(task, display="plain")[0]
    assert log.status == "success"
