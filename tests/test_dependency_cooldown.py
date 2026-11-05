"""Tests for the dependency cooldown in pyproject.toml and the CI jobs around it.

pyproject.toml holds back releases younger than seven days, or six hours for a
list of model provider SDKs and Inspect packages. Dependabot applies the seven
days to its uv.lock bumps and leaves that list to uv, and every CI job installs
from a lockfile. The model-data sync script runs without pyproject.toml, so its
own metadata repeats the policy. Testing against the newest releases happens in
meridianlabs-ai/canaries, outside this repository.
"""

import ast
import json
import pathlib
import re
import tomllib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import yaml

REPO = pathlib.Path(__file__).parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
BUILD = WORKFLOWS / "build.yml"
# The shared install actions, pinned by SHA at each call site. The install
# commands themselves live in the actions repo, so these tests read the
# install-shape inputs of each call rather than the old `uv sync` run lines.
ACTIONS = "meridianlabs-ai/actions/"
INSTALL_ACTION = ACTIONS + "install-python-dependencies"
SETUP_UV_ACTION = ACTIONS + "setup-uv"
# Every install-python-dependencies call, keyed by (workflow, job), as the
# inputs that set what gets installed (install.sh reads these; python-version
# and actions-cache select the Python and the cache, not the install shape).
# The package job installs twice: the hashed build toolchain, then the locked
# dist extra for the check tools. No call is versions: unlocked: an unlocked
# install has no cooldown and belongs only in meridianlabs-ai/canaries.
INSTALL_CALLS = {
    ("build.yml", "mypy"): [{"versions": "locked"}],
    ("build.yml", "pre-commit"): [{"versions": "locked"}],
    ("build.yml", "test"): [
        {"versions": "locked", "also-install-without-deps": "./tests/test_package"}
    ],
    ("build.yml", "slow-tests"): [{"versions": "locked"}],
    ("build.yml", "slow-tool-tests-dev"): [{"versions": "locked"}],
    ("build.yml", "slow-tool-tests-release"): [{"versions": "locked"}],
    ("build.yml", "docs"): [
        {"versions": "locked", "extras": "doc", "default-dependency-groups": "exclude"}
    ],
    ("build.yml", "package"): [
        {
            "versions": "hashed-requirements",
            "requirements-file": "scripts/build-dist/requirements.txt",
            "environment-dir": "${{ runner.temp }}/build-env",
            "package-format": "wheels-only",
            "project-uv-settings": "ignore",
        },
        {
            "versions": "locked",
            "extras": "dist",
            "default-dependency-groups": "exclude",
            "project-install": "skip",
        },
    ],
    ("log_viewer.yml", "check-schema-and-types"): [{"versions": "locked"}],
    ("sandbox-tools-build.yml", "validate"): [{"versions": "locked"}],
    ("sync_model_data.yml", "generate"): [
        {
            "versions": "locked",
            "script": "src/inspect_ai/model/_model_data/sync_models.py",
            "project-uv-settings": "ignore",
        }
    ],
}
# Inputs that select the Python or the cache, not what the job installs.
NON_SHAPE_INPUTS = {"python-version", "actions-cache"}
SANDBOX_TOOLS_TEST_LOCK = "src/inspect_sandbox_tools/tests/requirements.txt"
PROVIDERS = REPO / "src" / "inspect_ai" / "model" / "_providers"
SYNC_MODELS = REPO / "src" / "inspect_ai" / "model" / "_model_data" / "sync_models.py"
DEPENDENCY_CHECKS = {"pip_dependency_error", "verify_required_version"}
# A direct dependency that providers need but that is not a provider SDK (see
# CONTRIBUTING.md). It keeps the seven-day cooldown.
PROVIDER_INFRASTRUCTURE = {"aiobotocore"}
# The cooldown for packages in exclude-newer-package, and how uv.lock records it.
EXEMPT_COOLDOWN = "6 hours"
EXEMPT_COOLDOWN_SPAN = "PT6H"


def uv_config() -> dict[str, Any]:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    config: dict[str, Any] = pyproject["tool"]["uv"]
    return config


def normalize(package: str) -> str:
    return re.sub(r"[-_.]+", "-", package).lower()


