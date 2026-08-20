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

        done, _ = concurrent.futures.wait([future], timeout=20)
        if future in done:
            log = future.result()
            assert log.status == "success"
            assert log.samples[0].output.choices[0].message.content == "test"
        else:
            raise Exception("eval() did not complete within timeout")


@pytest.mark.slow
@skip_if_no_docker
def test_human_cli_submit_no_answer(capsys: pytest.CaptureFixture[str]):
    """Test that submitting without an answer completes the task when answer=False."""

    def run_eval():
        task = Task(
            solver=human_cli(answer=False),
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
        # Submit without an answer - this should complete the task when answer=False
        subprocess.check_call(
            docker_exec
            + [
                'echo -e "y\\n" | python3 /opt/human_agent/task.py submit',
            ],
        )

        done, _ = concurrent.futures.wait([future], timeout=5)
        if future in done:
            log = future.result()
            assert log.status == "success"
            assert log.samples[0].output.choices[0].message.content == ""
        else:
            raise Exception("eval() did not complete within timeout")


def fmt_err(cp: CompletedProcess) -> str:
    return f"Wrong output. {cp.stdout}\n{cp.stderr}"


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


def submit_task(docker_exec: list[str], answer: str = "done") -> None:
    subprocess.check_call(docker_exec + ["python3 /opt/human_agent/task.py start"])
    subprocess.check_call(
        docker_exec
        + [f'echo -e "y\\n" | python3 /opt/human_agent/task.py submit "{answer}"']
    )


@pytest.mark.slow
@skip_if_no_docker
def test_human_cli_with_tools(capsys: pytest.CaptureFixture[str]):
    """Test human_cli with tools parameter.

    Tests two argument styles:
    - Named: task tool addition --x 12 --y 34
    - JSON escape hatch: task tool addition --raw-json-escape-hatch '{"x": 12, "y": 34}'
    """

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
            assert (
                """usage: task.py tool [-h] {addition} ...

positional arguments:
  {addition}
    addition  Add two numbers together.

options:
  -h, --help  show this help message and exit
"""
                in list_result.stdout
            ), fmt_err(list_result)

            # Test: task tool addition --help (note this will clash with a tool argument called 'help')
            help_result = subprocess.run(
                docker_exec + ["python3 /opt/human_agent/task.py tool addition --help"],
                capture_output=True,
                text=True,
            )
            assert (
                """usage: task.py tool addition [-h] --x X --y Y

options:
  -h, --help  show this help message and exit
  --x X       First number to add.
  --y Y       Second number to add.
"""
                in help_result.stdout
            ), fmt_err(help_result)

            # Test: named args - task tool addition --x 12 --y 34
            named_result = subprocess.run(
                docker_exec
                + ["python3 /opt/human_agent/task.py tool addition --x 12 --y 34"],
                capture_output=True,
                text=True,
            )
            assert named_result.stdout.strip() == "46", fmt_err(named_result)

        finally:
            # Always call task start/submit to unblock eval thread (otherwise test hangs!)
            submit_task(docker_exec)

        done, _ = concurrent.futures.wait([future], timeout=5)
        if future not in done:
            raise Exception("eval() did not complete within timeout")
        # unwrap the future — a future completed with an exception is
        # "done", so done-ness alone hides eval failures
        log = future.result()
        assert log.status == "success", f"eval failed: {log.error}"


@pytest.mark.slow
@skip_if_no_docker
def test_human_cli_with_tools_complex(capsys: pytest.CaptureFixture[str]):
    """Test human_cli with a tool that has structured (JSON-valued) parameters.

    Complex types (dicts, nested objects) become ordinary named arguments
    whose values are JSON; simple parameters on the same tool stay typed flags.
    """

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
            # Test: help shows flags for both params, with a JSON example for
            # the structured one (no schema dump, no escape hatch)
            help_result = subprocess.run(
                docker_exec
                + ["python3 /opt/human_agent/task.py tool process_config --help"],
                capture_output=True,
                text=True,
            )
            assert "--name" in help_result.stdout, fmt_err(help_result)
            assert "--config JSON" in help_result.stdout, fmt_err(help_result)
            assert "e.g." in help_result.stdout, fmt_err(help_result)
            assert "escape-hatch" not in help_result.stdout, fmt_err(help_result)

            # Test: structured param passed as a JSON value alongside a plain flag
            json_result = subprocess.run(
                docker_exec
                + [
                    "python3 /opt/human_agent/task.py tool process_config "
                    '--name test --config \'{"a": 1, "b": 2}\''
                ],
                capture_output=True,
                text=True,
            )
            assert json_result.stdout.strip() == "test: 2 settings", fmt_err(
                json_result
            )

            # Test: malformed JSON is an immediate usage error naming the flag
            bad_json_result = subprocess.run(
                docker_exec
                + [
                    "python3 /opt/human_agent/task.py tool process_config "
                    "--name test --config '{not json'"
                ],
                capture_output=True,
                text=True,
            )
            assert bad_json_result.returncode == 2, fmt_err(bad_json_result)
            assert "invalid JSON" in bad_json_result.stderr, fmt_err(bad_json_result)

        finally:
            # Always call task start/submit to unblock eval thread (otherwise test hangs!)
            submit_task(docker_exec)

        done, _ = concurrent.futures.wait([future], timeout=5)
        if future not in done:
            raise Exception("eval() did not complete within timeout")
        # unwrap the future — a future completed with an exception is
        # "done", so done-ness alone hides eval failures
        log = future.result()
        assert log.status == "success", f"eval failed: {log.error}"


@pytest.mark.slow
@skip_if_no_docker
def test_human_cli_with_tools_no_args(capsys: pytest.CaptureFixture[str]):
    """Test human_cli with a tool that takes no arguments."""

    @tool
    def get_timestamp():
        async def execute() -> str:
            """Get the current timestamp.

            Returns:
                A fixed timestamp string for testing.
            """
            return "2024-01-01T00:00:00Z"

        return execute

    def run_eval():
        task = Task(
            solver=human_cli(tools=[get_timestamp()]),
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
            # Test: tool is listed
            list_result = subprocess.run(
                docker_exec + ["python3 /opt/human_agent/task.py tool"],
                capture_output=True,
                text=True,
            )
            assert "get_timestamp" in list_result.stdout, fmt_err(list_result)

            # Test: calling without arguments works
            call_result = subprocess.run(
                docker_exec + ["python3 /opt/human_agent/task.py tool get_timestamp"],
                capture_output=True,
                text=True,
            )
            assert call_result.stdout.strip() == "2024-01-01T00:00:00Z", fmt_err(
                call_result
            )

        finally:
            # Always call task start/submit to unblock eval thread (otherwise test hangs!)
            submit_task(docker_exec)

        done, _ = concurrent.futures.wait([future], timeout=5)
        if future not in done:
            raise Exception("eval() did not complete within timeout")
        # unwrap the future — a future completed with an exception is
        # "done", so done-ness alone hides eval failures
        log = future.result()
        assert log.status == "success", f"eval failed: {log.error}"


@pytest.mark.slow
@skip_if_no_docker
def test_human_cli_with_tools_boolean(capsys: pytest.CaptureFixture[str]):
    """Test human_cli with a tool that has boolean parameters."""

    @tool
    def format_text():
        async def execute(
            text: str, uppercase: bool = False, reverse: bool = True
        ) -> str:
            """Format text with various options.

            Args:
                text: The text to format.
                uppercase: Whether to convert to uppercase.
                reverse: Whether to reverse the text.

            Returns:
                The formatted text.
            """
            result = text
            if uppercase:
                result = result.upper()
            if reverse:
                result = result[::-1]
            return result

        return execute

    def run_eval():
        task = Task(
            solver=human_cli(tools=[format_text()]),
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
            # Test: without boolean flags, the tool's own defaults apply
            # (reverse defaults to True in the tool signature)
            no_flags_result = subprocess.run(
                docker_exec
                + ['python3 /opt/human_agent/task.py tool format_text --text "hello"'],
                capture_output=True,
                text=True,
            )
            assert no_flags_result.stdout.strip() == "olleh", fmt_err(no_flags_result)

            # Test: --no-reverse expresses False explicitly
            no_reverse_result = subprocess.run(
                docker_exec
                + [
                    'python3 /opt/human_agent/task.py tool format_text --text "hello" --no-reverse'
                ],
                capture_output=True,
                text=True,
            )
            assert no_reverse_result.stdout.strip() == "hello", fmt_err(
                no_reverse_result
            )

            # Test: with --uppercase flag, it becomes True
            uppercase_result = subprocess.run(
                docker_exec
                + [
                    'python3 /opt/human_agent/task.py tool format_text --text "hello" --uppercase'
                ],
                capture_output=True,
                text=True,
            )
            assert uppercase_result.stdout.strip() == "OLLEH", fmt_err(uppercase_result)

            # Test: with --reverse flag
            reverse_result = subprocess.run(
                docker_exec
                + [
                    'python3 /opt/human_agent/task.py tool format_text --text "hello" --reverse'
                ],
                capture_output=True,
                text=True,
            )
            assert reverse_result.stdout.strip() == "olleh", fmt_err(reverse_result)

            # Test: with both flags
            both_result = subprocess.run(
                docker_exec
                + [
                    'python3 /opt/human_agent/task.py tool format_text --text "hello" --uppercase --reverse'
                ],
                capture_output=True,
                text=True,
            )
            assert both_result.stdout.strip() == "OLLEH", fmt_err(both_result)

        finally:
            # Always call task start/submit to unblock eval thread (otherwise test hangs!)
            submit_task(docker_exec)

        done, _ = concurrent.futures.wait([future], timeout=5)
        if future not in done:
            raise Exception("eval() did not complete within timeout")
        # unwrap the future — a future completed with an exception is
        # "done", so done-ness alone hides eval failures
        log = future.result()
        assert log.status == "success", f"eval failed: {log.error}"
