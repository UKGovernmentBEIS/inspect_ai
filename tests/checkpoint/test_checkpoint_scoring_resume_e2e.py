"""End-to-end scoring-phase checkpoint-resume test.

The agent finishes cleanly, the scorer hard-kills the process, then retry
skips the agent and re-runs scoring to success.

This is the scenario the scoring-phase resume machinery exists for. The agent
loop runs to a clean ``submit`` — so the checkpointer fires a final
``agent_complete`` checkpoint — and then the scorer ``SIGKILL``s its own
process *before* scoring commits. On retry, inspect reads the latest
``agent_complete`` checkpoint, tags the sample
``Attempt.RESUME_FOR_SCORING``, and the ``react`` agent fast-path-returns its
restored state with **zero** model calls; the scorer then re-runs to success.

Like the mid-agent sibling (``test_checkpoint_e2e.py``), a real ``SIGKILL``
can't kill the pytest process and let it continue, so the killed attempt runs
in a **child process** (the harness in ``resume_scoring_kill_harness.py``, run
as a script); the scorer kills that child. The final resume runs in-process.

Requires Docker: the sandbox backup path injects/execs a Linux restic binary
inside the sandbox, which only works with a Linux container.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from checkpoint.resume_scoring_kill_harness import (
    ANSWER,
    CANCEL_FILE_ENV,
    TARGET_ENV,
    generates,
    reset_generates,
)
from inspect_ai import eval_retry
from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.scorer import CORRECT


def _latest_log(log_dir: str) -> str:
    """Location of the most recently written eval log (timestamp-prefixed)."""
    logs = list_eval_logs(log_dir)
    assert logs, f"no eval logs under {log_dir}"
    return max(logs, key=lambda info: info.name).name


def _run_killed_attempt(log_dir: str, retry_from: str | None, tests_dir: Path) -> None:
    """Run an eval in a child process whose scorer ``SIGKILL``s itself.

    Asserts the child died by signal rather than exiting normally.
    """
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            p for p in (str(tests_dir), os.environ.get("PYTHONPATH", "")) if p
        ),
    }
    harness = str(tests_dir / "checkpoint" / "resume_scoring_kill_harness.py")
    proc = subprocess.run(
        [sys.executable, harness, log_dir, retry_from or ""],
        env=env,
        timeout=600,
    )
    assert proc.returncode == -signal.SIGKILL, (
        f"expected the child to die by SIGKILL (-{signal.SIGKILL}); "
        f"got returncode {proc.returncode}"
    )


def _inspect_projects() -> set[str]:
    """Names of inspect docker compose projects currently known to docker."""
    result = subprocess.run(
        ["docker", "compose", "ls", "--all", "--format", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    try:
        projects = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return set()
    return {
        p.get("Name", "") for p in projects if p.get("Name", "").startswith("inspect-")
    }


def _force_remove_project(name: str) -> None:
    """Best-effort force-remove the containers of a leaked compose project."""
    ids = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={name}"],
        capture_output=True,
        text=True,
    ).stdout.split()
    if ids:
        subprocess.run(["docker", "rm", "-f", *ids], capture_output=True)


@skip_if_no_docker
@pytest.mark.slow
def test_checkpoint_scoring_phase_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSPECT_CHECKPOINTING", "1")
    # Scoring-crash count (host file) + target are inherited by the child.
    cancel_file = tmp_path / "cancels.txt"
    monkeypatch.setenv(CANCEL_FILE_ENV, str(cancel_file))
    monkeypatch.setenv(TARGET_ENV, "1")
    # The crash count is stateful on disk. Under flaky-retry (this test is
    # `_needs_flaky_retry` via `skip_if_no_docker`) the body re-runs with the
    # same `tmp_path`, so reset it — otherwise a retry would inherit a
    # count >= target, the scorer would never crash, and the retry would
    # spuriously fail.
    cancel_file.unlink(missing_ok=True)

    log_dir = str(tmp_path / "logs")
    tests_dir = Path(__file__).parent.parent

    # A hard kill skips sandbox teardown, so the killed attempt leaks its
    # sandbox container. Track inspect projects before/after and force-remove
    # the ones this test leaks (the final resume cleans up its own).
    projects_before = _inspect_projects()
    try:
        # --- attempt #0: fresh eval; agent completes, scorer hard-kills ------
        _run_killed_attempt(log_dir, None, tests_dir)

        # --- final resume: runs in this process, scoring-phase only ----------
        reset_generates()
        resume = eval_retry(read_eval_log(_latest_log(log_dir)), log_dir=log_dir)[0]
    finally:
        for name in _inspect_projects() - projects_before:
            _force_remove_project(name)

    assert resume.status == "success"
    assert resume.samples is not None and len(resume.samples) == 1
    sample = resume.samples[0]
    assert sample.error is None

    # Headline: the agent loop was skipped entirely on the scoring-phase
    # resume — zero model calls. A plain RETRY (or a from-scratch rerun) would
    # have driven the scripted model again.
    assert generates() == 0

    # The restored agent output was re-scored to success.
    assert sample.scores is not None
    assert sample.scores["crashing_includes"].value == CORRECT
    assert ANSWER in sample.output.completion
