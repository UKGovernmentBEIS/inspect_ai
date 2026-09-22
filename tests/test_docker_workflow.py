"""Tests for the image selector step in .github/workflows/docker.yml.

The step maps the workflow_dispatch ``image`` input to a build-context path
and must refuse every other value before the Docker login and build steps.
The input reaches the shell only through a step environment variable, so
these tests extract the step from the workflow and run its script under bash
the way the runner does, with the variable set to each candidate value.
"""

import os
import pathlib
import subprocess
from typing import Any

import pytest
import yaml

WORKFLOW = pathlib.Path(__file__).parents[1] / ".github" / "workflows" / "docker.yml"
STEP_NAME = "Set build context path and image name"
IMAGE_INPUT_EXPRESSIONS = {"${{ github.event.inputs.image }}", "${{ inputs.image }}"}
IMAGE_CONTEXTS = {
    "inspect-computer-tool": "src/inspect_ai/tool/_tools/_computer/_resources",
    "inspect-tool-support": "src/inspect_tool_support",
}

# Values the selector must reject. Those that would run a command if the
# shell ever evaluated them create $CANARY, which the tests check for.
INVALID_IMAGES = [
    "",
    " inspect-computer-tool ",
    "inspect-computer-tool\n",
    "INSPECT-COMPUTER-TOOL",
    "'inspect-computer-tool'",
    "inspect-computer-tool*",
    "inspect-computer-tool|inspect-tool-support",
    "inspect-computer-tool\nBUILD_CONTEXT=/",
    "inspect-computer-tool\nEVIL=1",
    'inspect-computer-tool" ]] || touch "$CANARY"; [[ "x',
    'inspect-computer-tool"; touch "$CANARY"; echo "',
    'inspect-computer-tool; touch "$CANARY"',
    'inspect-computer-tool $(touch "$CANARY")',
    '$(touch "$CANARY")inspect-computer-tool',
    'inspect-computer-tool `touch "$CANARY"`',
    'inspect-tool-support && touch "$CANARY"',
]


def selector_step() -> dict[str, Any]:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["build-and-push"]["steps"]
    matching = [step for step in steps if step.get("name") == STEP_NAME]
    assert len(matching) == 1, f"expected exactly one step named {STEP_NAME!r}"
    return matching[0]


def image_variable(step: dict[str, Any]) -> str:
    """Name of the step environment variable that carries the image input."""
    names = [
        name
        for name, value in step.get("env", {}).items()
        if isinstance(value, str) and value.strip() in IMAGE_INPUT_EXPRESSIONS
    ]
    assert len(names) == 1, "the image input must reach the step via one env var"
    return names[0]


def run_selector(
    image: str, tmp_path: pathlib.Path
) -> tuple[subprocess.CompletedProcess[str], str, bool]:
    """Run the selector script as the runner would, with ``image`` as input.

    Returns the completed process, the resulting GITHUB_ENV contents, and
    whether the canary file was created.
    """
    step = selector_step()
    script = tmp_path / "step.sh"
    script.write_text(step["run"])
    github_env = tmp_path / "github_env"
    github_env.touch()
    canary = tmp_path / "canary"
    env = {
        "PATH": os.environ["PATH"],
        "GITHUB_ENV": str(github_env),
        "CANARY": str(canary),
        image_variable(step): image,
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result, github_env.read_text(), canary.exists()


def test_selector_does_not_interpolate_expressions_into_shell() -> None:
    step = selector_step()
    assert "${{" not in step["run"], (
        "the selector must read its input from an env var, not an expression"
    )
    assert "GITHUB_ENV" in step["run"]


@pytest.mark.parametrize("image,context", sorted(IMAGE_CONTEXTS.items()))
def test_selector_accepts_supported_images(
    image: str, context: str, tmp_path: pathlib.Path
) -> None:
    result, github_env, canary = run_selector(image, tmp_path)
    assert result.returncode == 0, result.stderr
    assert github_env == f"BUILD_CONTEXT={context}\n"
    assert not canary


@pytest.mark.parametrize("image", INVALID_IMAGES)
def test_selector_rejects_other_values(image: str, tmp_path: pathlib.Path) -> None:
    result, github_env, canary = run_selector(image, tmp_path)
    assert result.returncode != 0
    assert github_env == "", "a rejected value must not reach GITHUB_ENV"
    assert not canary, "a rejected value must never be executed"
    assert "\n" not in (result.stdout + result.stderr).rstrip("\n"), (
        "the rejected value must be printed on one escaped line"
    )
