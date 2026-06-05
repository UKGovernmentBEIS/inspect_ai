"""End-to-end checkpoint resume test: cancel an attempt, then retry it.

Drives a ``react()`` agent through tool-calling turns with
``TurnInterval(every=1)``, so a checkpoint fires at the start of each turn
after the first; the agent then calls a ``cancel`` tool that interrupts the
sample mid-run, leaving committed checkpoints on disk.
``test_checkpoint_resume_rehydrated_event_layout`` then ``eval_retry``s the
cancelled run and asserts it resumes and completes successfully. It checks,
via the public ``.eval`` log: the restored checkpoints appear as
``CheckpointEvent``s inside the ``prior_run`` ("checkpoint restore") span, a
new checkpoint commits *during* the retry (a ``CheckpointEvent`` outside that
span, continuing the numbering), and resume restored the prior conversation
(only the remaining turns run, not a replay from scratch).

Requires Docker: the sandbox backup path injects/execs a Linux restic
binary inside the sandbox, which only works with a Linux container
(``detect_sandbox_os`` rejects non-Linux hosts). See
``examples/checkpoint_ctf.py`` for the manual harness this replaces.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import anyio
import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.event import Event, SpanBeginEvent, SpanEndEvent, ToolEvent
from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.log import read_eval_log
from inspect_ai.log._samples import sample_active
from inspect_ai.model import (
    ChatMessage,
    ChatMessageTool,
    GenerateConfig,
    ModelOutput,
    modelapi,
)
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.scorer import CORRECT, includes
from inspect_ai.tool import Tool, ToolChoice, ToolInfo, bash, tool
from inspect_ai.util import CheckpointConfig, TurnInterval, store

LAYER1_CONTENT = "plain1"
STORE_KEY = "answer"
# Write under $HOME (not /workspace) so the default-user home-dir auto-backup
# captures it — the task declares no `sandbox_paths`, exercising
# `resolve_sandbox_backup_paths` / `_resolve_home_and_cache`. Also drop a file
# under the XDG cache dir ($HOME/.cache) to prove auto-home mode excludes it.
WRITE_CMD = (
    'mkdir -p "$HOME/workspace/decoded" "$HOME/.cache" && '
    f"printf '{LAYER1_CONTENT}' > \"$HOME/workspace/decoded/layer1.txt\" && "
    'printf cache > "$HOME/.cache/junk.txt"'
)
# Written on the post-resume turn so the ckpt-3 snapshot has a non-empty
# diff vs its parent (ckpt-2) — used to assert file listing records the
# *changed* file, not the unchanged `layer1.txt`.
RESUME_WRITE_CMD = 'printf resumed > "$HOME/workspace/resumed.txt"'
SCRIPTED_MODEL = "scripteddecode/model"


def assert_spans_balanced(events: list[Event]) -> None:
    """Assert the event stream's spans are well-formed (LIFO-nested).

    Treats ``span_begin``/``span_end`` as brackets: every end must close
    the innermost open span, and nothing may be left open at the end.
    Presence/membership assertions can't catch an *additive* structural
    corruption (extra unbalanced spans wrapped around otherwise-correct
    content) — this can. See ``test_checkpoint_resume_spans_balanced``.
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


class _ResumeState:
    """Module-level state shared by the scripted provider and the cancel tool.

    ``generates`` counts model calls so the resume test can prove the
    conversation was restored (only the remaining turns run) rather than
    re-run from scratch.

    The cancel *count* and *target* deliberately do NOT live here: on
    ``eval_retry`` the cancel tool is rebuilt from a re-imported copy of
    this module, so a module-global counter mutated by the tool and read
    by the model would be two different instances. They're kept in a host
    file / env var instead (process-global, re-import-proof) — see
    ``_cancels_done`` / ``_bump_cancels`` / ``_target_cancels``.
    """

    generates: int = 0

    @property
    def cancelled(self) -> bool:
        return _cancels_done() > 0


_resume_state = _ResumeState()

# Env vars set per test. The cancel count is persisted to the file named by
# `_CANCEL_FILE_ENV` so it survives `eval_retry`'s module re-import.
_CANCEL_FILE_ENV = "INSPECT_TEST_RESUME_CANCEL_FILE"
_TARGET_ENV = "INSPECT_TEST_RESUME_TARGET_CANCELS"


def _cancels_done() -> int:
    f = os.environ.get(_CANCEL_FILE_ENV)
    return int(Path(f).read_text() or "0") if f and Path(f).exists() else 0


def _bump_cancels() -> int:
    n = _cancels_done() + 1
    f = os.environ.get(_CANCEL_FILE_ENV)
    if f:
        Path(f).write_text(str(n))
    return n


def _target_cancels() -> int:
    return int(os.environ.get(_TARGET_ENV, "1"))


