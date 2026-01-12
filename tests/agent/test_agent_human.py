import concurrent.futures
import re
import subprocess
import time
from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.agent._human.agent import human_cli
from inspect_ai.tool import tool


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize("user", ["root", "nonroot", None])
def test_human_cli(capsys: pytest.CaptureFixture[str], user: str | None):
    def run_eval():
        task = Task(
            solver=human_cli(user=user),
            sandbox=(
                "docker",
                (Path(__file__).parent / "compose.human.yaml").as_posix(),
            ),
        )
        return eval(task, display="plain")[0]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(run_eval)

        out = ""
        container_name = None
        for _ in range(10):
            out += capsys.readouterr().out
            if match := re.search(r"inspect-task-\S+-default-1", out):
                container_name = match.group(0)
                break
            time.sleep(1)

        if not container_name:
            raise Exception("Failed to find container name")

        docker_exec = [
            "docker",
            "exec",
            *(["-u", user] if user else []),
            container_name,
            "bash",
            "-l",
            "-c",
        ]

        human_agent_found = False
        for _ in range(10):
            result = subprocess.run(
                docker_exec
                + ["ls /var/tmp/sandbox-services/human_agent/human_agent.py"]
            )
            if result.returncode == 0:
                human_agent_found = True
                break
            time.sleep(1)

        if not human_agent_found:
            raise Exception("Human agent sandbox service not found")

        subprocess.check_call(docker_exec + ["python3 /opt/human_agent/task.py start"])
        subprocess.check_call(
            docker_exec
            + [
                'echo -e "y\\n" | python3 /opt/human_agent/task.py submit "test"',
            ],
        )

        done, _ = concurrent.futures.wait([future], timeout=5)
        if future in done:
            log = future.result()
            assert log.status == "success"
            assert log.samples[0].output.choices[0].message.content == "test"
        else:
            raise Exception("eval() did not complete within timeout")


@pytest.mark.slow
@skip_if_no_docker
def test_human_cli_with_tools(capsys: pytest.CaptureFixture[str]):
    """Test human_cli with tools parameter."""

    @tool
    def addition():
        async def execute(x: int, y: int) -> int:
            """Add two numbers together.

            Args:
                x: First number to add.
                y: Second number to add.

            Returns:
                The sum of the two numbers.
            """
            return x + y

        return execute

    def run_eval():
        task = Task(
            solver=human_cli(tools=[addition()]),
            sandbox=(
                "docker",
                (Path(__file__).parent / "compose.human.yaml").as_posix(),
            ),
        )
        return eval(task, display="plain")[0]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(run_eval)

        # Wait for container (same pattern as test_human_cli)
        out = ""
        container_name = None
        for _ in range(10):
            out += capsys.readouterr().out
            if match := re.search(r"inspect-task-\S+-default-1", out):
                container_name = match.group(0)
                break
            time.sleep(1)

        if not container_name:
            raise Exception("Failed to find container name")

        docker_exec = ["docker", "exec", container_name, "bash", "-l", "-c"]

        # Wait for human_agent service
        human_agent_found = False
        for _ in range(10):
            ls_result = subprocess.run(
                docker_exec
                + ["ls /var/tmp/sandbox-services/human_agent/human_agent.py"]
            )
            if ls_result.returncode == 0:
                human_agent_found = True
                break
            time.sleep(1)

        if not human_agent_found:
            raise Exception("Human agent sandbox service not found")

        # Test: task tool (list tools)
        list_result = subprocess.run(
            docker_exec + ["python3 /opt/human_agent/task.py tool"],
            capture_output=True,
            text=True,
        )
        assert "addition" in list_result.stdout, (
            f"Expected 'addition' in output: {list_result.stdout}"
        )
        assert "Add two numbers" in list_result.stdout

        # Test: task tool addition --help
        help_result = subprocess.run(
            docker_exec + ["python3 /opt/human_agent/task.py tool addition --help"],
            capture_output=True,
            text=True,
        )
        assert "Add two numbers" in help_result.stdout
        assert '"x"' in help_result.stdout  # JSON schema should include parameter

        # Test: task tool addition '{"x": 1, "y": 2}'
        exec_result = subprocess.run(
            docker_exec
            + ['python3 /opt/human_agent/task.py tool addition \'{"x": 1, "y": 2}\''],
            capture_output=True,
            text=True,
        )
        assert "3" in exec_result.stdout, (
            f"Expected '3' in output: {exec_result.stdout}"
        )

        # Clean up: start and submit to complete the task
        subprocess.check_call(docker_exec + ["python3 /opt/human_agent/task.py start"])
        subprocess.check_call(
            docker_exec
            + ['echo -e "y\\n" | python3 /opt/human_agent/task.py submit "done"'],
        )

        done, _ = concurrent.futures.wait([future], timeout=5)
        if future in done:
            log = future.result()
            assert log.status == "success"
        else:
            raise Exception("eval() did not complete within timeout")
