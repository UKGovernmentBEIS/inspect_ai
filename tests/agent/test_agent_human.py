import concurrent.futures
import re
import subprocess
import time
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.agent._human.agent import human_cli


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize("user", ["root", "nonroot", None])
def test_human_cli(user: str | None):
    task = Task(
        solver=human_cli(user=user),
        sandbox=("docker", (Path(__file__).parent / "compose.human.yaml").as_posix()),
    )

    stdout = StringIO()

    def run_eval():
        with redirect_stdout(stdout):
            return eval(task, display="plain")[0]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(run_eval)

        while True:
            if match := re.search(r"inspect-task-[^\s]+", stdout.getvalue()):
                container_name = match.group(0)
                assert container_name, "Expected to find task ID in docker exec command"
                break
            time.sleep(1)

        docker_exec = [
            "docker",
            "exec",
            "-it",
            *(["-u", user] if user else []),
            container_name,
            "bash",
            "-l",
            "-c",
        ]
        subprocess.run(docker_exec + ["python3 /opt/human_agent/task.py start"])
        subprocess.run(
            docker_exec
            + [
                'echo -e "y\\n" | python3 /opt/human_agent/task.py submit "test"',
            ],
        )

        concurrent.futures.wait([future])

        log = future.result()
        assert log.status == "success"
        assert log.samples[0].output.choices[0].message.content == "test"