@tool
def remember() -> Tool:
    async def execute(key: str, value: str) -> str:
        """Record a key/value note in the sample store.

        Args:
            key: short label for the note.
            value: the value to remember.

        Returns:
            Confirmation string.
        """
        store().set(key, value)
        return f"remembered: {key}"

    return execute


@tool
def cancel() -> Tool:
    async def execute() -> str:
        """Cancel the run immediately (interrupts the sample)."""
        active = sample_active()
        assert active is not None, "expected an active sample"
        _bump_cancels()
        active.interrupt("error")
        # interrupt cancels the surrounding scope; never return normally.
        await anyio.sleep_forever()
        return "cancelled"

    return execute


# eval_retry reconstructs the task by registry name and rebuilds the model by
# name from the log — so the task must be a registered @task and the scripted
# behavior must live in a registered model provider (a plain mockllm
# custom_outputs object would not survive the round-trip). The provider drives
# a linear script keyed off the number of completed tool turns in the restored
# conversation, plus `_resume_state`:
#
#   turn 0: bash (write a sandbox file)          -> ckpt-1 fires next turn
#   turn 1: remember (write the store)           -> ckpt-2 fires next turn
#   turn 2: cancel (first attempt) ............... interrupt, then resume
#           bash (write a *new* sandbox file)    -> ckpt-3 fires next turn
#   turn 3: submit
#
# The post-resume bash turn exists so a *new* checkpoint (ckpt-3) fires during
# the retry — the trigger resets on resume, so a single submit turn alone would
# commit nothing. It writes a new file (not the one from turn 0) so ckpt-3's
# diff-vs-parent file listing has a deterministic changed file to assert on.


def _scripted_outputs(
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
) -> ModelOutput:
    _resume_state.generates += 1
    n = sum(1 for m in input if isinstance(m, ChatMessageTool))
    cancels_done = _cancels_done()
    target = _target_cancels()
    if n == 0:
        return ModelOutput.for_tool_call(SCRIPTED_MODEL, "bash", {"command": WRITE_CMD})
    if n == 1:
        return ModelOutput.for_tool_call(
            SCRIPTED_MODEL, "remember", {"key": STORE_KEY, "value": LAYER1_CONTENT}
        )
    # Each resume cycle does one work turn (commits a fresh checkpoint) and
    # then cancels, until `target` cancels are reached. The k-th cancel
    # (k = cancels_done) lands at turn `2 + cancels_done`; the work turn for
    # the cycle that *doesn't* cancel writes a new sandbox file (so the new
    # checkpoint has a non-empty diff vs its parent).
    if cancels_done < target and n == 2 + cancels_done:
        return ModelOutput.for_tool_call(SCRIPTED_MODEL, "cancel", {})
    if n < 2 + target:
        return ModelOutput.for_tool_call(
            SCRIPTED_MODEL, "bash", {"command": RESUME_WRITE_CMD}
        )
    return ModelOutput.for_tool_call(
        SCRIPTED_MODEL, "submit", {"answer": LAYER1_CONTENT}
    )


@modelapi(name="scripteddecode")
def _scripteddecode_provider() -> type[MockLLM]:
    class ScriptedDecode(MockLLM):
        def __init__(self, model_name: str, **kwargs: Any) -> None:
            # ignore any persisted custom_outputs; drive from _scripted_outputs
            kwargs.pop("custom_outputs", None)
            super().__init__(model_name, custom_outputs=_scripted_outputs, **kwargs)

    return ScriptedDecode


