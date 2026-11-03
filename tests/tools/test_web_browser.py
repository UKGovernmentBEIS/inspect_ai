import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

import inspect_ai.tool as tool_module
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool import web_browser


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"interactive": False},
        {"instance": "browser"},
        {"interactive": True, "instance": None},
        {"interactive": False, "instance": "browser"},
    ],
)
def test_web_browser_removed(kwargs: dict[str, Any]) -> None:
    with pytest.raises(
        PrerequisiteError, match=r"web_browser\(\).*has been removed"
    ) as exc:
        web_browser(**kwargs)

    message = str(exc.value)
    assert "web_search()" in message
    assert "computer()" in message
    assert "mcp_server_sandbox()" in message
    assert "https://github.com/UKGovernmentBEIS/inspect_ai/issues/5497" in message


def test_web_browser_legacy_alias_removed() -> None:
    with pytest.raises(PrerequisiteError, match="has been removed"):
        getattr(tool_module, "web_browser_tools")()


def test_web_browser_import_does_not_warn() -> None:
    """Task discovery can import the removed tool without constructing it."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging; logging.basicConfig(level=logging.WARNING); "
            "from inspect_ai.tool import web_browser",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "web_browser" not in result.stderr


@pytest.mark.parametrize("json_output", [False, True])
def test_web_browser_cli_reports_migration_without_traceback(
    tmp_path: Path, json_output: bool
) -> None:
    task_file = tmp_path / "removed_browser.py"
    task_file.write_text(
        dedent("""
        from inspect_ai import Task, task
        from inspect_ai.solver import use_tools
        from inspect_ai.tool import web_browser

        @task
        def removed_browser() -> Task:
            return Task(solver=use_tools(web_browser()))
        """)
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "inspect_ai",
            "eval",
            task_file.name,
            "--model",
            "mockllm/model",
            *(["--json"] if json_output else []),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "web_browser()" in output
    assert "has been removed" in output
    assert "web_search()" in output
    assert "https://github.com/UKGovernmentBEIS/inspect_ai/issues/5497" in output
    assert "Traceback" not in output
    if json_output:
        assert result.stdout == ""
