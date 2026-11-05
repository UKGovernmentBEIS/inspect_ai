import os
import subprocess
import sys
from pathlib import Path

import pytest

# Extension tests install a startup hook into this interpreter's environment.
ISOLATE_EXTENSIONS = (
    "from unittest.mock import patch; "
    "patch('inspect_ai._util.entrypoints.entry_points', return_value=[]).start(); "
)
CLI_ARGS = [
    "-c",
    ISOLATE_EXTENSIONS + "import runpy; "
    "runpy.run_module('inspect_ai._cli.main', run_name='__main__')",
]


@pytest.mark.parametrize("entrypoint", ["cli", "environment", "python"])
def test_quiet_display_reports_prerequisite_errors(
    entrypoint: str, tmp_path: Path
) -> None:
    env = {**os.environ, "INSPECT_EVAL_CTL_SERVER": "false"}
    expected = "No inspect tasks were found"
    args = [
        *CLI_ARGS,
        "eval",
        "missing.py",
        "--model",
        "mockllm/model",
    ]
    if entrypoint == "cli":
        args.extend(["--display", "none"])
    elif entrypoint == "environment":
        env["INSPECT_DISPLAY"] = "none"
    else:
        args = [
            "-c",
            ISOLATE_EXTENSIONS + "from inspect_ai import Task, eval; "
            "from inspect_ai.dataset import Sample; "
            "eval(Task(dataset=[Sample(input='hi')]), "
            "model='mockllm/model[dev]', cost_limit=1, display='none')",
        ]
        expected = "mockllm/model[dev]"

    result = subprocess.run(
        [sys.executable, *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert expected in result.stderr
    assert "Traceback" not in result.stderr


def test_quiet_prerequisite_error_uses_current_stderr(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ISOLATE_EXTENSIONS + "import sys; "
            "sys.stderr = open('errors.txt', 'w'); "
            "from inspect_ai import Task, eval; "
            "from inspect_ai.dataset import Sample; "
            "eval(Task(dataset=[Sample(input='hi')]), "
            "model='mockllm/model', cost_limit=1, display='none')",
        ],
        cwd=tmp_path,
        env={**os.environ, "INSPECT_EVAL_CTL_SERVER": "false"},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert result.stdout == result.stderr == ""
    assert "cost_limit requires cost data" in (tmp_path / "errors.txt").read_text()


@pytest.mark.parametrize("args", [["--display", "plain"], ["--no-ansi"]])
def test_nonquiet_prerequisite_error_keeps_rendering(
    args: list[str], tmp_path: Path
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            *CLI_ARGS,
            "eval",
            "missing.py",
            "--model",
            "mockllm/model",
            *args,
        ],
        cwd=tmp_path,
        env={**os.environ, "INSPECT_EVAL_CTL_SERVER": "false"},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert "No inspect tasks were found" in result.stdout
    assert result.stderr == ""
    assert "\x1b" not in result.stdout


def test_successful_quiet_eval_stays_silent(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ISOLATE_EXTENSIONS + "from inspect_ai import Task, eval; "
            "from inspect_ai.dataset import Sample; "
            "eval(Task(dataset=[Sample(input='hi')]), "
            "model='mockllm/model', display='none')",
        ],
        cwd=tmp_path,
        env={**os.environ, "INSPECT_EVAL_CTL_SERVER": "false"},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""
