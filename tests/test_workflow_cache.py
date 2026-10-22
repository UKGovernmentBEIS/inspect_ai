"""Tests that GitHub Actions jobs holding credentials restore no cache.

Any step in a job can use the runner's cache token, so code from a freshly
published package can write cache entries that other jobs on the same branch
restore, whatever the job's `save-cache` setting. uv's cache also records the
package hashes it checks against, so a tampered cache isn't caught by the
lockfile. A job that holds credentials (write permissions, an id-token,
secrets, or a pull_request_target trigger), or one whose outputs such a job
uses, must therefore not restore from the Actions cache at all.
"""

from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

REPO = Path(__file__).parents[1]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))

Permissions = dict[str, str] | str | None


def never(inputs: dict[str, Any], permissions: Permissions) -> bool:
    return False


def can_read_actions(permissions: Permissions) -> bool:
    if permissions is None or isinstance(permissions, str):
        return True
    return permissions.get("actions", "none") != "none"


# Actions that can restore from the Actions cache, each with a check that
# passes only when the step's inputs (or the job's permissions) rule it out.
CACHE_ACTIONS: dict[str, Callable[[dict[str, Any], Permissions], bool]] = {
    "actions/cache": never,
    "actions/cache/restore": never,
    "hynek/build-and-inspect-python-package": never,
    "astral-sh/setup-uv": lambda inputs, _: inputs.get("enable-cache") is False,
    "actions/setup-python": lambda inputs, _: "cache" not in inputs,
    "actions/setup-node": lambda inputs, _: (
        "cache" not in inputs and inputs.get("package-manager-cache") is False
    ),
    "pnpm/action-setup": lambda inputs, _: inputs.get("cache", False) is False,
    "docker/build-push-action": lambda inputs, _: "cache-from" not in inputs,
    "docker/setup-qemu-action": lambda inputs, _: inputs.get("cache-image") is False,
    "docker/setup-buildx-action": lambda inputs, _: (
        inputs.get("cache-binary") is False
    ),
    # Restores its state only after listing the repository's caches with the
    # job token, which needs `actions: read`.
    "actions/stale": lambda _, permissions: not can_read_actions(permissions),
}


def triggers(workflow: dict[Any, Any]) -> set[str]:
    # PyYAML reads the `on` key as True.
    on: str | list[str] | dict[str, Any] = workflow["on" if "on" in workflow else True]
    return {on} if isinstance(on, str) else set(on)


def job_permissions(workflow: dict[Any, Any], job: dict[str, Any]) -> Permissions:
    permissions: Permissions = job.get("permissions", workflow.get("permissions"))
    return permissions


def grants_write(permissions: Permissions) -> bool:
    # No permissions block means the repository's default token permissions.
    if permissions is None or permissions == "write-all":
        return True
    return isinstance(permissions, dict) and "write" in permissions.values()


def holds_credentials(workflow: dict[Any, Any], job: dict[str, Any]) -> bool:
    return (
        grants_write(job_permissions(workflow, job))
        or "secrets." in yaml.safe_dump([workflow.get("env", {}), job])
        or "secrets" in job
        or "pull_request_target" in triggers(workflow)
    )


def privileged_jobs(workflow: dict[Any, Any]) -> set[str]:
    """Jobs that hold credentials, and the jobs they need (and so trust)."""
    jobs: dict[str, dict[str, Any]] = workflow["jobs"]
    privileged = {
        name for name, job in jobs.items() if holds_credentials(workflow, job)
    }
    pending = list(privileged)
    while pending:
        needs = jobs[pending.pop()].get("needs", [])
        for name in [needs] if isinstance(needs, str) else needs:
            if name not in privileged:
                privileged.add(name)
                pending.append(name)
    return privileged


