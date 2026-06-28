"""Regression test for sandbox-fingerprint drift detection.

The eval log records only the sandbox *recipe* (provider + config path), so two
runs whose compose file pins the same mutable tag (e.g. ``:latest``) are
byte-identical in the log even when the tag is silently repointed at a different
underlying image. The ``sandbox_fingerprint`` hook records the *resolved* runtime
of each sandbox, which must distinguish such drift.

This test promotes the throwaway drift demo (originally /tmp/prov-spike) into the
suite: it builds two genuinely different images (Debian vs Alpine), publishes each
behind the SAME mutable tag in turn, runs an eval after each repoint, and asserts
the recipe is identical across runs while the recorded fingerprint differs.
"""

import subprocess
from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample

FIXTURES = Path(__file__).parent / "fingerprint_drift"
COMPOSE = FIXTURES / "compose.yaml"
TAG = "inspect-fingerprint-drift:latest"


def _build_and_tag(dockerfile: str) -> None:
    """Build the given Dockerfile and point the mutable TAG at the result."""
    subprocess.run(
        ["docker", "build", "-f", str(FIXTURES / dockerfile), "-t", TAG, str(FIXTURES)],
        check=True,
        capture_output=True,
    )


def _run_eval_fingerprint():
    task = Task(
        dataset=[Sample(input="hello", target="x")],
        sandbox=("docker", COMPOSE.as_posix()),
    )
    log = eval(task, model="mockllm/model", limit=1)[0]
    assert log.status == "success", f"eval failed: {log.error}"
    fingerprint = log.samples[0].sandbox_fingerprint
    assert fingerprint is not None, "sandbox_fingerprint was not recorded"
    return log, fingerprint["default"]


@pytest.mark.slow
@skip_if_no_docker
def test_sandbox_fingerprint_detects_tag_drift() -> None:
    try:
        _build_and_tag("Dockerfile.a")
        log_a, fp_a = _run_eval_fingerprint()

        # Same mutable tag, different underlying image.
        _build_and_tag("Dockerfile.b")
        log_b, fp_b = _run_eval_fingerprint()

        # The recipe the framework records is byte-identical across both runs:
        # the log alone cannot tell the two environments apart.
        assert log_a.eval.sandbox == log_b.eval.sandbox
        assert fp_a.image == fp_b.image == TAG

        # The fingerprint distinguishes the drift the recipe cannot.
        assert fp_a.image_id is not None and fp_b.image_id is not None
        assert fp_a.image_id != fp_b.image_id

        # The two images also differ in OS (Debian vs Alpine), a second signal.
        assert fp_a.os is not None and fp_b.os is not None
        assert fp_a.os != fp_b.os
    finally:
        subprocess.run(["docker", "rmi", "-f", TAG], capture_output=True)
