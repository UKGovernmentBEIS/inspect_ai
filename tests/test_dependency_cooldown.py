"""Tests for the dependency cooldown in pyproject.toml and the CI jobs around it.

pyproject.toml holds back releases younger than seven days except for an
exempt list of packages that must include every model provider's own package,
Dependabot applies the same cooldown and exemptions to its uv.lock bumps, and
every CI job installs from a lockfile. The model-data sync script runs without
pyproject.toml, so its own metadata repeats the policy. Testing against the
newest releases happens in meridianlabs-ai/canaries, outside this repository.
"""

import ast
import json
import pathlib
import re
import tomllib
from typing import Any

import pytest
import yaml

REPO = pathlib.Path(__file__).parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
BUILD = WORKFLOWS / "build.yml"
LOCKED_JOBS = {
    "mypy": "uv sync --locked",
    "pre-commit": "uv sync --locked",
    "test": "uv sync --locked",
    "slow-tests": "uv sync --locked",
    "slow-tool-tests-dev": "uv sync --locked",
    "slow-tool-tests-release": "uv sync --locked",
    "docs": "uv sync --locked --extra doc --no-default-groups",
    "package": "uv sync --locked --no-default-groups --extra dist --no-install-project",
}
SANDBOX_TOOLS_TEST_LOCK = "src/inspect_sandbox_tools/tests/requirements.txt"
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
    # Joins backslash continuations so a command's flags stay on one line.
    return [
        line.strip()
        for step in job.get("steps", [])
        for line in step.get("run", "").replace("\\\n", " ").splitlines()
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


def test_setuptools_scm_fallback_version_is_the_released_version() -> None:
    # Dependabot's uv.lock bumps need it; see the comment in pyproject.toml.
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    manifest = json.loads((REPO / ".release-please-manifest.json").read_text())
    assert pyproject["tool"]["setuptools_scm"]["fallback_version"] == manifest["."]


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
    devcontainer = (REPO / ".devcontainer" / "Dockerfile").read_text()
    devcontainer_uv = re.search(r"^ARG UV_VERSION=(\S+)$", devcontainer, re.M)
    assert devcontainer_uv
    pinned["devcontainer"] = devcontainer_uv[1]
    for where, pin in pinned.items():
        assert version(pin) >= version(required[1]), f"{where}: uv {pin}"


def test_no_workflow_uses_the_build_and_inspect_action() -> None:
    # hynek/build-and-inspect-python-package installs the newest uv with
    # curl | bash and apt-installs tree.
    for path in (REPO / ".github").rglob("*.y*ml"):
        assert "build-and-inspect-python-package" not in path.read_text(), path


def test_pre_commit_hooks_run_locked_tools() -> None:
    # A hook repo would make pre-commit install the hook's tool and its
    # dependencies itself, outside uv.lock and the cooldown.
    config = yaml.safe_load((REPO / ".pre-commit-config.yaml").read_text())
    for repo in config["repos"]:
        assert repo["repo"] == "local", repo["repo"]
        for hook in repo["hooks"]:
            assert hook["language"] == "unsupported", hook["id"]
            if hook["id"] == "uv-lock":
                assert hook["entry"] == "uv lock"
            else:
                assert hook["entry"].startswith("uv run --frozen "), hook["id"]
    requirements = (REPO / "requirements-dev.txt").read_text().splitlines()
    for tool in ["pre-commit-hooks", "ruff", "typos"]:
        assert any(re.fullmatch(rf"{tool}==[\d.]+", line) for line in requirements)


def test_no_workflow_uses_the_pre_commit_action() -> None:
    # pre-commit/action pip-installs the newest pre-commit, outside uv.lock.
    for workflow in WORKFLOWS.glob("*.yml"):
        assert "pre-commit/action" not in workflow.read_text(), workflow.name


@pytest.mark.parametrize("name,sync", LOCKED_JOBS.items())
def test_locked_jobs_install_from_the_lockfile(name: str, sync: str) -> None:
    syncs = [line for line in run_lines(build_job(name)) if line.startswith("uv sync")]
    assert syncs == [sync]


def test_sandbox_tools_unit_installs_from_its_hashed_lock() -> None:
    installs = [
        line
        for line in run_lines(build_job("sandbox-tools-unit"))
        if line.startswith("uv pip")
    ]
    assert installs == [
        f"uv pip sync --require-hashes {SANDBOX_TOOLS_TEST_LOCK}",
        "uv pip install --no-deps ./src/inspect_sandbox_tools",
    ]


def workflow_run_lines() -> list[tuple[str, str]]:
    lines = [
        (f"{path.name}:{name}", line)
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for name, job in yaml.safe_load(path.read_text())["jobs"].items()
        for line in run_lines(job)
    ]
    for path in sorted((REPO / ".github" / "actions").glob("*/action.yml")):
        runs = yaml.safe_load(path.read_text())["runs"]
        lines += [(f"{path.parent.name}/action.yml", line) for line in run_lines(runs)]
    return lines


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


# pip installs skip uv.lock, so they may only add local packages without their
# dependencies, or install a hashed lock (`-r` or `uv pip sync`).
def test_pip_installs_are_dependency_free_or_hashed() -> None:
    unlocked = [
        (where, line)
        for where, line in workflow_run_lines()
        if (re.search(r"\bpip3? install\b", line) and "--no-deps" not in line.split())
        or (
            re.search(r"\bpip sync\b|\bpip3? install\b.* -r\b", line)
            and "--require-hashes" not in line.split()
        )
    ]
    assert unlocked == []


def test_no_workflow_opts_out_of_the_cooldown() -> None:
    floating = [
        (where, line)
        for where, line in workflow_run_lines()
        if re.search(r"--exclude-newer(=|\s+)false", line)
    ]
    assert floating == []
