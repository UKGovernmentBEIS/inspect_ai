"""End-to-end checkpoint resume test: hard-kill an attempt, then retry — twice.

Drives a ``react()`` agent through tool-calling turns with
``TurnInterval(every=1)``, so a checkpoint fires at the start of each turn
after the first. Instead of cooperatively cancelling, the agent calls a
``crash`` tool that ``SIGKILL``s its own process mid-run — an *unanticipated*
death (power loss / OOM / preemption) with no graceful unwind, no log
finalize, and an orphaned sandbox container. Recovering from exactly that is
the point of checkpointing.

Because a real ``SIGKILL`` can't kill the pytest process and let it continue,
each killed attempt runs in a **child process** (the harness in
``test_helpers/checkpoint_resume_kill.py``, run via ``python -c``); the
``crash`` tool kills that child. ``test_checkpoint_resume_rehydrated_event_layout``
kills a fresh attempt (after ck1/ck2 commit), resumes and kills again (after
ck3), then resumes a final time *in-process* to completion. It checks, via
the public ``.eval`` log: each resume's restored checkpoints appear as
``CheckpointEvent``s inside its own ``prior_run`` ("checkpoint restore N")
span; the wraps are sequentially numbered, span-balanced siblings; a new
checkpoint commits *during* the final resume (a ``CheckpointEvent`` outside
the wraps, continuing the numbering); and resume restored the prior
conversation (only the remaining turns run, not a replay from scratch).

Requires Docker: the sandbox backup path injects/execs a Linux restic
binary inside the sandbox, which only works with a Linux container
(``detect_sandbox_os`` rejects non-Linux hosts). See
``examples/checkpoint_ctf.py`` for the manual harness this replaces.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from test_helpers.checkpoint_resume_kill import (
    CANCEL_FILE_ENV,
    LAYER1_CONTENT,
    TARGET_ENV,
    generates,
    reset_generates,
)
from test_helpers.utils import skip_if_no_docker

from inspect_ai import eval_retry
from inspect_ai.event import Event, SpanBeginEvent, SpanEndEvent, ToolEvent
from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.scorer import CORRECT


def assert_spans_balanced(events: list[Event]) -> None:
    """Assert the event stream's spans are well-formed (LIFO-nested).

    Treats ``span_begin``/``span_end`` as brackets: every end must close
    the innermost open span, and nothing may be left open at the end.
    Presence/membership assertions can't catch an *additive* structural
    corruption (extra unbalanced spans wrapped around otherwise-correct
    content) — this can.
    """
    stack: list[str] = []
    for e in events:
        if isinstance(e, SpanBeginEvent):
            stack.append(e.id)
        elif isinstance(e, SpanEndEvent):
            assert stack, f"span_end {e.id} with no open span"
            top = stack.pop()
            assert top == e.id, (
                f"span_end {e.id} closes out of order; innermost open span is {top}"
            )
    assert not stack, f"{len(stack)} unclosed span(s): {stack}"


def _latest_log(log_dir: str) -> str:
    """Location of the most recently written eval log.

    Filenames are timestamp-prefixed, so lexicographic max is newest.
    """
    logs = list_eval_logs(log_dir)
    assert logs, f"no eval logs under {log_dir}"
    return max(logs, key=lambda info: info.name).name


def _run_killed_attempt(log_dir: str, retry_from: str | None, tests_dir: Path) -> None:
    """Run an eval in a child process that ``SIGKILL``s itself mid-run.

    Asserts the child died by signal rather than exiting normally.
    """
    env = {
        **os.environ,
        # the child needs `tests/` on the path to import `test_helpers`
        "PYTHONPATH": os.pathsep.join(
            p for p in (str(tests_dir), os.environ.get("PYTHONPATH", "")) if p
        ),
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from test_helpers.checkpoint_resume_kill import main; main()",
            log_dir,
            retry_from or "",
        ],
        env=env,
        timeout=600,
    )
    assert proc.returncode == -signal.SIGKILL, (
        f"expected the child to die by SIGKILL (-{signal.SIGKILL}); "
        f"got returncode {proc.returncode}"
    )
    # The hard kill orphans the realtime-view sample buffer (`<log_dir>/.buffer`,
    # a streaming UI cache distinct from the durable .eval log + checkpoints).
    # inspect only auto-prunes buffers of *finished* evals, so this killed
    # ("started") one lingers and its stale recovery data shadows checkpoint
    # resume on the next attempt. A real crash-recovery orchestrator restores
    # from the log + checkpoints, not this cache, so drop it before resuming.
    shutil.rmtree(Path(log_dir) / ".buffer", ignore_errors=True)


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
def test_checkpoint_resume_rehydrated_event_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSPECT_CHECKPOINTING", "1")
    # Opt into per-snapshot file listing so the ckpt JSON records the
    # sandbox file paths (exercises host-side `restic ls` on the egressed
    # sandbox repo).
    monkeypatch.setenv("INSPECT_CHECKPOINT_LIST_FILES", "1")
    # Crash count (host file) + target are inherited by the child processes.
    monkeypatch.setenv(CANCEL_FILE_ENV, str(tmp_path / "cancels.txt"))
    monkeypatch.setenv(TARGET_ENV, "2")

    log_dir = str(tmp_path / "logs")
    tests_dir = Path(__file__).parent.parent

    # This test is auto-wrapped in flaky_retry (docker), which re-invokes it
    # with the *same* tmp_path. Reset the per-run state so a retry starts clean
    # (a stale crash count would make the fresh attempt never crash).
    shutil.rmtree(tmp_path / "logs", ignore_errors=True)
    (tmp_path / "cancels.txt").unlink(missing_ok=True)

    # A hard kill skips sandbox teardown, so each killed attempt leaks its
    # sandbox container. Track inspect projects before/after and force-remove
    # the ones this test leaks (the final resume cleans up its own).
    projects_before = _inspect_projects()
    try:
        # --- attempt #0: fresh eval, hard-killed at turn 2 (after ck1/ck2) --
        _run_killed_attempt(log_dir, None, tests_dir)

        # --- attempt #1: resume, work one turn (ck3), hard-kill at turn 3 ---
        _run_killed_attempt(log_dir, _latest_log(log_dir), tests_dir)

        # --- final resume: runs in this process, to completion --------------
        reset_generates()
        resume = eval_retry(read_eval_log(_latest_log(log_dir)), log_dir=log_dir)[0]
    finally:
        for name in _inspect_projects() - projects_before:
            _force_remove_project(name)

    assert resume.status == "success"
    assert resume.samples is not None and len(resume.samples) == 1
    sample = resume.samples[0]
    assert sample.error is None

    # the final resume restored the full prior conversation, so only the
    # remaining turns ran (one bash + submit = 2 generates; a fresh re-run
    # would have redone the earlier turns as well).
    assert generates() == 2

    # the restored + completed run scored correct
    assert sample.scores is not None
    assert sample.scores["includes"].value == CORRECT
    assert LAYER1_CONTENT in sample.output.completion

    # --- examine the completed .eval: restore spans + checkpoint events ----
    completed = read_eval_log(resume.location)
    assert completed.samples is not None
    events = completed.samples[0].events

    # the rehydrated wraps must be self-contained, balanced subtrees — not
    # closed while restored structural spans are still open (the regression)
    assert_spans_balanced(events)

    # each resume contributed one "checkpoint restore" (prior_run) wrap,
    # sequentially numbered
    restore_spans = [
        e for e in events if isinstance(e, SpanBeginEvent) and e.type == "prior_run"
    ]
    assert [s.name for s in restore_spans] == [
        "checkpoint restore 1",
        "checkpoint restore 2",
    ]

    # index range each wrap spans (begin..matching end)
    def _span_range(span_id: str) -> tuple[int, int]:
        begin_idx = next(
            i
            for i, e in enumerate(events)
            if isinstance(e, SpanBeginEvent) and e.id == span_id
        )
        end_idx = next(
            i
            for i, e in enumerate(events)
            if isinstance(e, SpanEndEvent) and e.id == span_id
        )
        return begin_idx, end_idx

    wrap_ranges = [_span_range(s.id) for s in restore_spans]

    def _in_wrap(i: int) -> bool:
        return any(begin < i < end for begin, end in wrap_ranges)

    # every checkpoint that fired before a kill is rehydrated inside a wrap:
    # ckpt-1/ckpt-2 (initial attempt) and ckpt-3 (first resume).
    restored_checkpoint_ids = {
        e.checkpoint_id
        for i, e in enumerate(events)
        if isinstance(e, CheckpointEvent) and _in_wrap(i)
    }
    assert restored_checkpoint_ids == {1, 2, 3}

    # the prior tool activity was rehydrated inside the wraps too
    restored_tools = {
        e.function
        for i, e in enumerate(events)
        if isinstance(e, ToolEvent) and _in_wrap(i)
    }
    assert {"bash", "remember"} <= restored_tools

    # the checkpoint committed *during* the final resume is live — outside any
    # wrap — and continues the numbering past the restored ones.
    new_checkpoint_ids = {
        e.checkpoint_id
        for i, e in enumerate(events)
        if isinstance(e, CheckpointEvent) and not _in_wrap(i)
    }
    assert new_checkpoint_ids == {4}

    # File listing (opt-in) records each sandbox snapshot's added/changed
    # files (diff vs parent), not the whole tree.
    def _ckpt(checkpoint_id: int) -> CheckpointEvent:
        return next(
            e
            for e in events
            if isinstance(e, CheckpointEvent) and e.checkpoint_id == checkpoint_id
        )

    # ckpt-1 is the first sandbox snapshot (no parent) → full listing, which
    # includes the turn-0 write but NOT the XDG cache dir (auto-home excludes
    # $HOME/.cache).
    ckpt1_files = _ckpt(1).sandboxes["default"].files
    assert ckpt1_files is not None
    assert any(p.endswith("workspace/decoded/layer1.txt") for p in ckpt1_files)
    assert not any("/.cache/" in p for p in ckpt1_files)

    # ckpt-3 diffs against its parent (ckpt-2): it lists the post-resume write
    # but NOT the unchanged turn-0 file — proving it's a delta, not the tree.
    ckpt3_details = _ckpt(3).sandboxes["default"]
    assert ckpt3_details.files is not None
    assert any(p.endswith("workspace/resumed.txt") for p in ckpt3_details.files)
    assert not any(
        p.endswith("workspace/decoded/layer1.txt") for p in ckpt3_details.files
    )
    assert ckpt3_details.additional_files is None
