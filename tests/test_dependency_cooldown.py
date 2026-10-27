"""Tests for the dependency cooldown in pyproject.toml and the CI jobs around it.

pyproject.toml holds back releases younger than seven days except for an
exempt list of packages that must include every model provider's own package,
Dependabot applies the same cooldown and exemptions
to its uv.lock bumps, and the canary jobs in build.yml opt out of the cooldown
so they keep installing the newest releases. The model-data sync script runs
without pyproject.toml, so its own metadata repeats the policy.
"""

import ast
import pathlib
import re
import tomllib
from typing import Any

import pytest
import yaml

REPO = pathlib.Path(__file__).parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
BUILD = WORKFLOWS / "build.yml"
LOCKED_JOBS = ["mypy", "test", "slow-tests", "slow-tool-tests-release"]
PROVIDERS = REPO / "src" / "inspect_ai" / "model" / "_providers"
SYNC_MODELS = REPO / "src" / "inspect_ai" / "model" / "_model_data" / "sync_models.py"
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
        for step in job.get("steps", [])
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
    dependabot = dependabot_uv()
    cooldown = dependabot["cooldown"]
    assert cooldown["default-days"] == int(days.group(1))
    exempt = config["exclude-newer-package"]
    assert all(value is False for value in exempt.values())
    assert sorted(cooldown["exclude"]) == sorted(exempt)
    # The exempt packages have their own group, listed before the catch-all.
    groups = dependabot["groups"]
    assert list(groups) == ["provider-sdks", "python-packages"]
    assert sorted(groups["provider-sdks"]["patterns"]) == sorted(exempt)
    assert groups["python-packages"]["patterns"] == ["*"]


def script_uv_config() -> dict[str, Any]:
    block = re.search(
        r"^# /// script$\n(.*?)^# ///$", SYNC_MODELS.read_text(), re.M | re.S
    )
    assert block
    lines = [line.removeprefix("#").removeprefix(" ") for line in block[1].splitlines()]
    config: dict[str, Any] = tomllib.loads("\n".join(lines))["tool"]["uv"]
    return config


def test_sync_models_script_follows_the_cooldown() -> None:
    config = uv_config()
    script = script_uv_config()
    lock = tomllib.loads((SYNC_MODELS.parent / "sync_models.py.lock").read_text())
    assert script["exclude-newer"] == config["exclude-newer"]
    # The script exempts the packages it locks that pyproject.toml exempts.
    locked = {package["name"] for package in lock["package"]}
    exempt = locked & set(config["exclude-newer-package"])
    assert "certifi" in exempt
    assert script["exclude-newer-package"] == dict.fromkeys(exempt, False)
    # The lock was written with these settings.
    days = re.fullmatch(r"(\d+) days", script["exclude-newer"])
    assert days
    assert lock["options"]["exclude-newer-span"] == f"P{days[1]}D"
    assert lock["options"]["exclude-newer-package"] == script["exclude-newer-package"]


def version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_pinned_uv_versions_meet_required_version() -> None:
    required = re.fullmatch(r">=(\d+\.\d+\.\d+)", uv_config()["required-version"])
    assert required, uv_config()["required-version"]
    pinned = {
        workflow: yaml.safe_load(
            (REPO / ".github" / "workflows" / workflow).read_text()
        )["env"]["UV_VERSION"]
        for workflow in [
            "build.yml",
            "log_viewer.yml",
            "sandbox-tools-build.yml",
            "suppressions.yml",
            "suppressions-comment.yml",
            "sync_model_data.yml",
        ]
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


def workflow_run_lines() -> list[tuple[str, str]]:
    return [
        (f"{path.name}:{name}", line)
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for name, job in yaml.safe_load(path.read_text())["jobs"].items()
        for line in run_lines(job)
    ]


# A bare `uv run` or `uv sync` re-resolves an out-of-date uv.lock and installs
# the result. `uv run --no-project` ignores the project and uv.lock. `--with`
# installs unlocked packages whatever the other flags.
def test_uv_never_relocks() -> None:
    unlocked = [
        (where, line)
        for where, line in workflow_run_lines()
        if re.search(r"\buv (run|sync)\b", line)
        and (
            "--with" in line
            or not {"--locked", "--no-sync", "--no-project"} & set(line.split())
        )
    ]
    assert unlocked == []


# pip installs skip uv.lock, so only the canaries' floating installs and
# dependency-free installs of local packages may use them.
def test_pip_installs_are_canaries_or_dependency_free() -> None:
    unlocked = [
        (where, line)
        for where, line in workflow_run_lines()
        if re.search(r"\bpip3? install\b", line)
        and "--exclude-newer false" not in line
        and "--no-deps" not in line.split()
    ]
    assert unlocked == []


def canary_jobs() -> list[tuple[str, str]]:
    return [
        (path.name, name)
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for name, job in yaml.safe_load(path.read_text())["jobs"].items()
        if any("--exclude-newer false" in line for line in run_lines(job))
    ]


def test_canary_jobs_are_found() -> None:
    assert {
        ("build.yml", "docs"),
        ("build.yml", "sandbox-tools-unit"),
        ("build.yml", "slow-tool-tests-dev"),
    } <= set(canary_jobs())


# Keeps honest canary runs from putting unvetted releases into the cache. A
# malicious release can still write to it, so jobs that hold credentials
# restore no cache (test_workflow_cache.py).
@pytest.mark.parametrize("workflow,name", canary_jobs())
def test_canary_jobs_float_without_secrets_or_cache_saves(
    workflow: str, name: str
) -> None:
    job = yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][name]
    installs = [line for line in run_lines(job) if line.startswith("uv pip install")]
    assert installs
    assert all("--exclude-newer false" in line for line in installs)
    (setup_uv,) = [
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("astral-sh/setup-uv@")
    ]
    assert setup_uv["with"]["save-cache"] is False
    assert "secrets" not in yaml.safe_dump(job)
