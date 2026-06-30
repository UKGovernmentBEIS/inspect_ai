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
``tests/checkpoint/resume_kill_harness.py``, run as a script); the
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
from test_helpers.utils import flaky_retry, skip_if_no_anthropic, skip_if_no_docker

from checkpoint.resume_kill_harness import (
    CANCEL_FILE_ENV,
    LAYER1_CONTENT,
    TARGET_ENV,
    generates,
    reset_generates,
)
from checkpoint.resume_kill_thinking_harness import (
    CRASH_FILE_ENV,
    committed_thinking_signatures,
)
from inspect_ai import eval_retry
from inspect_ai.event import Event, SpanBeginEvent, SpanEndEvent, ToolEvent
from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.scorer import CORRECT
from inspect_ai.util._checkpoint._layout.eval_checkpoints_dir import (
    eval_checkpoints_dir,
)


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


def _run_killed_attempt(
    log_dir: str,
    retry_from: str | None,
    tests_dir: Path,
    harness_name: str = "resume_kill_harness.py",
) -> None:
    """Run an eval in a child process that ``SIGKILL``s itself mid-run.

    Asserts the child died by signal rather than exiting normally.
    """
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            p for p in (str(tests_dir), os.environ.get("PYTHONPATH", "")) if p
        ),
    }
    harness = str(tests_dir / "checkpoint" / harness_name)
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


def _thinking_signatures(log_location: str) -> set[str]:
    """Anthropic thinking-block signatures dumped under a run's checkpoints dir.

    Reads every ``context/assistant_internal.json`` under the checkpoints dir
    derived from ``log_location`` (a run writes its checkpoints to a dir keyed
    off its *own* log basename, so this isolates one run's dumps from another's).
    """
    return committed_thinking_signatures(eval_checkpoints_dir(log_location, None))


@skip_if_no_anthropic
@skip_if_no_docker
@pytest.mark.slow
@flaky_retry(max_retries=2)
def test_checkpoint_resume_restores_assistant_internal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real Anthropic model's thinking blocks survive a hard-kill + resume.

    With extended thinking on, the provider records thinking blocks (keyed by
    signature) in its per-sample assistant-internal state. This drives one
    tool turn — so a checkpoint with a recorded block commits — then
    ``SIGKILL``s the eval, and resumes.

    Two artifact assertions (resume *succeeding* can't catch a regression: the
    request builder reconstructs a thinking block from the message's own
    ``ContentReasoning`` on a cache miss, so a broken restore degrades fidelity
    rather than erroring):

    1. the killed attempt dumped real thinking-block signatures into its
       checkpoint host context (real-provider serialization works); and
    2. those signatures reappear in the *resume's* own checkpoint dump —
       replaying history never re-records them, so they're present only if
       restore put them back into the live assistant-internal state.
    """
    crash_file = tmp_path / "crashed.txt"
    monkeypatch.setenv(CRASH_FILE_ENV, str(crash_file))

    log_dir = str(tmp_path / "logs")
    tests_dir = Path(__file__).parent.parent

    # flaky-retry re-runs this body in-process reusing `tmp_path`. Both the
    # crash marker and the log dir are stateful on disk: a stale crash marker
    # would skip the kill, and stale checkpoints would trip the `crash` tool's
    # "thinking checkpoint committed" gate before this run commits its own.
    # Reset both so every attempt starts clean.
    crash_file.unlink(missing_ok=True)
    shutil.rmtree(log_dir, ignore_errors=True)

    projects_before = _inspect_projects()
    try:
        _run_killed_attempt(
            log_dir, None, tests_dir, harness_name="resume_kill_thinking_harness.py"
        )
        killed_log = _latest_log(log_dir)
        prekill_sigs = _thinking_signatures(killed_log)
        assert prekill_sigs, (
            "no Anthropic thinking-block signatures were checkpointed before "
            "the kill — the model may not have thought + called a tool before "
            "the first checkpoint fired"
        )

        resume = eval_retry(
            read_eval_log(killed_log), log_dir=log_dir, display="plain"
        )[0]
    finally:
        for name in _inspect_projects() - projects_before:
            _force_remove_project(name)

    assert resume.status == "success"
    assert resume.samples is not None and len(resume.samples) == 1
    assert resume.samples[0].error is None

    postresume_sigs = _thinking_signatures(resume.location)
    assert prekill_sigs <= postresume_sigs, (
        "pre-kill thinking-block signatures are missing from the resume's own "
        "checkpoint dump — assistant-internal state was not restored on resume"
    )


@skip_if_no_docker
@pytest.mark.slow
def test_checkpoint_resume_rehydrated_event_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Crash count (host file) + target are inherited by the child processes.
    cancel_file = tmp_path / "cancels.txt"
    monkeypatch.setenv(CANCEL_FILE_ENV, str(cancel_file))
    monkeypatch.setenv(TARGET_ENV, "2")
    # The crash count is stateful on disk. Under flaky-retry (this test is
    # `_needs_flaky_retry` via `skip_if_no_docker`) the body re-runs with the
    # same `tmp_path`, so reset it — otherwise a retry would inherit a
    # count >= target, no attempt would crash, and the retry would
    # spuriously fail.
    cancel_file.unlink(missing_ok=True)

    log_dir = str(tmp_path / "logs")
    tests_dir = Path(__file__).parent.parent

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

    # the checkpoints committed *during* the final resume are live — outside
    # any wrap — and continue the numbering past the restored ones: ckpt-4 is
    # the post-resume turn fire, ckpt-5 is the `agent_complete` finalize fired
    # when the agent loop exits cleanly (the scoring-phase resume marker).
    new_checkpoints = {
        (e.checkpoint_id, e.trigger)
        for i, e in enumerate(events)
        if isinstance(e, CheckpointEvent) and not _in_wrap(i)
    }
    assert new_checkpoints == {(4, "turn"), (5, "agent_complete")}

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
