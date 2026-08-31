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

``test_checkpoint_resume_rehydrated_event_layout`` is parametrized over
both sandbox snapshot strategies — the default ``restic-incremental``
and ``archive`` — so the full kill/resume cycle (capture, adopt,
restore, strategy pin round-trip) runs end-to-end against each.

Requires Docker: the sandbox backup path runs Linux tooling inside the
sandbox (an injected restic binary, or tar + compressor for the archive
strategy), which only works with a Linux container
(``detect_sandbox_os`` rejects non-Linux hosts).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from test_helpers.utils import flaky_retry, skip_if_no_anthropic, skip_if_no_docker

from checkpoint.resume_kill_harness import (
    CANCEL_FILE_ENV,
    LAYER1_CONTENT,
    SIGNAL_ENV,
    STRATEGY_ENV,
    TARGET_ENV,
    TURN_LIMIT_ENV,
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
from inspect_ai.util._checkpoint._layout.host_context import SAMPLE_RUNTIME
from inspect_ai.util._checkpoint._sandbox_restic.repo import _SANDBOX_RESTIC_DIR
from inspect_ai.util._checkpoint._snapshot import (
    STRATEGY_ARCHIVE,
    STRATEGY_RESTIC,
    snapshot_strategy_name,
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


def _project_prefix(task_name: str) -> str:
    """Compose-project name prefix for evals of `task_name`.

    Mirrors `task_project_name` in inspect's docker provider
    (`inspect-{task[:12].rstrip('_')}-i{suffix}`), minus the random suffix.
    """
    return f"inspect-{task_name[:12].rstrip('_')}-"


def _inspect_projects(prefix: str) -> set[str]:
    """Names of this harness's docker compose projects currently known to docker.

    Must be scoped to this test's own task (`prefix`): docker state is
    machine-global, and under xdist a global before/after diff sweeps up —
    and force-removes — live containers belonging to concurrently running
    tests on other workers (#264).
    """
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
    return {p.get("Name", "") for p in projects if p.get("Name", "").startswith(prefix)}


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


def _assert_snapshot_dir_hidden(container_id: str, strategy: str) -> None:
    """The in-sandbox snapshot work area is inside ``.cache`` and root-only.

    Probes the live sandbox container of a killed attempt (checkpoints
    committed → the strategy's in-sandbox area exists). Both strategies
    share the same root-only dir (restic's home doubles as the archive
    strategy's staging parent):

    - the path sits under ``/root/.cache/`` — inside the always-on backup
      exclude (``**/.cache``, so the area never backs itself up) and under
      a parent whose dirent is invisible to non-root;
    - the dir is mode 0700 owned by root, and a non-root uid cannot list
      it;
    - restic: the injected repo is present. archive: no restic repo was
      ever injected, and the tar staging area was cleaned up after the
      last capture.
    """
    assert _SANDBOX_RESTIC_DIR.startswith("/root/.cache/")

    stat = subprocess.run(
        ["docker", "exec", container_id, "stat", "-c", "%a %u", _SANDBOX_RESTIC_DIR],
        capture_output=True,
        text=True,
    )
    assert stat.returncode == 0, f"snapshot dir missing in sandbox: {stat.stderr}"
    assert stat.stdout.split() == ["700", "0"]

    def _dir_exists(path: str) -> bool:
        return (
            subprocess.run(
                ["docker", "exec", container_id, "test", "-d", path],
                capture_output=True,
            ).returncode
            == 0
        )

    if strategy == "restic":
        assert _dir_exists(f"{_SANDBOX_RESTIC_DIR}/repo"), (
            "restic repo missing in sandbox"
        )
    else:
        assert not _dir_exists(f"{_SANDBOX_RESTIC_DIR}/repo"), (
            "restic repo injected despite the archive strategy"
        )
        assert not _dir_exists(f"{_SANDBOX_RESTIC_DIR}/snapshot-staging"), (
            "archive staging area not cleaned up after capture"
        )

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
        f"snapshot dir is listable by a non-root user: {denied.stdout}"
    )


class _SpentBudget(NamedTuple):
    turns: int
    tokens: int


def _spent_budget(log_location: str) -> _SpentBudget:
    """Peak turn/token usage across the limit snapshots a run committed."""
    turns = 0
    tokens = 0
    root = Path(local_path(eval_checkpoints_dir(log_location, None)))
    for path in root.rglob(SAMPLE_RUNTIME):
        try:
            snapshot: dict[str, Any] = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        turns = max(turns, int(snapshot.get("turns") or 0))
        usage: dict[str, Any] = snapshot.get("token_usage") or {}
        tokens = max(tokens, int(usage.get("total_tokens") or 0))
    return _SpentBudget(turns=turns, tokens=tokens)


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

    prefix = _project_prefix("resume_thinking_task")
    projects_before = _inspect_projects(prefix)
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
        for name in _inspect_projects(prefix) - projects_before:
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
def test_checkpoint_resume_carries_budget_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resumed sample keeps the budget it already spent.

    Turn count is the readable one: the killed attempt spends at least two
    turns, the resume spends two more, and the logged count has to include
    both. Limit counters live in per-sample objects the runner rebuilds on
    every attempt, so without the restore the resume reports only its own
    turns and the sample gets a second full budget.
    """
    cancel_file = tmp_path / "cancels.txt"
    monkeypatch.setenv(CANCEL_FILE_ENV, str(cancel_file))
    monkeypatch.setenv(TARGET_ENV, "1")
    # generous: this asserts the counter carries, not that it halts anything
    monkeypatch.setenv(TURN_LIMIT_ENV, "50")
    cancel_file.unlink(missing_ok=True)

    log_dir = str(tmp_path / "logs")
    tests_dir = Path(__file__).parent.parent

    prefix = _project_prefix("resume_decode_task")
    projects_before = _inspect_projects(prefix)
    try:
        _run_interrupted_attempt(log_dir, None, tests_dir)

        killed_log = _latest_log(log_dir)
        spent = _spent_budget(killed_log)
        assert spent.turns >= 2 and spent.tokens > 0, (
            f"the killed attempt committed no usable limit snapshot: {spent}"
        )

        reset_generates()
        resume = eval_retry(read_eval_log(killed_log), log_dir=log_dir)[0]
    finally:
        for name in _inspect_projects(prefix) - projects_before:
            _force_remove_project(name)

    assert resume.status == "success"
    assert resume.samples is not None and len(resume.samples) == 1
    sample = resume.samples[0]
    assert sample.error is None

    # The resume runs two turns (bash + submit) — no more than the killed
    # attempt had already spent — so a reset counter cannot reach past it.
    assert sample.turn_count is not None
    assert sample.turn_count > spent.turns

    resumed_tokens = sum(usage.total_tokens for usage in sample.model_usage.values())
    assert resumed_tokens > spent.tokens


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("strategy", ["restic", "archive"])
@pytest.mark.parametrize("interrupt", ["SIGKILL", "SIGINT"])
def test_checkpoint_resume_rehydrated_event_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, strategy: str, interrupt: str
) -> None:
    """Resume works whether the eval was hard-killed or Ctrl-C'd.

    Ctrl-C (SIGINT) runs a lot of graceful cleanup a hard kill skips —
    sandbox teardown, log finalize, a sample logged with a cancellation
    error — so it reaches checkpoint resume down a different path than
    the SIGKILL case, and gets the same result.
    """
    # Crash count (host file) + target + snapshot strategy are inherited by
    # the child processes. Only the fresh attempt reads the strategy; resumes
    # reconstruct it from the log's recorded task args (pin-checked).
    cancel_file = tmp_path / "cancels.txt"
    monkeypatch.setenv(CANCEL_FILE_ENV, str(cancel_file))
    monkeypatch.setenv(TARGET_ENV, "2")
    monkeypatch.setenv(STRATEGY_ENV, strategy)
    # The crash count is stateful on disk. Under flaky-retry (this test is
    # `_needs_flaky_retry` via `skip_if_no_docker`) the body re-runs with the
    # same `tmp_path`, so reset it — otherwise a retry would inherit a
    # count >= target, no attempt would crash, and the retry would
    # spuriously fail.
    cancel_file.unlink(missing_ok=True)

    log_dir = str(tmp_path / "logs")
    tests_dir = Path(__file__).parent.parent

    # A hard kill skips sandbox teardown, so each killed attempt leaks its
    # sandbox container. Track this harness's projects before/after and
    # force-remove the ones this test leaks (the final resume cleans up its
    # own).
    prefix = _project_prefix("resume_decode_task")
    projects_before = _inspect_projects(prefix)
    try:
        # --- attempt #0: fresh eval, interrupted at turn 2 (after ck1/ck2) --
        _run_interrupted_attempt(log_dir, None, tests_dir, interrupt)

        leaked = [
            cid
            for name in _inspect_projects(prefix) - projects_before
            for cid in _project_container_ids(name)
        ]
        if interrupt == "SIGKILL":
            # The hard kill leaves the attempt's sandbox container running —
            # probe it for the snapshot dir's location and permissions.
            assert leaked, "expected the killed attempt to leak its sandbox container"
            _assert_snapshot_dir_hidden(leaked[0], strategy)
        else:
            assert not leaked, f"Ctrl-C should tear down the sandbox; leaked {leaked}"

        # --- attempt #1: resume, work one turn (ck3), interrupt at turn 3 ---
        _run_interrupted_attempt(log_dir, _latest_log(log_dir), tests_dir, interrupt)

        # --- final resume: runs in this process, to completion --------------
        reset_generates()
        resume = eval_retry(read_eval_log(_latest_log(log_dir)), log_dir=log_dir)[0]
    finally:
        for name in _inspect_projects(prefix) - projects_before:
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

    # The live post-resume bash turns (outside any wrap) cat the turn-0 file —
    # their output proves the sandbox *filesystem* was actually restored
    # across both kills (resume merely succeeding can't: the submit answer
    # comes from the model script, not from the sandbox).
    live_bash = [
        e
        for i, e in enumerate(events)
        if isinstance(e, ToolEvent) and e.function == "bash" and not _in_wrap(i)
    ]
    assert live_bash and live_bash[-1].error is None
    assert LAYER1_CONTENT in str(live_bash[-1].result)

    # Every committed snapshot's details name the strategy that wrote them.
    details_by_id = {
        e.checkpoint_id: e.sandboxes["default"]
        for e in events
        if isinstance(e, CheckpointEvent) and "default" in e.sandboxes
    }
    assert {1, 2, 3, 4} <= set(details_by_id)
    expected_strategy = STRATEGY_ARCHIVE if strategy == "archive" else STRATEGY_RESTIC
    assert all(
        snapshot_strategy_name(d) == expected_strategy for d in details_by_id.values()
    )

    if strategy == "archive":
        # A complete tar per checkpoint: no parent to diff against, so no
        # per-snapshot file listing is recorded.
        assert all(
            d.files is None and d.additional_files is None
            for d in details_by_id.values()
        )
    else:
        # File listing (restic) records each sandbox snapshot's added/changed
        # files (diff vs parent), not the whole tree.
        #
        # ckpt-1 is the first sandbox snapshot (no parent) → full listing,
        # which includes the turn-0 write but NOT the XDG cache dir
        # (auto-home excludes $HOME/.cache).
        ckpt1_files = details_by_id[1].files
        assert ckpt1_files is not None
        assert any(p.endswith("workspace/decoded/layer1.txt") for p in ckpt1_files)
        assert not any("/.cache/" in p for p in ckpt1_files)

        # ckpt-3 diffs against its parent (ckpt-2): it lists the post-resume
        # write but NOT the unchanged turn-0 file — proving it's a delta, not
        # the tree.
        ckpt3_details = details_by_id[3]
        assert ckpt3_details.files is not None
        assert any(p.endswith("workspace/resumed.txt") for p in ckpt3_details.files)
        assert not any(
            p.endswith("workspace/decoded/layer1.txt") for p in ckpt3_details.files
        )
        assert ckpt3_details.additional_files is None
