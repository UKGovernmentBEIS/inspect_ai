"""Tests for .github/workflows/sync_model_data.yml.

The sync script and its dependencies run with the provider API keys. They run
in a job whose token can only read, so a compromised dependency can't push or
open PRs. The job that can is separate, holds no keys and installs nothing.
"""

import pathlib
import re
from typing import Any

import yaml

REPO = pathlib.Path(__file__).parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "sync_model_data.yml"


def workflow() -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    return config


def job(name: str) -> dict[str, Any]:
    config: dict[str, Any] = workflow()["jobs"][name]
    return config


def test_workflow_grants_no_default_permissions() -> None:
    assert workflow()["permissions"] == {}
    assert set(workflow()["jobs"]) == {"generate", "open-pr"}


def test_generate_job_holds_the_keys_with_a_read_only_token() -> None:
    generate = job("generate")
    assert generate["permissions"] == {"contents": "read"}
    (checkout,) = [
        s
        for s in generate["steps"]
        if s.get("uses", "").startswith("actions/checkout@")
    ]
    assert checkout["with"]["persist-credentials"] is False
    (sync,) = [s for s in generate["steps"] if s.get("name") == "Sync model data"]
    assert set(sync["env"]) == {"TOGETHER_API_KEY", "FIREWORKS_API_KEY"}


def test_open_pr_job_holds_no_secrets_and_installs_nothing() -> None:
    open_pr = job("open-pr")
    assert open_pr["needs"] == "generate"
    assert open_pr["permissions"] == {"contents": "write", "pull-requests": "write"}
    # Workflow-level env reaches every job, so only the generate job may
    # mention a secret.
    outside_generate = {k: v for k, v in workflow().items() if k != "jobs"}
    # Any mention, in any case: secrets.NAME, secrets['NAME'], toJSON(secrets).
    dumped = yaml.safe_dump([outside_generate, open_pr])
    assert not re.search(r"\bsecrets\b", dumped, re.IGNORECASE)
    actions = [s["uses"].split("@")[0] for s in open_pr["steps"] if "uses" in s]
    assert actions == [
        "actions/checkout",
        "actions/download-artifact",
        "peter-evans/create-pull-request",
    ]
    for step in open_pr["steps"]:
        run = step.get("run", "")
        for installer in ("uv ", "pip", "npm", "pnpm", "curl", "wget"):
            assert installer not in run, f"{step.get('name')!r} runs {installer!r}"
