"""An eval's calls through the real sentinel sidecar, so that Inspect's client and the sidecar are checked against each other.

The sidecar is `inspect_sentinel`'s own handler and its endpoint for evals, behind a stand-in for a model proxy. Inspect's other sidecar tests answer with a stand-in sidecar, which checks signatures with code of its own, written in the same Python. Here, what Inspect registers, signs and asks is read and checked by the sidecar itself.

The evals run in a process of their own (`test_helpers/real_sidecar_eval.py`), since this suite keeps `inspect_sentinel` from being imported. One process runs every case, and each test reads its case from what that process wrote.

These tests need a sidecar that checks an eval's signatures. With one that doesn't, they fail, as an eval would.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from test_helpers.real_sidecar_eval import CASES, Case

_TESTS = Path(__file__).parent.parent

_TIMEOUT = 120
"""How long every case may take in all, in seconds. They take a few."""

_BASE_URLS = ["ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "TOGETHER_BASE_URL"]


def _run_cases(folder: Path) -> dict[str, Any]:
    """Run every case in a process of its own, and give what it wrote, or why it wrote nothing under `failed`."""
    results = folder / "results.json"
    # no base URL but each case's own reaches the sidecar, and the providers
    # are given a key, which nothing checks
    env = {name: value for name, value in os.environ.items() if name not in _BASE_URLS}
    env.setdefault("ANTHROPIC_API_KEY", "test-key")
    env.setdefault("OPENAI_API_KEY", "test-key")
    try:
        ran = subprocess.run(
            [
                sys.executable,
                "-m",
                "test_helpers.real_sidecar_eval",
                str(results),
                str(folder / "logs"),
            ],
            cwd=_TESTS,
            env=env,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired as ex:
        stderr = ex.stderr.decode() if isinstance(ex.stderr, bytes) else ex.stderr
        return {
            "failed": f"The evals through the real sidecar didn't finish in {_TIMEOUT} seconds.\n{(stderr or '')[-4000:]}"
        }
    if ran.returncode != 0 or not results.exists():
        return {
            "failed": f"The evals through the real sidecar couldn't run (exit {ran.returncode}).\n{ran.stderr[-4000:]}"
        }
    found: dict[str, Any] = json.loads(results.read_text(encoding="utf-8"))
    return found


@pytest.fixture(scope="module")
def ran(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """What came of every case, run once however many workers run these tests."""
    if os.environ.get("PYTEST_XDIST_WORKER") is None:
        found = _run_cases(tmp_path_factory.mktemp("real_sidecar"))
    else:
        # Each xdist worker has this fixture, and the tests of a file are
        # spread over them. The first worker to make the folder, which all
        # of a run's workers share, runs the cases. The others wait for what
        # it writes, including why it failed, so none waits past the first.
        shared = tmp_path_factory.getbasetemp().parent / "real_sidecar"
        done = shared / "done.json"
        try:
            shared.mkdir()
        except FileExistsError:
            deadline = time.monotonic() + _TIMEOUT + 30
            while not done.exists():
                if time.monotonic() > deadline:
                    pytest.fail(
                        "The worker running the evals through the real sidecar wrote nothing."
                    )
                time.sleep(0.1)
            found = json.loads(done.read_text(encoding="utf-8"))
        else:
            found = _run_cases(shared)
            # written whole, so a waiting worker never reads half of it
            writing = shared / "writing.json"
            writing.write_text(json.dumps(found), encoding="utf-8")
            writing.replace(done)
    if "failed" in found:
        pytest.fail(found["failed"])
    return found


def _came_of(ran: dict[str, Any], case: Case) -> dict[str, Any]:
    found: dict[str, Any] = ran["cases"][case.name]
    assert "raised" not in found, found.get("raised")
    # the stand-in for a model proxy is this test's own, and must not fail
    assert found["proxy_errors"] == [], "\n".join(found["proxy_errors"])
    return found


def _why(ran: dict[str, Any], found: dict[str, Any]) -> str:
    # what a failed case says, with which sidecar ran: one that doesn't
    # check signatures fails every case, as an eval through it would
    return f"{found['sample_error'] or found['error']}\nThe sidecar that ran is {ran['sidecar']}, and these tests need one that checks an eval's signatures."


_TAKEN = [case for case in CASES if case.change is None]
_CHANGED = [case for case in CASES if case.change is not None]


@pytest.mark.parametrize("case", _TAKEN, ids=[case.name for case in _TAKEN])
def test_the_sidecar_takes_what_inspect_signs(ran: dict[str, Any], case: Case) -> None:
    found = _came_of(ran, case)

    # the sample ran, with every call judged, as `required` asks
    assert found["status"] == "success", _why(ran, found)
    assert found["sample_error"] is None, _why(ran, found)

    # The sidecar's sentinel judged the call as the sample Inspect named,
    # whose signature the sidecar took: each value as Inspect wrote it, an
    # int still an int.
    assert found["seen"], "the sidecar's sentinel was asked nothing"
    for named in found["seen"]:
        assert named == {
            "eval_id": found["eval_id"],
            "task": case.task,
            "sample_id": case.sample_id,
            "sample_id_type": type(case.sample_id).__name__,
            "sample_uuid": found["sample_uuid"],
            "epoch": 1,
        }


@pytest.mark.parametrize("case", _CHANGED, ids=[case.name for case in _CHANGED])
def test_the_sidecar_refuses_a_call_changed_after_inspect_signed_it(
    ran: dict[str, Any], case: Case
) -> None:
    found = _came_of(ran, case)

    # refused by the sidecar's own check of the signature, and never judged
    error = found["sample_error"]
    assert error is not None, _why(ran, found)
    assert "x-inspect-context mac" in error
    assert "The request was not judged" in error
    assert found["seen"] == []
