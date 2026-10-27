"""Jobs that hold credentials restore no cache (see the canary comment in build.yml)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).parents[1]
CREDENTIAL_JOBS = [
    ("suppressions-comment.yml", "comment"),
    ("sync_model_data.yml", "sync-models"),
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


def job_steps(workflow: str, job: str) -> list[dict[str, Any]]:
    config = yaml.safe_load((REPO / ".github" / "workflows" / workflow).read_text())
    steps: list[dict[str, Any]] = []
    for step in config["jobs"][job]["steps"]:
        steps.append(step)
        # The build-dist and publish-dist composite actions.
        if ".github/actions/" in step.get("uses", ""):
            action = REPO / ".github" / "actions" / step["uses"].split("/")[-1]
            steps += yaml.safe_load((action / "action.yml").read_text())["runs"][
                "steps"
            ]
    return steps


@pytest.mark.parametrize("workflow,job", CREDENTIAL_JOBS)
def test_credential_holding_jobs_restore_no_cache(workflow: str, job: str) -> None:
    for step in job_steps(workflow, job):
        action = step.get("uses", "").split("@")[0]
        inputs = step.get("with") or {}
        assert action not in {"actions/cache", "actions/cache/restore"}
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
