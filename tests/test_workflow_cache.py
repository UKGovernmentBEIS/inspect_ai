"""Cache safety for the shared-action call sites.

Jobs that hold credentials restore no cache, and every job that does not save
to the Actions cache declares a cache-mode.

A malicious package installed by any job can write to the shared Actions
cache, so a job holding secrets, an id-token or write permissions must not
restore one. The shared install actions move the uv setup behind a call, so a
call counts as a restore from the Actions cache unless it sets
actions-cache: none.

cache-mode, which the Actions cache enforces, is the only setting that stops a
write by any step holding the Actions cache token (save-cache: false stops only
setup-uv's own Action save). So a job whose shared-action call does not save
(actions-cache none or restore-only) also declares a cache-mode, except docs,
whose actions/cache step writes a render marker a cache-mode would block.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
INSTALL_ACTION = "meridianlabs-ai/actions/install-python-dependencies"
SETUP_UV_ACTION = "meridianlabs-ai/actions/setup-uv"
SHARED_ACTIONS = {INSTALL_ACTION, SETUP_UV_ACTION}

CREDENTIAL_JOBS = [
    ("suppressions-comment.yml", "comment"),
    ("sync_model_data.yml", "generate"),
    ("sync_model_data.yml", "open-pr"),
    ("docker.yml", "build-and-push"),
    ("publish.yml", "build"),
    ("publish.yml", "publish"),
    ("release.yml", "build"),
    ("release.yml", "publish-pypi"),
    ("npm-publish.yml", "build"),
    ("npm-publish.yml", "publish"),
    # Builds released binaries; attest signs whatever build uploaded.
    ("sandbox-tools-build.yml", "build"),
    ("sandbox-tools-build.yml", "attest"),
    ("sandbox-tools-build.yml", "validate"),
]

# The cache-mode each job that does not save to the Actions cache must declare.
# actions-cache none -> cache-mode none; restore-only -> a cache-mode that
# blocks a write (slow-tool-tests-dev uses read). docs is the one restore-only
# job with no cache-mode (see the module docstring).
CACHE_MODE_JOBS = {
    ("sandbox-tools-build.yml", "validate"): "none",
    ("sync_model_data.yml", "generate"): "none",
    ("suppressions.yml", "suppressions"): "none",
    ("suppressions-comment.yml", "comment"): "none",
    ("build.yml", "slow-tool-tests-dev"): "read",
}
NO_CACHE_MODE_JOBS = {("build.yml", "docs")}


def load(workflow: str) -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load((WORKFLOWS / workflow).read_text())
    return config


def all_configs() -> dict[str, dict[str, Any]]:
    return {
        path.name: yaml.safe_load(path.read_text()) for path in WORKFLOWS.glob("*.yml")
    }


def job_steps(workflow: str, job: str) -> list[dict[str, Any]]:
    config = load(workflow)
    steps: list[dict[str, Any]] = []
    for step in config["jobs"][job]["steps"]:
        steps.append(step)
        # The build-dist and publish-dist composite actions (in this repo).
        if ".github/actions/" in step.get("uses", ""):
            action = REPO / ".github" / "actions" / step["uses"].split("/")[-1]
            steps += yaml.safe_load((action / "action.yml").read_text())["runs"][
                "steps"
            ]
    return steps


def assert_restores_no_cache(steps: list[dict[str, Any]]) -> None:
    for step in steps:
        action = step.get("uses", "").split("@")[0]
        inputs = step.get("with") or {}
        assert action not in {"actions/cache", "actions/cache/restore"}
        # A shared-action call restores from the Actions cache unless it opts
        # out with actions-cache: none.
        if action in SHARED_ACTIONS:
            assert inputs.get("actions-cache") == "none", action
        if action == "astral-sh/setup-uv":
            assert inputs.get("enable-cache") is False
        if action == "actions/setup-python":
            assert "cache" not in inputs
        if action == "actions/setup-node":
            assert "cache" not in inputs
            assert inputs.get("package-manager-cache") is False
        if action == "docker/setup-qemu-action":
            assert inputs.get("cache-image") is False
        if action == "docker/setup-buildx-action":
            assert inputs.get("cache-binary") is False
        if action == "docker/build-push-action":
            assert "cache-from" not in inputs


@pytest.mark.parametrize("workflow,job", CREDENTIAL_JOBS)
def test_credential_holding_jobs_restore_no_cache(workflow: str, job: str) -> None:
    assert_restores_no_cache(job_steps(workflow, job))


def test_shared_action_restore_without_actions_cache_none_is_caught() -> None:
    # A privileged job that calls the shared action with the default
    # actions-cache (read-write) restores from the Actions cache, so the check
    # must reject it.
    bad = [
        {
            "uses": f"{INSTALL_ACTION}@{'0' * 40}",
            "with": {"versions": "locked", "python-version": "3.11"},
        }
    ]
    with pytest.raises(AssertionError):
        assert_restores_no_cache(bad)


def effective_cache_mode(config: dict[str, Any], job_name: str) -> str | None:
    job = config["jobs"][job_name]
    if "cache-mode" in job:
        mode: str = job["cache-mode"]
        return mode
    workflow_mode: str | None = config.get("cache-mode")
    return workflow_mode


def job_actions_cache(job: dict[str, Any]) -> str | None:
    """The actions-cache of the job's first shared-action call, or None."""
    for step in job.get("steps", []):
        if step.get("uses", "").split("@")[0] in SHARED_ACTIONS:
            inputs = step.get("with") or {}
            cache: str = inputs.get("actions-cache", "read-write")
            return cache
    return None


def verify_cache_modes(configs: dict[str, dict[str, Any]]) -> None:
    for workflow, config in configs.items():
        for job_name, job in config["jobs"].items():
            actions_cache = job_actions_cache(job)
            if actions_cache is None:
                continue
            mode = effective_cache_mode(config, job_name)
            key = (workflow, job_name)
            if actions_cache == "none":
                assert mode == "none", (
                    f"{key}: actions-cache none needs cache-mode none"
                )
            elif actions_cache == "restore-only":
                if key in NO_CACHE_MODE_JOBS:
                    assert mode is None, f"{key}: expected no cache-mode, got {mode}"
                else:
                    assert mode in ("read", "none"), (
                        f"{key}: restore-only job needs cache-mode read or none, "
                        f"got {mode}"
                    )
            # read-write saves, so it needs no cache-mode.
    # The specific values the plan fixes.
    for (workflow, job_name), expected in CACHE_MODE_JOBS.items():
        got = effective_cache_mode(configs[workflow], job_name)
        assert got == expected, (
            f"{(workflow, job_name)}: cache-mode {got} != {expected}"
        )


def test_cache_mode_matches_actions_cache() -> None:
    verify_cache_modes(all_configs())


def test_cache_mode_removed_is_caught() -> None:
    configs = all_configs()
    del configs["sync_model_data.yml"]["jobs"]["generate"]["cache-mode"]
    with pytest.raises(AssertionError):
        verify_cache_modes(configs)


def test_restore_only_cache_mode_write_is_caught() -> None:
    configs = all_configs()
    configs["build.yml"]["jobs"]["slow-tool-tests-dev"]["cache-mode"] = "write"
    # The match shows that the restore-only check fails, not the
    # CACHE_MODE_JOBS check.
    with pytest.raises(AssertionError, match="needs cache-mode read or none"):
        verify_cache_modes(configs)
