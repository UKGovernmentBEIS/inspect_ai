"""Tests for the dependency cooldown in pyproject.toml and the CI jobs around it.

pyproject.toml holds back releases younger than seven days except for an
exempt list of packages, Dependabot applies the same cooldown and exemptions
to its uv.lock bumps, and the canary jobs in build.yml opt out of the cooldown
so they keep installing the newest releases.
"""

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


def uv_config() -> dict[str, Any]:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    config: dict[str, Any] = pyproject["tool"]["uv"]
    return config


def dependabot_uv() -> dict[str, Any]:
    config = yaml.safe_load((REPO / ".github" / "dependabot.yml").read_text())
    updates: list[dict[str, Any]] = config["updates"]
    (update,) = [u for u in updates if u["package-ecosystem"] == "uv"]
    return update


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


def test_dependabot_cooldown_matches_pyproject() -> None:
    config = uv_config()
    days = re.fullmatch(r"(\d+) days", config["exclude-newer"])
    assert days, config["exclude-newer"]
    cooldown = dependabot_uv()["cooldown"]
    assert cooldown["default-days"] == int(days.group(1))
    exempt = config["exclude-newer-package"]
    assert all(value is False for value in exempt.values())
    assert sorted(cooldown["exclude"]) == sorted(exempt)


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
