import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from test_helpers.utils import run_example, skip_if_github_action

from inspect_ai.tool import ToolCall, ToolCallView
from inspect_ai.util import parse_compose_yaml


@skip_if_github_action
def test_examples():
    run_example(example="security_guide.py", model="mockllm/model")
    run_example(example="popularity.py", model="mockllm/model")


def test_http_proxy_example_disables_network_egress() -> None:
    compose_file = Path(__file__).parents[1] / "examples/http_proxy/compose.yaml"

    config = parse_compose_yaml(compose_file.as_posix())

    assert config.services["default"].network_mode == "none"


@pytest.fixture(scope="module")
def approval_example() -> ModuleType:
    path = Path(__file__).parents[1] / "examples/approval/approval.py"
    spec = importlib.util.spec_from_file_location("approval_example", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("arguments", "decision"),
    [
        ({"command": "ls -la /tmp"}, "approve"),
        ({"command": "ls\ntouch x"}, "reject"),
        ({"command": "ls; touch x"}, "reject"),
        ({"command": 'echo "hi"'}, "reject"),
        ({"command": "FOO=bar ls"}, "escalate"),
        ({"command": "rm -rf x"}, "escalate"),
        ({"other": "ls", "command": "rm -rf x"}, "escalate"),
    ],
)
async def test_approval_example_bash_allowlist(
    approval_example: ModuleType, arguments: dict[str, str], decision: str
) -> None:
    approve = approval_example.bash_allowlist(allowed_commands=["ls", "echo", "cat"])
    call = ToolCall(id="1", function="bash", arguments=arguments)
    approval = await approve("", call, ToolCallView(), [])
    assert approval.decision == decision


@pytest.mark.parametrize(
    ("code", "decision"),
    [
        ("import math\nresult = math.factorial(5)\nprint(result)", "approve"),
        ("import shutil\nshutil.rmtree('x')", "escalate"),
        ("print(print.__self__)", "escalate"),
        ("x = eval\nprint(x)", "escalate"),
        ("print = 1", "escalate"),
        ("from math import sqrt", "escalate"),
        ("# coding: utf-7\nprint(1)", "escalate"),
        ("print(", "reject"),
    ],
)
async def test_approval_example_python_allowlist(
    approval_example: ModuleType, code: str, decision: str
) -> None:
    approve = approval_example.python_allowlist(
        allowed_functions=["print"], allowed_modules=["math"]
    )
    call = ToolCall(id="1", function="python", arguments={"code": code})
    approval = await approve("", call, ToolCallView(), [])
    assert approval.decision == decision


def test_approval_example_rejects_string_for_list(approval_example: ModuleType) -> None:
    with pytest.raises(TypeError, match="list of strings"):
        approval_example.bash_allowlist(allowed_commands="ls")
    with pytest.raises(TypeError, match="list of strings"):
        approval_example.python_allowlist(
            allowed_functions=["print"], allowed_modules="math"
        )