def direct_dependencies() -> set[str]:
    """Packages in the pyproject.toml `dependencies` or the `dev` extra."""
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    requirements = project["dependencies"] + project["optional-dependencies"]["dev"]
    return {
        normalize(re.split(r"[^A-Za-z0-9._-]", requirement, maxsplit=1)[0])
        for requirement in requirements
    }


def cooldown_days(exclude_newer: str) -> int:
    days = re.fullmatch(r"(\d+) days", exclude_newer)
    assert days, exclude_newer
    return int(days[1])


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


def all_configs() -> dict[str, dict[str, Any]]:
    return {
        path.name: yaml.safe_load(path.read_text())
        for path in sorted(WORKFLOWS.glob("*.yml"))
    }


def install_shapes(job: dict[str, Any]) -> list[dict[str, Any]]:
    """The install-shape inputs of each install call in the job, in order."""
    return [
        {k: v for k, v in (step.get("with") or {}).items() if k not in NON_SHAPE_INPUTS}
        for step in job.get("steps", [])
        if step.get("uses", "").split("@")[0] == INSTALL_ACTION
    ]


def collected_install_calls(
    configs: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Install-shape inputs of every install call, keyed by (workflow, job)."""
    return {
        (workflow, name): shapes
        for workflow, config in configs.items()
        for name, job in config["jobs"].items()
        if (shapes := install_shapes(job))
    }


def verify_install_calls(configs: dict[str, dict[str, Any]]) -> None:
    assert collected_install_calls(configs) == INSTALL_CALLS


def shared_action_uses(configs: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Every step that calls a shared action: (workflow, uses ref)."""
    return [
        (workflow, uses)
        for workflow, config in configs.items()
        for job in config["jobs"].values()
        for step in job.get("steps", [])
        if (uses := step.get("uses", "")).split("@")[0].startswith(ACTIONS)
    ]


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
    return {normalize(package) for package in packages}


def test_provider_packages_are_exempt() -> None:
    packages = provider_packages()
    assert {"openai", "transformers", "vllm"} <= packages
    # Only direct dependencies can have the six-hour cooldown.
    missing = (
        (packages & direct_dependencies())
        - PROVIDER_INFRASTRUCTURE
        - set(uv_config()["exclude-newer-package"])
    )
    assert not missing, f"add to exclude-newer-package and Dependabot: {missing}"


def verify_exclude_newer_package(
    config: dict[str, Any], direct: set[str], now: datetime
) -> None:
    # Each entry is "6 hours" or a dated entry younger than the cooldown.
    max_age = timedelta(days=cooldown_days(config["exclude-newer"]))
    for package, cooldown in config["exclude-newer-package"].items():
        assert normalize(package) in direct, f"{package} is not a direct dependency"
        if cooldown != EXEMPT_COOLDOWN:
            age = now - datetime.fromisoformat(cooldown)
            assert timedelta(0) <= age < max_age, (
                f'dated entry {package} = "{cooldown}" is in the future or stale'
            )


def test_exclude_newer_package_entries() -> None:
    verify_exclude_newer_package(uv_config(), direct_dependencies(), datetime.now(UTC))


def test_non_direct_entry_is_caught() -> None:
    config = uv_config()
    config["exclude-newer-package"]["torch"] = EXEMPT_COOLDOWN
    with pytest.raises(AssertionError, match="not a direct dependency"):
        verify_exclude_newer_package(config, direct_dependencies(), datetime.now(UTC))


def test_fresh_dated_entry_passes() -> None:
    config = uv_config()
    now = datetime.now(UTC)
    config["exclude-newer-package"]["boto3"] = (now - timedelta(days=6)).isoformat()
    verify_exclude_newer_package(config, direct_dependencies(), now)
    verify_dependabot_cooldown(config, dependabot_uv())


def test_stale_dated_entry_is_caught() -> None:
    config = uv_config()
    now = datetime.now(UTC)
    config["exclude-newer-package"]["boto3"] = (now - timedelta(days=7)).isoformat()
    with pytest.raises(AssertionError, match="dated entry"):
        verify_exclude_newer_package(config, direct_dependencies(), now)


def test_future_dated_entry_is_caught() -> None:
    config = uv_config()
    now = datetime.now(UTC)
    config["exclude-newer-package"]["boto3"] = (now + timedelta(days=1)).isoformat()
    with pytest.raises(AssertionError, match="dated entry"):
        verify_exclude_newer_package(config, direct_dependencies(), now)


def test_other_cooldown_value_is_caught() -> None:
    config = uv_config()
    config["exclude-newer-package"]["boto3"] = "1 day"
    with pytest.raises(ValueError):
        verify_exclude_newer_package(config, direct_dependencies(), datetime.now(UTC))


def verify_dependabot_cooldown(
    config: dict[str, Any], dependabot: dict[str, Any]
) -> None:
    cooldown = dependabot["cooldown"]
    assert cooldown["default-days"] == cooldown_days(config["exclude-newer"])
    # Dependabot's cooldown counts whole days, so it leaves the "6 hours"
    # entries to uv. Dated entries are locked by hand.
    exempt = sorted(
        package
        for package, cooldown in config["exclude-newer-package"].items()
        if cooldown == EXEMPT_COOLDOWN
    )
    assert sorted(cooldown["exclude"]) == exempt
    # The exempt packages have their own group, listed before the catch-all.
    groups = dependabot["groups"]
    assert list(groups) == ["provider-sdks", "python-packages"]
    assert sorted(groups["provider-sdks"]["patterns"]) == exempt
    assert groups["python-packages"]["patterns"] == ["*"]


def test_dependabot_cooldown_matches_pyproject() -> None:
    verify_dependabot_cooldown(uv_config(), dependabot_uv())


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


def test_dependencies_are_declared_in_pyproject() -> None:
    # Dependabot's uv updater only updates uv.lock for dependencies declared in
    # pyproject.toml, not ones setuptools reads from requirements files.
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert pyproject["project"]["dynamic"] == ["version"]
    assert "dynamic" not in pyproject["tool"]["setuptools"]


def test_sync_models_script_follows_the_cooldown() -> None:
    config = uv_config()
    script = script_uv_config()
    lock = tomllib.loads((SYNC_MODELS.parent / "sync_models.py.lock").read_text())
    assert script["exclude-newer"] == config["exclude-newer"]
    # The script repeats the pyproject.toml entries for the packages it locks.
    locked = {package["name"] for package in lock["package"]}
    entries = {
        package: cooldown
        for package, cooldown in config["exclude-newer-package"].items()
        if normalize(package) in locked
    }
    assert script.get("exclude-newer-package", {}) == entries
    # The lock was written with these settings. The sync workflow's --locked run
    # runs weekly and accepts a lock written with an earlier timestamp.
    days = cooldown_days(script["exclude-newer"])
    assert lock["options"]["exclude-newer-span"] == f"P{days}D"
    # uv writes a dated entry as a UTC timestamp ending in "Z".
    options = lock["options"].get("exclude-newer-package", {})
    assert {
        package: datetime.fromisoformat(value) if isinstance(value, str) else value
        for package, value in options.items()
    } == {
        package: {"timestamp": "0001-01-01T00:00:00Z", "span": EXEMPT_COOLDOWN_SPAN}
        if cooldown == EXEMPT_COOLDOWN
        else datetime.fromisoformat(cooldown)
        for package, cooldown in entries.items()
    }


def version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_pinned_uv_versions_meet_required_version() -> None:
    required = re.fullmatch(r">=(\d+\.\d+\.\d+)", uv_config()["required-version"])
    assert required, uv_config()["required-version"]
    # Only build.yml still pins uv directly (sandbox-tools-unit installs uv
    # outside the shared action); every other install gets uv from the shared
    # setup-uv action. A test in the actions repo checks that pin against a
    # fixed floor (0.13.5), not against this repository's required-version.
    # Removing the local pins keeps one source of truth for the uv version per
    # install path. So, before a required-version increase, the shared
    # setup-uv action must release a uv that meets it. This test does not
    # check that. The sync_model_data generate job also does not catch a miss:
    # it runs uv with --no-config, so uv does not read required-version there.
    pin = yaml.safe_load((WORKFLOWS / "build.yml").read_text())["env"]["UV_VERSION"]
    assert version(pin) >= version(required[1]), f"build.yml: uv {pin}"
    for workflow in [
        "log_viewer.yml",
        "sandbox-tools-build.yml",
        "suppressions.yml",
        "suppressions-comment.yml",
        "sync_model_data.yml",
    ]:
        env = yaml.safe_load((WORKFLOWS / workflow).read_text()).get("env") or {}
        assert "UV_VERSION" not in env, workflow


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
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    requirements = pyproject["project"]["optional-dependencies"]["dev"]
    for tool in ["pre-commit-hooks", "ruff", "typos"]:
        assert any(re.fullmatch(rf"{tool}==[\d.]+", line) for line in requirements)


def test_no_workflow_uses_the_pre_commit_action() -> None:
    # pre-commit/action pip-installs the newest pre-commit, outside uv.lock.
    for workflow in WORKFLOWS.glob("*.yml"):
        assert "pre-commit/action" not in workflow.read_text(), workflow.name


@pytest.mark.parametrize("key,expected", INSTALL_CALLS.items())
def test_install_jobs_declare_their_versions(
    key: tuple[str, str], expected: list[dict[str, Any]]
) -> None:
    # Per-job check for a readable failure; test_every_install_call_is_covered
    # also catches a new or moved call the parametrize list would miss.
    assert collected_install_calls(all_configs()).get(key) == expected


def test_every_install_call_is_covered() -> None:
    verify_install_calls(all_configs())


def test_removed_install_call_is_caught() -> None:
    configs = all_configs()
    steps = configs["log_viewer.yml"]["jobs"]["check-schema-and-types"]["steps"]
    steps[:] = [s for s in steps if s.get("uses", "").split("@")[0] != INSTALL_ACTION]
    with pytest.raises(AssertionError):
        verify_install_calls(configs)


def verify_shared_action_pins(configs: dict[str, dict[str, Any]]) -> None:
    # All shared-action calls use one 40-character SHA. This check does not
    # make sure that the SHA is on meridianlabs-ai/actions main; a reviewer
    # does that.
    refs = set()
    for where, uses in shared_action_uses(configs):
        ref = uses.split("@", 1)[1] if "@" in uses else ""
        assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{where}: {uses} is not SHA-pinned"
        refs.add(ref)
    assert refs, "no shared-action calls found"
    assert len(refs) == 1, f"shared actions pinned to several SHAs: {sorted(refs)}"


def test_shared_action_calls_pin_one_sha() -> None:
    verify_shared_action_pins(all_configs())


def test_shared_action_call_on_a_second_sha_is_caught() -> None:
    configs = all_configs()
    steps = configs["log_viewer.yml"]["jobs"]["check-schema-and-types"]["steps"]
    step = next(s for s in steps if s.get("uses", "").startswith(ACTIONS))
    step["uses"] = step["uses"].split("@")[0] + "@" + "0" * 40
    with pytest.raises(AssertionError):
        verify_shared_action_pins(configs)


def verify_uv_cache_prunes(configs: dict[str, dict[str, Any]]) -> None:
    # setup-uv makes an Action save with actions-cache: read-write (the
    # default); without a prune the saved uv cache grows unbounded.
    for workflow, config in configs.items():
        for name, job in config["jobs"].items():
            calls = [
                step.get("with") or {}
                for step in job.get("steps", [])
                if step.get("uses", "").split("@")[0]
                in (INSTALL_ACTION, SETUP_UV_ACTION)
            ]
            if not any(
                c.get("actions-cache", "read-write") == "read-write" for c in calls
            ):
                continue
            runs = [step.get("run", "") for step in job["steps"]]
            assert any("uv cache prune --ci" in run for run in runs), (
                f"{workflow}:{name}"
            )


def test_read_write_jobs_prune_the_uv_cache() -> None:
    verify_uv_cache_prunes(all_configs())


def test_read_write_job_without_a_prune_is_caught() -> None:
    configs = all_configs()
    steps = configs["log_viewer.yml"]["jobs"]["check-schema-and-types"]["steps"]
    steps[:] = [s for s in steps if "uv cache prune --ci" not in s.get("run", "")]
    with pytest.raises(AssertionError):
        verify_uv_cache_prunes(configs)


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


def test_ruff_action_pins_ruff_by_version_file() -> None:
    # ruff-action must read the ruff pin from pyproject.toml. A `version` input
    # in place of version-file would replace the pin.
    steps = [
        step
        for step in build_job("ruff")["steps"]
        if step.get("uses", "").startswith("astral-sh/ruff-action@")
    ]
    assert len(steps) == 2, "expected the lint and format ruff-action steps"
    for step in steps:
        with_ = step.get("with", {})
        assert with_.get("version-file") == "pyproject.toml", step.get("name")
        assert "version" not in with_, step.get("name")


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
