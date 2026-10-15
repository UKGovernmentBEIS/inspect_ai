"""Tests for the pnpm invocations in .github/workflows/npm-publish.yml.

The release job selects the viewer package with ``pnpm --filter``. A filter
that matches no workspace package makes pnpm print "No projects matched the
filters" and exit 0, which turned the quality checks and the prerelease
library build into silent no-ops. These tests resolve every filter against
the ts-mono workspace, require ``--fail-if-no-match``, and check that the
gitignored CSS-module typings are generated before ``check-all`` runs tsc.
"""

import json
import pathlib
import shlex
from typing import Any

import pytest
import yaml

REPO = pathlib.Path(__file__).parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "npm-publish.yml"
TS_MONO = REPO / "src" / "inspect_ai" / "_view" / "ts-mono"

_submodule_missing = not (TS_MONO / "pnpm-workspace.yaml").exists()


def publish_steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps: list[dict[str, Any]] = workflow["jobs"]["publish"]["steps"]
    return steps


def pnpm_commands() -> list[list[str]]:
    """Every ``pnpm ...`` command line in the job's run scripts, tokenized."""
    commands = []
    for step in publish_steps():
        for line in step.get("run", "").splitlines():
            if line.strip().startswith("pnpm "):
                commands.append(shlex.split(line))
    return commands


def filter_selectors(command: list[str]) -> list[str]:
    """Package names selected by ``--filter`` in a pnpm command line.

    Strips the ``...`` dependency and ``^`` exclusion markers so that
    ``pkg...`` and ``^pkg`` resolve to ``pkg``.
    """
    selectors = []
    for i, token in enumerate(command):
        if token == "--filter" and i + 1 < len(command):
            selectors.append(command[i + 1])
        elif token.startswith("--filter="):
            selectors.append(token.removeprefix("--filter="))
    return [s.strip("^").removesuffix("...").removeprefix("...") for s in selectors]


def filtered_commands() -> list[list[str]]:
    commands = [c for c in pnpm_commands() if filter_selectors(c)]
    assert commands, "expected the publish job to filter pnpm to the viewer package"
    return commands


def workspace_package_names() -> set[str]:
    globs = yaml.safe_load((TS_MONO / "pnpm-workspace.yaml").read_text())["packages"]
    return {
        json.loads(pkg.read_text())["name"]
        for pattern in globs
        for pkg in TS_MONO.glob(f"{pattern}/package.json")
    }


@pytest.mark.skipif(_submodule_missing, reason="ts-mono submodule not initialized")
def test_filters_name_a_workspace_package() -> None:
    names = workspace_package_names()
    for command in filtered_commands():
        for selector in filter_selectors(command):
            assert selector in names, (
                f"{shlex.join(command)!r} filters on {selector!r}, which is not "
                f"a ts-mono workspace package; pnpm would silently run nothing"
            )


def test_filters_fail_if_no_match() -> None:
    for command in filtered_commands():
        assert "--fail-if-no-match" in command, (
            f"{shlex.join(command)!r} must fail loudly if its filter matches "
            f"no package instead of exiting 0 having run nothing"
        )


def test_css_typings_generated_before_checks() -> None:
    steps = publish_steps()
    checks = [i for i, s in enumerate(steps) if "check-all" in s.get("run", "")]
    assert len(checks) == 1, "expected exactly one step running check-all"
    generated = [i for i, s in enumerate(steps) if "generate:css" in s.get("run", "")]
    assert generated and generated[0] < checks[0], (
        "check-all runs tsc outside turbo, so the gitignored *.module.css.d.ts "
        "typings must be generated in an earlier step"
    )
