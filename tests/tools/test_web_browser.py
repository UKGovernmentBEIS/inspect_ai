import subprocess
import sys
from typing import Any

import pytest

import inspect_ai.tool as tool_module
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
    with pytest.raises(RuntimeError, match=r"web_browser\(\).*has been removed") as exc:
        web_browser(**kwargs)

    message = str(exc.value)
    assert "web_search()" in message
    assert "computer()" in message
    assert "mcp_server_sandbox()" in message
    assert "https://github.com/UKGovernmentBEIS/inspect_ai/issues/5497" in message


def test_web_browser_legacy_alias_removed() -> None:
    with pytest.raises(RuntimeError, match="has been removed"):
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
