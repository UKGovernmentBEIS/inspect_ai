"""Tests for the dependency cooldown in pyproject.toml and the CI jobs around it.

pyproject.toml holds back releases younger than seven days except for an
exempt list of packages that must include every model provider's own package,
Dependabot applies the same cooldown and exemptions
to its uv.lock bumps, and the canary jobs in build.yml opt out of the cooldown
so they keep installing the newest releases.
"""

import ast
import pathlib
import re
import tomllib
from typing import Any

import pytest
import yaml

REPO = pathlib.Path(__file__).parents[1]
BUILD = REPO / ".github" / "workflows" / "build.yml"
CANARY_JOBS = ["docs", "sandbox-tools-unit", "slow-tool-tests-dev"]
LOCKED_JOBS = ["mypy", "test"]
PROVIDERS = REPO / "src" / "inspect_ai" / "model" / "_providers"
DEPENDENCY_CHECKS = {"pip_dependency_error", "verify_required_version"}
# Packages providers need that aren't the provider's own SDK or integration
# package. These stay under the cooldown.
PROVIDER_INFRASTRUCTURE = {"accelerate", "torch"}


def uv_config() -> dict[str, Any]:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    config: dict[str, Any] = pyproject["tool"]["uv"]
    return config


def dependabot_uv() -> dict[str, Any]:
    config = yaml.safe_load((REPO / ".github" / "dependabot.yml").read_text())
    updates: list[dict[str, Any]] = config["updates"]
    root = [
        u for u in updates if u["package-ecosystem"] == "uv" and u["directory"] == "/"
    ]
    assert len(root) == 1, "expected one uv entry for directory / in dependabot.yml"
    return root[0]


def build_job(name: str) -> dict[str, Any]:
    job: dict[str, Any] = yaml.safe_load(BUILD.read_text())["jobs"][name]
    return job


def run_lines(job: dict[str, Any]) -> list[str]:
    return [
        line.strip()
        for step in job["steps"]
        for line in step.get("run", "").splitlines()
        if line.strip()
    ]


def provider_packages() -> set[str]:
    packages: set[str] = set()
    for path in PROVIDERS.rglob("*.py"):
        for func in ast.walk(ast.parse(path.read_text())):
            if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            constants = {
                target.id: node.value.value
                for node in ast.walk(func)
                if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            for call in ast.walk(func):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id in DEPENDENCY_CHECKS
                ):
                    continue
                arg = call.args[1]
                names = arg.elts if isinstance(arg, ast.List) else [arg]
                for name in names:
                    if isinstance(name, ast.Constant) and isinstance(name.value, str):
                        packages.add(name.value)
                    else:
                        assert isinstance(name, ast.Name) and name.id in constants, (
                            f"{path}:{call.lineno}: can't resolve the package name"
                        )
                        packages.add(constants[name.id])
    return {re.sub(r"[-_.]+", "-", package).lower() for package in packages}


def test_provider_packages_are_exempt() -> None:
    packages = provider_packages()
    assert {"openai", "transformers", "vllm"} <= packages
    missing = (
        packages - PROVIDER_INFRASTRUCTURE - set(uv_config()["exclude-newer-package"])
    )
    assert not missing, f"add to exclude-newer-package and Dependabot: {missing}"


def test_dependabot_cooldown_matches_pyproject() -> None:
    config = uv_config()
    days = re.fullmatch(r"(\d+) days", config["exclude-newer"])
    assert days, config["exclude-newer"]
    cooldown = dependabot_uv()["cooldown"]
    assert cooldown["default-days"] == int(days.group(1))
    exempt = config["exclude-newer-package"]
    assert all(value is False for value in exempt.values())
    assert sorted(cooldown["exclude"]) == sorted(exempt)


def version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_pinned_uv_versions_meet_required_version() -> None:
    required = re.fullmatch(r">=(\d+\.\d+\.\d+)", uv_config()["required-version"])
    assert required, uv_config()["required-version"]
    pinned = {
        workflow: yaml.safe_load(
            (REPO / ".github" / "workflows" / workflow).read_text()
        )["env"]["UV_VERSION"]
        for workflow in ["build.yml", "log_viewer.yml", "sync_model_data.yml"]
    }
    pre_commit = yaml.safe_load((REPO / ".pre-commit-config.yaml").read_text())
    (pinned["pre-commit"],) = [
        repo["rev"] for repo in pre_commit["repos"] if "uv-pre-commit" in repo["repo"]
    ]
    devcontainer = (REPO / ".devcontainer" / "Dockerfile").read_text()
    devcontainer_uv = re.search(r"^ARG UV_VERSION=(\S+)$", devcontainer, re.M)
    assert devcontainer_uv
    pinned["devcontainer"] = devcontainer_uv[1]
    for where, pin in pinned.items():
        assert version(pin) >= version(required[1]), f"{where}: uv {pin}"


@pytest.mark.parametrize("name", LOCKED_JOBS)
def test_locked_jobs_install_from_the_lockfile(name: str) -> None:
    syncs = [line for line in run_lines(build_job(name)) if line.startswith("uv sync")]
    assert syncs == ["uv sync --locked"]


@pytest.mark.parametrize("name", CANARY_JOBS)
def test_canary_jobs_float_without_secrets_or_cache_saves(name: str) -> None:
    job = build_job(name)
    installs = [line for line in run_lines(job) if line.startswith("uv pip install")]
    assert installs
    assert all("--exclude-newer false" in line for line in installs)
    (setup_uv,) = [
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("astral-sh/setup-uv@")
    ]
    assert setup_uv["with"]["save-cache"] is False
    assert "secrets." not in yaml.safe_dump(job)