def local_action(uses: str, steps: list[dict[str, Any]]) -> Path:
    path = uses.removeprefix("./")
    # A second checkout of this repository under `path:` (as release.yml does)
    # puts its actions under that directory.
    for step in steps:
        inputs = step.get("with", {})
        if (
            step.get("uses", "").startswith("actions/checkout@")
            and "path" in inputs
            and "repository" not in inputs
        ):
            path = path.removeprefix(inputs["path"].rstrip("/") + "/")
    for name in ["action.yml", "action.yaml"]:
        if (REPO / path / name).exists():
            return REPO / path / name
    raise AssertionError(f"can't find the local action {uses}")


def step_restores(
    steps: list[dict[str, Any]],
    permissions: Permissions,
    checkouts: list[dict[str, Any]],
) -> list[str]:
    restores: list[str] = []
    for step in steps:
        uses = step.get("uses")
        if uses is None or uses.startswith("docker://"):
            continue
        if uses.startswith("./"):
            action = yaml.safe_load(local_action(uses, checkouts).read_text())
            assert action["runs"]["using"] == "composite", f"can't check {uses}"
            restores += [
                f"{uses} > {restore}"
                for restore in step_restores(
                    action["runs"]["steps"], permissions, checkouts
                )
            ]
            continue
        check = CACHE_ACTIONS.get(uses.split("@")[0])
        if check is not None and not check(step.get("with", {}), permissions):
            restores.append(uses)
    return restores


def job_restores(
    workflow: dict[Any, Any], job: dict[str, Any], permissions: Permissions
) -> list[str]:
    uses = job.get("uses")
    if uses is not None:
        assert uses.startswith("./"), f"can't check the reusable workflow {uses}"
        called = yaml.safe_load((REPO / uses).read_text())
        # Called jobs get at most the caller's permissions.
        return [
            restore
            for called_job in called["jobs"].values()
            for restore in job_restores(called, called_job, permissions)
        ]
    steps: list[dict[str, Any]] = job["steps"]
    return step_restores(steps, permissions, steps)


def workflow_restores(workflow: dict[Any, Any]) -> dict[str, list[str]]:
    restores = {
        name: job_restores(
            workflow,
            workflow["jobs"][name],
            job_permissions(workflow, workflow["jobs"][name]),
        )
        for name in privileged_jobs(workflow)
    }
    return {name: found for name, found in restores.items() if found}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_privileged_jobs_restore_no_cache(path: Path) -> None:
    restores = workflow_restores(yaml.safe_load(path.read_text()))
    assert not restores, f"jobs that hold credentials restore a cache: {restores}"


def test_privileged_jobs_are_found() -> None:
    found = {
        (path.name, name)
        for path in WORKFLOWS
        for name in privileged_jobs(yaml.safe_load(path.read_text()))
    }
    assert {
        ("docker.yml", "build-and-push"),
        ("npm-publish.yml", "publish"),
        ("pr-gate.yml", "gate"),
        ("publish.yml", "build"),
        ("publish.yml", "publish"),
        ("release.yml", "build"),
        ("release.yml", "publish-npm"),
        ("release.yml", "publish-pypi"),
        ("sync_model_data.yml", "sync-models"),
    } <= found


def test_cache_restores_in_privileged_jobs_are_reported() -> None:
    uv: dict[str, Any] = {"uses": "astral-sh/setup-uv@v1"}
    workflow = {
        "on": "push",
        "permissions": {"contents": "read"},
        "jobs": {
            "build": {"steps": [uv]},
            "publish": {
                "needs": "build",
                "steps": [{"run": "echo ${{ secrets.TOKEN }}"}],
            },
            "test": {"steps": [{"uses": "actions/cache@v1"}]},
        },
    }
    assert workflow_restores(workflow) == {"build": ["astral-sh/setup-uv@v1"]}
    uv["with"] = {"enable-cache": False}
    assert workflow_restores(workflow) == {}
    workflow["on"] = ["pull_request_target"]
    assert workflow_restores(workflow) == {"test": ["actions/cache@v1"]}
