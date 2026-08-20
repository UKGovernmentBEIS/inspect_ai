"""End-to-end checkpoint resume test: interrupt an attempt, then retry — twice.

Drives a ``react()`` agent through tool-calling turns with
``TurnInterval(every=1)``, so a checkpoint fires at the start of each turn
after the first. The agent calls a ``crash`` tool that signals its own
process mid-run, parametrized over both ways a run really ends:

- ``SIGKILL`` — an *unanticipated* death (power loss / OOM / preemption)
  with no graceful unwind, no log finalize, and an orphaned sandbox
  container. Recovering from exactly that is the point of checkpointing.
- ``SIGINT`` — what Ctrl-C delivers. The opposite hazard: a lot of cleanup
  *does* run (sandbox teardown, log finalize, the sample logged with a
  cancellation error), any of which could plausibly leave the run
  unresumable.

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

from checkpoint.hydrate_interrupt_harness import HOOK_NEVER_FIRED_EXIT_CODE
from checkpoint.resume_kill_harness import (
    B_CONTENT,
    B_SAMPLE_ID,
    CANCEL_FILE_ENV,
    LAYER1_CONTENT,
    SIBLING_CKPT_GLOB_ENV,
    SIGNAL_ENV,
    TARGET_ENV,
    TWO_SAMPLE_ENV,
    generates,
    reset_generates,
)
from checkpoint.resume_kill_thinking_harness import (
    CRASH_FILE_ENV,
    committed_thinking_signatures,
)
from inspect_ai import eval_retry
from inspect_ai._util.file import local_path
from inspect_ai.event import Event, SpanBeginEvent, SpanEndEvent, ToolEvent
from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.scorer import CORRECT
from inspect_ai.util._checkpoint._layout.eval_checkpoints_dir import (
    eval_checkpoints_dir,
)
from inspect_ai.util._checkpoint._sandbox_restic.repo import _SANDBOX_RESTIC_DIR


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


def _run_interrupted_attempt(
    log_dir: str,
    retry_from: str | None,
    tests_dir: Path,
    interrupt: str = "SIGKILL",
    harness_name: str = "resume_kill_harness.py",
) -> None:
    """Run an eval in a child process that signals itself mid-run.

    ``SIGKILL`` is an unanticipated death (no unwind, no log finalize);
    ``SIGINT`` is what Ctrl-C delivers (graceful cancel, finalized log,
    sandboxes torn down). Asserts the attempt ended the way the signal
    implies, so a mode that silently stopped taking effect can't pass.
    """
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            p for p in (str(tests_dir), os.environ.get("PYTHONPATH", "")) if p
        ),
        SIGNAL_ENV: interrupt,
    }
    harness = str(tests_dir / "checkpoint" / harness_name)
    proc = subprocess.run(
        [sys.executable, harness, log_dir, retry_from or ""],
        env=env,
        timeout=600,
    )
    if interrupt == "SIGKILL":
        assert proc.returncode == -signal.SIGKILL, (
            f"expected the child to die by SIGKILL (-{signal.SIGKILL}); "
            f"got returncode {proc.returncode}"
        )
    else:
        # The child's exit code is not a useful signal here: inspect absorbs
        # the interrupt rather than re-raising KeyboardInterrupt, so a
        # SIGINTed eval() exits 0 and a SIGINTed eval_retry() exits 1 on an
        # IndexError. What matters is that the run wound down gracefully —
        # a *finalized* log with status "cancelled" (a hard kill never
        # finalizes one).
        assert proc.returncode != -signal.SIGKILL, "child was hard-killed, not SIGINTed"
        status = read_eval_log(_latest_log(log_dir), header_only=True).status
        assert status == "cancelled", (
            f"expected the SIGINTed attempt to finalize a cancelled log; got '{status}'"
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


def _project_container_ids(name: str) -> list[str]:
    """Container ids belonging to a compose project."""
    return subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={name}"],
        capture_output=True,
        text=True,
    ).stdout.split()


def _force_remove_project(name: str) -> None:
    """Best-effort force-remove the containers of a leaked compose project."""
    ids = _project_container_ids(name)
    if ids:
        subprocess.run(["docker", "rm", "-f", *ids], capture_output=True)


def _assert_restic_dir_hidden(container_id: str) -> None:
    """The injected restic dir is inside ``.cache`` and root-only.

    Probes the live sandbox container of a killed attempt (checkpoints
    committed → binary + repo injected):

    - the path sits under ``/root/.cache/`` — inside the always-on backup
      exclude (``**/.cache``, so the repo never backs itself up) and under
      a parent whose dirent is invisible to non-root; and
    - the dir is mode 0700 owned by root with the repo present, and a
      non-root uid cannot list it.
    """
    assert _SANDBOX_RESTIC_DIR.startswith("/root/.cache/")

    stat = subprocess.run(
        ["docker", "exec", container_id, "stat", "-c", "%a %u", _SANDBOX_RESTIC_DIR],
        capture_output=True,
        text=True,
    )
    assert stat.returncode == 0, f"restic dir missing in sandbox: {stat.stderr}"
    assert stat.stdout.split() == ["700", "0"]

    repo = subprocess.run(
        ["docker", "exec", container_id, "test", "-d", f"{_SANDBOX_RESTIC_DIR}/repo"],
        capture_output=True,
    )
    assert repo.returncode == 0, "restic repo missing in sandbox"

    denied = subprocess.run(
        [
            "docker",
            "exec",
            "-u",
            "65534:65534",
            container_id,
            "ls",
            _SANDBOX_RESTIC_DIR,
        ],
        capture_output=True,
        text=True,
    )
    assert denied.returncode != 0, (
        f"restic dir is listable by a non-root user: {denied.stdout}"
    )


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
        _run_interrupted_attempt(
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
@pytest.mark.parametrize("interrupt", ["SIGKILL", "SIGINT"])
def test_checkpoint_resume_rehydrated_event_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt: str
) -> None:
    """Resume works whether the eval was hard-killed or Ctrl-C'd.

    Ctrl-C (SIGINT) runs a lot of graceful cleanup a hard kill skips —
    sandbox teardown, log finalize, a sample logged with a cancellation
    error — so it reaches checkpoint resume down a different path than
    the SIGKILL case, and gets the same result.
    """
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
        # --- attempt #0: fresh eval, interrupted at turn 2 (after ck1/ck2) --
        _run_interrupted_attempt(log_dir, None, tests_dir, interrupt)

        leaked = [
            cid
            for name in _inspect_projects() - projects_before
            for cid in _project_container_ids(name)
        ]
        if interrupt == "SIGKILL":
            # The hard kill leaves the attempt's sandbox container running —
            # probe it for the restic dir's location and permissions.
            assert leaked, "expected the killed attempt to leak its sandbox container"
            _assert_restic_dir_hidden(leaked[0])
        else:
            assert not leaked, f"Ctrl-C should tear down the sandbox; leaked {leaked}"

        # --- attempt #1: resume, work one turn (ck3), interrupt at turn 3 ---
        _run_interrupted_attempt(log_dir, _latest_log(log_dir), tests_dir, interrupt)

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


def _run_hydrate_interrupted_resume(
    log_dir: str, retry_from: str, tests_dir: Path, interrupt: str
) -> None:
    """Resume in a child process that signals itself mid-copy.

    The signal lands on the first repo copy of the startup pass
    (``copy_resume_payloads``), which runs before the destination
    log's first write — so the interrupted attempt leaves no log at
    all. ``SIGKILL`` dies on the spot; ``SIGINT`` unwinds gracefully
    (Ctrl-C semantics). The no-log outcome is asserted by the caller.
    """
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            p for p in (str(tests_dir), os.environ.get("PYTHONPATH", "")) if p
        ),
        SIGNAL_ENV: interrupt,
    }
    harness = str(tests_dir / "checkpoint" / "hydrate_interrupt_harness.py")
    proc = subprocess.run(
        [sys.executable, harness, log_dir, retry_from],
        env=env,
        timeout=600,
    )
    if interrupt == "SIGKILL":
        # also catches HOOK_NEVER_FIRED_EXIT_CODE: an un-fired hook means
        # the resume ran to completion and exited normally, not by signal
        assert proc.returncode == -signal.SIGKILL, (
            f"expected the child to die by SIGKILL (-{signal.SIGKILL}); "
            f"got returncode {proc.returncode}"
        )
    else:
        assert proc.returncode != HOOK_NEVER_FIRED_EXIT_CODE, (
            "the harness's hydration hook never fired — the repo-copy seam it "
            "patches has moved; this run was an ordinary uninterrupted resume"
        )


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("interrupt", ["SIGINT", "SIGKILL"])
def test_checkpoint_resume_survives_interrupted_hydration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt: str
) -> None:
    """An interrupt *during a resume's own startup* doesn't lose the run.

    A resume copies the prior attempt's checkpoint payload into the new
    attempt's dir at retry startup, before the destination log's first
    write (see ``_resume_copy``). Interrupting that copy used to leave
    a dir that looked committed (checkpoint files present) with no
    restic data behind it — every later resume failed on the missing
    repo, and each retry copied the bad state forward (#4861). Now an
    interrupted copy means the attempt never writes a log: the next
    retry sources the newest log that exists, whose checkpoint dirs are
    complete by construction.

    Flow: SIGKILL a fresh attempt at turn 2 (ck1/ck2 committed) →
    resume and interrupt it inside the startup copy window (a real
    SIGINT or SIGKILL, parametrized: graceful unwind vs. instant
    death must land in the same no-log state) → resume again,
    in-process, to completion. Asserts the interrupted attempt left
    no log and that the final resume genuinely restored (restore
    span + only the remaining turns ran) rather than re-running from
    scratch.
    """
    cancel_file = tmp_path / "cancels.txt"
    monkeypatch.setenv(CANCEL_FILE_ENV, str(cancel_file))
    monkeypatch.setenv(TARGET_ENV, "1")
    # stateful on disk; reset for flaky-retry re-runs (see the layout test)
    cancel_file.unlink(missing_ok=True)

    log_dir = str(tmp_path / "logs")
    tests_dir = Path(__file__).parent.parent

    projects_before = _inspect_projects()
    try:
        # --- attempt #0: fresh eval, hard-killed at turn 2 (ck1/ck2) -----
        _run_interrupted_attempt(log_dir, None, tests_dir)
        source_log = _latest_log(log_dir)

        # --- attempt #1: resume, interrupted inside the startup copy window
        _run_hydrate_interrupted_resume(log_dir, source_log, tests_dir, interrupt)
        # the copy runs before the destination log's first write, so the
        # interrupted attempt must leave no log — its partial checkpoint
        # copies are unreachable orphans, and the source log stays newest
        assert _latest_log(log_dir) == source_log, (
            "the interrupted resume wrote a destination log — its existence "
            "would wrongly certify the (incomplete) checkpoint copy"
        )

        # --- final resume: from the source log, in-process, to completion
        reset_generates()
        resume = eval_retry(read_eval_log(source_log), log_dir=log_dir)[0]
    finally:
        for name in _inspect_projects() - projects_before:
            _force_remove_project(name)

    assert resume.status == "success"
    assert resume.samples is not None and len(resume.samples) == 1
    sample = resume.samples[0]
    assert sample.error is None

    # restored, not re-run: only the remaining turns ran (bash + submit)
    assert generates() == 2
    assert sample.scores is not None
    assert sample.scores["includes"].value == CORRECT

    completed = read_eval_log(resume.location)
    assert completed.samples is not None
    events = completed.samples[0].events
    assert_spans_balanced(events)
    restore_spans = [
        e for e in events if isinstance(e, SpanBeginEvent) and e.type == "prior_run"
    ]
    assert [s.name for s in restore_spans] == ["checkpoint restore 1"]
    checkpoints = {
        (e.checkpoint_id, e.trigger) for e in events if isinstance(e, CheckpointEvent)
    }
    # ck1/ck2 restored from the source; ck3 (turn) + ck4 (agent_complete)
    # committed live during the final resume
    assert checkpoints == {(1, "turn"), (2, "turn"), (3, "turn"), (4, "agent_complete")}


@skip_if_no_docker
@pytest.mark.slow
def test_checkpoint_retry_preserves_queued_sample_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sample still queued when a retry dies keeps its checkpoints (#4870).

    Two samples, two kills. Attempt #0 runs both concurrently: sample B
    checkpoints steadily and never crashes; sample A crashes the process
    once B has a committed checkpoint. Attempt #1 retries with
    ``max_samples=1``: A resumes first and crashes again — B is still
    queued, having run *nothing* in attempt #1. Before the greedy startup
    copy existed, attempt #1 left no trace of B (per-sample copying only
    happened when a sample started), so the final retry — which resolves
    attempt #1's dirs — silently re-ran B from scratch. Now the copy runs
    at retry startup for every incomplete sample, so B's payload is in
    attempt #1's dir despite B never starting.

    Asserts the on-disk property directly (B's payload present in the
    dead attempt's dir) and the behavior: the final in-process retry
    *restores* B (its transcript carries a "checkpoint restore" span)
    rather than re-running it.
    """
    cancel_file = tmp_path / "cancels.txt"
    log_dir = str(tmp_path / "logs")
    monkeypatch.setenv(CANCEL_FILE_ENV, str(cancel_file))
    monkeypatch.setenv(TARGET_ENV, "2")
    monkeypatch.setenv(TWO_SAMPLE_ENV, "1")
    monkeypatch.setenv(
        SIBLING_CKPT_GLOB_ENV,
        f"{log_dir}/*.checkpoints/{B_SAMPLE_ID}__1/ckpt-*.json",
    )
    # stateful on disk; reset for flaky-retry re-runs (see the layout test)
    cancel_file.unlink(missing_ok=True)
    shutil.rmtree(log_dir, ignore_errors=True)

    tests_dir = Path(__file__).parent.parent

    projects_before = _inspect_projects()
    try:
        # --- attempt #0: both samples in flight, killed once B checkpointed
        _run_interrupted_attempt(log_dir, None, tests_dir)
        first_log = _latest_log(log_dir)

        # --- attempt #1: A resumes and crashes; B queued, never started ---
        _run_interrupted_attempt(log_dir, first_log, tests_dir)
        second_log = _latest_log(log_dir)
        assert second_log != first_log, "the retry attempt wrote no log"

        # The #4870 property: the dead retry's checkpoints dir holds B's
        # payload — copied greedily at startup — even though B never ran.
        b_dir = Path(local_path(eval_checkpoints_dir(second_log, None))) / (
            f"{B_SAMPLE_ID}__1"
        )
        assert list(b_dir.glob("ckpt-*.json")), (
            "the retry left no checkpoint payload for the queued sample — "
            "the greedy startup copy regressed; a further retry would re-run "
            "the sample from scratch"
        )

        # --- final retry: in-process, to completion ----------------------
        resume = eval_retry(read_eval_log(second_log), log_dir=log_dir, max_samples=1)[
            0
        ]
    finally:
        for name in _inspect_projects() - projects_before:
            _force_remove_project(name)

    assert resume.status == "success"
    assert resume.samples is not None and len(resume.samples) == 2
    b_sample = next(s for s in resume.samples if s.id == B_SAMPLE_ID)
    assert b_sample.error is None
    assert b_sample.scores is not None
    assert b_sample.scores["includes"].value == CORRECT
    assert B_CONTENT in b_sample.output.completion

    # B was *restored*, not re-run: its transcript opens with a checkpoint
    # restore wrap containing its prior-attempt checkpoints
    assert_spans_balanced(b_sample.events)
    b_restores = [
        e
        for e in b_sample.events
        if isinstance(e, SpanBeginEvent) and e.type == "prior_run"
    ]
    assert [s.name for s in b_restores] == ["checkpoint restore 1"], (
        "the queued sample did not resume from its checkpoints — its "
        "prior-attempt progress was silently discarded"
    )
