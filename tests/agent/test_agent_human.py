import concurrent.futures
import re
import subprocess
import time
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.agent._human.agent import human_cli
from inspect_ai.tool import tool


def wait_for_container_name(
    capsys: pytest.CaptureFixture[str], timeout: int = 10
) -> str:
    """Wait for the container name to appear in captured output."""
    out = ""
    for _ in range(timeout):
        out += capsys.readouterr().out
        if match := re.search(r"inspect-task-\S+-default-1", out):
            return match.group(0)
        time.sleep(1)
    raise Exception("Failed to find container name")


def wait_for_human_agent(docker_exec: list[str], timeout: int = 10) -> None:
    """Wait for the human agent sandbox service to be available."""
    for _ in range(timeout):
        result = subprocess.run(
            docker_exec + ["ls /var/tmp/sandbox-services/human_agent/human_agent.py"]
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise Exception("Human agent sandbox service not found")


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

        container_name = wait_for_container_name(capsys)
        docker_exec = [
            "docker",
            "exec",
            *(["-u", user] if user else []),
            container_name,
            "bash",
            "-l",
            "-c",
        ]
        wait_for_human_agent(docker_exec)

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
    """Test human_cli with tools parameter.

    Tests two argument styles:
    - Named: task tool addition --x 12 --y 34
    - JSON escape hatch: task tool addition --raw-json-escape-hatch '{"x": 12, "y": 34}'
    """
    def fmt_err(cp: CompletedProcess):
        return f"Wrong output. {cp.stdout}\n{cp.stderr}"

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

        container_name = wait_for_container_name(capsys)
        docker_exec = ["docker", "exec", container_name, "bash", "-l", "-c"]
        wait_for_human_agent(docker_exec)

        try:
            # Test: task tool (list tools via argparse help)
            list_result = subprocess.run(
                docker_exec + ["python3 /opt/human_agent/task.py tool"],
                capture_output=True,
                text=True,
            )
            # argparse help shows tool names and descriptions
            assert """usage: task.py tool [-h] {addition} ...

positional arguments:
  {addition}
    addition  Add two numbers together.

options:
  -h, --help  show this help message and exit
""" in list_result.stdout, fmt_err(list_result)

            # Test: task tool addition --help (note this will clash with a tool argument called 'help')
            help_result = subprocess.run(
                docker_exec + ["python3 /opt/human_agent/task.py tool addition --help"],
                capture_output=True,
                text=True,
            )
            assert """usage: task.py tool addition [-h] --x X --y Y

options:
  -h, --help  show this help message and exit
  --x X       First number to add.
  --y Y       Second number to add.
""" in help_result.stdout, fmt_err(help_result)

            # Test: named args - task tool addition --x 12 --y 34
            named_result = subprocess.run(
                docker_exec
                + ["python3 /opt/human_agent/task.py tool addition --x 12 --y 34"],
                capture_output=True,
                text=True,
            )
            assert named_result.stdout.strip() == "46", fmt_err(named_result)

            # Test: JSON escape hatch
            json_result = subprocess.run(
                docker_exec
                + [
                    "python3 /opt/human_agent/task.py tool addition "
                    "--raw-json-escape-hatch '{\"x\": 12, \"y\": 34}'"
                ],
                capture_output=True,
                text=True,
            )
            assert json_result.stdout.strip() == "46"

            # Json escape hatch only applied to `task tool`, not to other commands
            invalid_json_result = subprocess.run(
                docker_exec
                + [
                    "python3 /opt/human_agent/task.py submit "
                    '--raw-json-escape-hatch \'{"answer": "test"}\''
                ],
                capture_output=True,
                text=True,
            )
            assert (
                "Error: --raw-json-escape-hatch requires: tool <name> --raw-json-escape-hatch '<json>'"
                in invalid_json_result.stdout
            )

        finally:
            # Always call task start/submit to unblock eval thread (otherwise test hangs!)
            subprocess.check_call(
                docker_exec + ["python3 /opt/human_agent/task.py start"]
            )
            subprocess.check_call(
                docker_exec
                + ['echo -e "y\\n" | python3 /opt/human_agent/task.py submit "done"'],
            )

        done, _ = concurrent.futures.wait([future], timeout=5)
        if future not in done:
            raise Exception("eval() did not complete within timeout")


@pytest.mark.slow
@skip_if_no_docker
def test_human_cli_with_tools_complex(capsys: pytest.CaptureFixture[str]):
    """Test human_cli with a tool that has complex types requiring JSON escape hatch.

    Complex types (dicts, nested objects) can't be mapped to argparse arguments,
    so users must use --raw-json-escape-hatch to pass them.
    """

    def fmt_err(cp: CompletedProcess):
        return f"Wrong output. {cp.stdout}\n{cp.stderr}"

    @tool
    def process_config():
        async def execute(config: dict, name: str) -> str:
            """Process a configuration object.

            Args:
                config: Configuration dictionary with settings.
                name: Name for the configuration.

            Returns:
                A summary of the configuration.
            """
            return f"{name}: {len(config)} settings"

        return execute

    def run_eval():
        task = Task(
            solver=human_cli(tools=[process_config()]),
            sandbox=(
                "docker",
                (Path(__file__).parent / "compose.human.yaml").as_posix(),
            ),
        )
        return eval(task, display="plain")[0]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(run_eval)

        container_name = wait_for_container_name(capsys)
        docker_exec = ["docker", "exec", container_name, "bash", "-l", "-c"]
        wait_for_human_agent(docker_exec)

        try:
            # Test: tool help shows epilog about complex parameters, no CLI args
            help_result = subprocess.run(
                docker_exec
                + ["python3 /opt/human_agent/task.py tool process_config --help"],
                capture_output=True,
                text=True,
            )
            # No CLI args shown - user must use escape hatch for all params
            assert "--name" not in help_result.stdout, fmt_err(help_result)
            assert "--config" not in help_result.stdout, fmt_err(help_result)
            assert "This tool has complex parameters. You must use --raw-json-escape-hatch" in help_result.stdout, fmt_err(help_result)

            # Test: calling with JSON escape hatch works
            json_result = subprocess.run(
                docker_exec
                + [
                    "python3 /opt/human_agent/task.py tool process_config "
                    '--raw-json-escape-hatch \'{"config": {"a": 1, "b": 2}, "name": "test"}\''
                ],
                capture_output=True,
                text=True,
            )
            assert json_result.stdout.strip() == "test: 2 settings", fmt_err(json_result)

        finally:
            # Always call task start/submit to unblock eval thread (otherwise test hangs!)
            subprocess.check_call(
                docker_exec + ["python3 /opt/human_agent/task.py start"]
            )
            subprocess.check_call(
                docker_exec
                + ['echo -e "y\\n" | python3 /opt/human_agent/task.py submit "done"'],
            )

        done, _ = concurrent.futures.wait([future], timeout=5)
        if future not in done:
            raise Exception("eval() did not complete within timeout")
