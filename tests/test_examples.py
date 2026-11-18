import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

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
    ("options", "arguments", "decision"),
    [
        ({}, {"command": "ls -la /tmp"}, "approve"),
        ({}, {"command": "ls\ntouch x"}, "reject"),
        ({}, {"command": "echo $HOME"}, "reject"),
        ({}, {"command": "FOO=bar ls"}, "escalate"),
        ({}, {"command": "rm -rf x"}, "escalate"),
        ({}, {"other": "ls", "command": "rm -rf x"}, "escalate"),
        ({}, {"command": "git push"}, "escalate"),
        ({}, {"command": "git"}, "escalate"),
        ({}, {"command": "sudo ls"}, "reject"),
        ({"allow_sudo": "false"}, {"command": "sudo ls"}, "reject"),
        ({"allow_sudo": True}, {"command": "sudo rm -rf x"}, "escalate"),
    ],
)
async def test_approval_example_bash_allowlist(
    approval_example: ModuleType,
    options: dict[str, Any],
    arguments: dict[str, Any],
    decision: str,
) -> None:
    approve = approval_example.bash_allowlist(
        allowed_commands=["ls", "echo", "git"],
        command_specific_rules={"git": ["status"]},
        **options,
    )
    call = ToolCall(id="1", function="bash", arguments=arguments)
    approval = await approve("", call, ToolCallView(), [])
    assert approval.decision == decision


@pytest.mark.parametrize(
    ("options", "arguments", "decision"),
    [
        (
            {},
            {"code": "import math\nresult = math.factorial(5)\nprint(result)"},
            "approve",
        ),
        ({}, {"code": "import shutil\nshutil.rmtree('x')"}, "escalate"),
        ({}, {"code": "print(print.__self__)"}, "escalate"),
        ({}, {"code": "import math\nprint(math.__doc__)"}, "escalate"),
        ({}, {"code": "import math\nmath.pi = 3"}, "escalate"),
        ({}, {"code": "x = 1\nprint(x.real)"}, "escalate"),
        ({}, {"code": "x = eval\nprint(x)"}, "escalate"),
        ({}, {"code": "_x = 1"}, "escalate"),
        ({}, {"code": "print = 1"}, "escalate"),
        ({}, {"code": "import math\nmath = 1"}, "escalate"),
        ({}, {"code": "x = 1\nx()"}, "escalate"),
        ({}, {"code": "print(print)()"}, "escalate"),
        ({}, {"code": "x = [1]\nprint(x[0])"}, "escalate"),
        ({}, {"code": "def f():\n    pass"}, "escalate"),
        ({}, {"code": "import math as m"}, "escalate"),
        ({}, {"code": "import os.path"}, "escalate"),
        ({}, {"code": "# coding: utf-7\nprint(1)"}, "escalate"),
        ({}, {"code": "#!/usr/bin/python\n# coding=latin-1\nprint(1)"}, "escalate"),
        ({}, {"other": "print(1)", "code": "import shutil"}, "escalate"),
        # the default deny lists override the allowed lists
        ({}, {"code": "import os"}, "escalate"),
        ({}, {"code": "eval('1')"}, "escalate"),
        # a deny list in the configuration is applied
        ({"sensitive_modules": ["math"]}, {"code": "import math"}, "escalate"),
        ({"disallowed_builtins": ["print"]}, {"code": "print(1)"}, "escalate"),
    ],
)
async def test_approval_example_python_allowlist(
    approval_example: ModuleType,
    options: dict[str, Any],
    arguments: dict[str, Any],
    decision: str,
) -> None:
    approve = approval_example.python_allowlist(
        allowed_functions=["print", "eval"],
        allowed_modules=["math", "os", "os.path"],
        **options,
    )
    call = ToolCall(id="1", function="python", arguments=arguments)
    approval = await approve("", call, ToolCallView(), [])
    assert approval.decision == decision


def test_approval_example_rejects_malformed_config(
    approval_example: ModuleType,
) -> None:
    bash, python = approval_example.bash_allowlist, approval_example.python_allowlist
    with pytest.raises(TypeError, match="list of strings"):
        bash(allowed_commands="ls")
    with pytest.raises(TypeError, match="command_specific_rules must be a mapping"):
        bash(allowed_commands=["ls"], command_specific_rules=False)
    with pytest.raises(TypeError, match="list of strings"):
        python(allowed_functions=["print"], allowed_modules="math")
