"""End-to-end checkpoint resume test: cancel an attempt, then retry it.

Drives a ``react()`` agent through tool-calling turns with
``TurnInterval(every=1)``, so a checkpoint fires at the start of each turn
after the first; the agent then calls a ``cancel`` tool that interrupts the
sample mid-run, leaving committed checkpoints on disk.
``test_checkpoint_resume_runs_to_completion`` then ``eval_retry``s the
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

from pathlib import Path
from typing import Any

import anyio
import pytest
from test_helpers.transcript import assert_spans_balanced
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.event import SpanBeginEvent, SpanEndEvent, ToolEvent
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
RESUMED_KEY = "resumed"
WRITE_CMD = (
    "mkdir -p /workspace/decoded && "
    f"printf '{LAYER1_CONTENT}' > /workspace/decoded/layer1.txt"
)
SCRIPTED_MODEL = "scripteddecode/model"


class _ResumeState:
    """Module-level state shared by the scripted provider and the cancel tool.

    ``cancelled`` lets the scripted model emit a ``cancel`` call on the
    first attempt and continue past it on resume (the cancel leaves no trace
    in the restored conversation, so an out-of-band flag is needed to
    distinguish the two). ``generates`` counts model calls so the resume test
    can prove the conversation was restored (only the remaining turns run)
    rather than re-run from scratch.
    """

    cancelled: bool = False
    generates: int = 0


_resume_state = _ResumeState()


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
        _resume_state.cancelled = True
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
#           remember again (after resume)        -> ckpt-3 fires next turn
#   turn 3: submit
#
# The post-resume `remember` turn exists so a *new* checkpoint (ckpt-3) fires
# during the retry — the trigger resets on resume, so a single submit turn
# alone would commit nothing.


def _scripted_outputs(
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
) -> ModelOutput:
    _resume_state.generates += 1
    completed_tool_turns = sum(1 for m in input if isinstance(m, ChatMessageTool))
    if completed_tool_turns == 0:
        return ModelOutput.for_tool_call(SCRIPTED_MODEL, "bash", {"command": WRITE_CMD})
    if completed_tool_turns == 1:
        return ModelOutput.for_tool_call(
            SCRIPTED_MODEL, "remember", {"key": STORE_KEY, "value": LAYER1_CONTENT}
        )
    if completed_tool_turns == 2 and not _resume_state.cancelled:
        return ModelOutput.for_tool_call(SCRIPTED_MODEL, "cancel", {})
    if completed_tool_turns == 2:
        # post-resume turn: a second store write so ckpt-3 commits on retry
        return ModelOutput.for_tool_call(
            SCRIPTED_MODEL, "remember", {"key": RESUMED_KEY, "value": LAYER1_CONTENT}
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
        sandbox="docker",
        checkpoint=CheckpointConfig(
            trigger=TurnInterval(every=1),
            sandbox_paths={"default": ["/workspace"]},
            retention="retain",
        ),
    )


@skip_if_no_docker
@pytest.mark.slow
def test_checkpoint_resume_runs_to_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSPECT_CHECKPOINTING", "1")
    _resume_state.cancelled = False
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
    # (one more remember + submit = 2 generates; a fresh re-run would have
    # redone bash + remember as well).
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


@skip_if_no_docker
@pytest.mark.slow
def test_checkpoint_resume_spans_balanced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resumed run's committed transcript must be span-balanced.

    Same cancel-then-retry flow as
    ``test_checkpoint_resume_runs_to_completion``, but asserts structural
    well-formedness of the event stream rather than content presence — the
    one check that catches the rehydration regression.
    """
    monkeypatch.setenv("INSPECT_CHECKPOINTING", "1")
    _resume_state.cancelled = False
    _resume_state.generates = 0

    log_dir = str(tmp_path / "logs")

    # initial attempt: cancels mid-run after checkpoints commit
    log = eval(resume_decode_task(), model=SCRIPTED_MODEL, log_dir=log_dir)[0]
    assert log.status == "error"

    # the cancelled run's own transcript closes its spans on interrupt unwind
    initial = read_eval_log(log.location)
    assert initial.samples is not None
    assert_spans_balanced(initial.samples[0].events)

    # retry: resume from checkpoint and run to completion
    retry_log = eval_retry(log, log_dir=log_dir)[0]
    assert retry_log.status == "success"

    # the rehydrated `prior_run` wrap must be a self-contained, balanced
    # subtree — not closed while restored structural spans are still open
    completed = read_eval_log(retry_log.location)
    assert completed.samples is not None
    assert_spans_balanced(completed.samples[0].events)
