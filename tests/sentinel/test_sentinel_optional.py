import subprocess
import sys
from pathlib import Path

# CI installs inspect_sentinel, so these run in a subprocess that hides it.
HIDE_SENTINEL = "import sys\nsys.modules['inspect_sentinel'] = None\n"

ROOT = Path(__file__).parents[2]


def run_without_sentinel(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", HIDE_SENTINEL + code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_sentinel_tests_skip_without_inspect_sentinel() -> None:
    result = run_without_sentinel(
        "import pytest\n"
        "sys.exit(pytest.main(['--collect-only', '-q', '-rs', '-p', 'no:cacheprovider', 'tests/sentinel']))\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    skipped = [
        line
        for line in result.stdout.splitlines()
        if "inspect_sentinel is not installed" in line
    ]
    for module in sorted(Path(__file__).parent.glob("test_*.py")):
        if module.name != Path(__file__).name:
            assert any(f"{module.name}:" in line for line in skipped), module.name


def test_eval_with_tool_calls_runs_without_inspect_sentinel(tmp_path: Path) -> None:
    result = run_without_sentinel(
        f"""
from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import Tool, tool


@tool
def addition() -> Tool:
    async def execute(x: int, y: int) -> str:
        \"\"\"Add two numbers.

        Args:
            x: First number to add.
            y: Second number to add.
        \"\"\"
        return str(x + y)

    return execute


model = get_model(
    "mockllm/model",
    custom_outputs=[
        ModelOutput.for_tool_call("mockllm/model", "addition", {{"x": 1, "y": 2}}),
        ModelOutput.from_content("mockllm/model", content="3"),
    ],
)
task = Task(
    dataset=[Sample(input="What is 1 + 2?")],
    solver=[use_tools(addition()), generate()],
)
log = eval(task, model=model, log_dir={str(tmp_path)!r}, display="none")[0]
assert log.status == "success", log.error.traceback if log.error else None
assert log.samples is not None
assert [m.text for m in log.samples[0].messages if m.role == "tool"] == ["3"]
"""
    )
    assert result.returncode == 0, result.stdout + result.stderr