@task
def resume_decode_task() -> Task:
    return Task(
        dataset=[Sample(id="resume", input="decode the layers", target=LAYER1_CONTENT)],
        solver=react(tools=[bash(timeout=60), remember(), cancel()]),
        scorer=includes(),
        # Default sandbox image: its ~955 MB /root is mostly /root/.cache,
        # which auto-home mode excludes — so the egress stays small without a
        # custom small-home image, and this exercises that exclude for real.
        sandbox="docker",
        checkpoint=CheckpointConfig(
            trigger=TurnInterval(every=1),
            # No sandbox_paths: the default sandbox's $HOME is auto-captured.
            retention="retain",
        ),
    )


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
    monkeypatch.setenv(_CANCEL_FILE_ENV, str(tmp_path / "cancels.txt"))
    monkeypatch.setenv(_TARGET_ENV, "1")
    _resume_state.generates = 0

    log_dir = str(tmp_path / "logs")

    # --- initial attempt: cancels mid-run after checkpoints commit ---------
    log = eval(resume_decode_task(), model=SCRIPTED_MODEL, log_dir=log_dir)[0]
    assert log.status == "error"
    assert _resume_state.cancelled is True
    assert _resume_state.generates >= 3  # bash, remember, cancel

    # --- retry: resume from checkpoint and run to completion ---------------
    _resume_state.generates = 0
    retry_log = eval_retry(log, log_dir=log_dir)[0]

    assert retry_log.status == "success"
    assert retry_log.samples is not None and len(retry_log.samples) == 1
    sample = retry_log.samples[0]
    assert sample.error is None

    # resume restored the prior conversation, so only the remaining turns ran
    # (one bash + submit = 2 generates; a fresh re-run would have redone the
    # turn-0 bash + turn-1 remember as well).
    assert _resume_state.generates == 2

    # the restored + completed run scored correct
    assert sample.scores is not None
    assert sample.scores["includes"].value == CORRECT
    assert LAYER1_CONTENT in sample.output.completion

    # --- examine the completed .eval: restore span + checkpoint events -----
    completed = read_eval_log(retry_log.location)
    assert completed.samples is not None
    events = completed.samples[0].events

    # the rehydrated history is wrapped in a single "checkpoint restore" span
    # (type "prior_run")
    restore_spans = [
        e for e in events if isinstance(e, SpanBeginEvent) and e.type == "prior_run"
    ]
    assert len(restore_spans) == 1
    restore_span = restore_spans[0]
    assert restore_span.name.startswith("checkpoint restore")

    # events contained by that span (between its begin and matching end)
    begin_idx = next(
        i
        for i, e in enumerate(events)
        if isinstance(e, SpanBeginEvent) and e.id == restore_span.id
    )
    end_idx = next(
        i
        for i, e in enumerate(events)
        if isinstance(e, SpanEndEvent) and e.id == restore_span.id
    )
    restored = events[begin_idx + 1 : end_idx]

    # a CheckpointEvent for each checkpoint that fired in the initial attempt,
    # all rehydrated inside the restore span
    restored_checkpoint_ids = {
        e.checkpoint_id for e in restored if isinstance(e, CheckpointEvent)
    }
    assert restored_checkpoint_ids == {1, 2}

    # the prior tool activity was rehydrated inside the span too
    restored_tools = {e.function for e in restored if isinstance(e, ToolEvent)}
    assert {"bash", "remember"} <= restored_tools

    # a checkpoint committed *during* the retry shows up as a CheckpointEvent
    # outside the restore span (the live resumed session), continuing the
    # numbering past the restored ones.
    new_checkpoint_ids = {
        e.checkpoint_id
        for i, e in enumerate(events)
        if isinstance(e, CheckpointEvent) and not (begin_idx < i < end_idx)
    }
    assert new_checkpoint_ids == {3}

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


@skip_if_no_docker
@pytest.mark.slow
def test_checkpoint_resume_spans_balanced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two resume cycles must yield a span-balanced final transcript.

    Like ``test_checkpoint_resume_rehydrated_event_layout`` but cancels
    *twice*: cancel mid-run, resume (work one turn, cancel again), resume
    again to completion. The second resume hydrates a buffer that already
    contains the first resume's ``prior_run`` wrap, so it exercises the
    wrap-reparenting path — the case that catches the rehydration
    regression. Asserts structural balance plus two sequentially-numbered
    sibling restore wraps.
    """
    monkeypatch.setenv("INSPECT_CHECKPOINTING", "1")
    monkeypatch.setenv(_CANCEL_FILE_ENV, str(tmp_path / "cancels.txt"))
    monkeypatch.setenv(_TARGET_ENV, "2")
    _resume_state.generates = 0

    log_dir = str(tmp_path / "logs")

    # initial attempt: cancels mid-run after ckpt-1/ckpt-2 commit
    log = eval(resume_decode_task(), model=SCRIPTED_MODEL, log_dir=log_dir)[0]
    assert log.status == "error"

    # the cancelled run's own transcript closes its spans on interrupt unwind
    initial = read_eval_log(log.location)
    assert initial.samples is not None
    assert_spans_balanced(initial.samples[0].events)

    # first resume: one work turn commits a fresh checkpoint, then cancels
    resume1 = eval_retry(log, log_dir=log_dir)[0]
    assert resume1.status == "error"

    # second resume: hydrates a buffer that already holds the first wrap
    resume2 = eval_retry(resume1, log_dir=log_dir)[0]
    assert resume2.status == "success"

    # the rehydrated `prior_run` wraps must form self-contained, balanced
    # subtrees — not closed while restored structural spans are still open
    completed = read_eval_log(resume2.location)
    assert completed.samples is not None
    events = completed.samples[0].events
    assert_spans_balanced(events)

    # two sibling restore wraps, sequentially numbered
    wrap_names = [
        e.name
        for e in events
        if isinstance(e, SpanBeginEvent) and e.type == "prior_run"
    ]
    assert wrap_names == ["checkpoint restore 1", "checkpoint restore 2"]
