"""End-to-end checkpoint resume test: cancel an attempt, then retry it.

Drives a ``react()`` agent through tool-calling turns with
``TurnInterval(every=1)``, so a checkpoint fires at the start of each turn
after the first; the agent then calls a ``cancel`` tool that interrupts the
sample mid-run, leaving committed checkpoints on disk.
``test_checkpoint_resume_runs_to_completion`` then ``eval_retry``s the
cancelled run and asserts — through the public interface only — that it
resumes from the checkpoint and completes successfully. Resume (vs a fresh
re-run) is proven by the agent needing only the final submit turn: the prior
conversation and sandbox state are restored, not replayed.

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
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
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
from inspect_ai.util import CheckpointConfig, Retention, TurnInterval, store

LAYER1_CONTENT = "plain1"
STORE_KEY = "answer"
WRITE_CMD = (
    "mkdir -p /workspace/decoded && "
    f"printf '{LAYER1_CONTENT}' > /workspace/decoded/layer1.txt"
)
SCRIPTED_MODEL = "scripteddecode/model"


class _ResumeState:
    """Module-level state shared by the scripted provider and the cancel tool.

    ``cancelled`` lets the scripted model emit a ``cancel`` call on the
    first attempt and a ``submit`` after (the cancel leaves no trace in the
    restored conversation, so an out-of-band flag is needed to distinguish
    the two). ``generates`` counts model calls so the resume test can prove
    the conversation was restored (one final turn) rather than re-run fresh.
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
# custom_outputs object would not survive the round-trip). The provider
# decides each turn from the restored conversation plus `_resume_state`.


def _scripted_outputs(
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
) -> ModelOutput:
    _resume_state.generates += 1
    called = {m.function for m in input if isinstance(m, ChatMessageTool)}
    if "bash" not in called:
        return ModelOutput.for_tool_call(SCRIPTED_MODEL, "bash", {"command": WRITE_CMD})
    if "remember" not in called:
        return ModelOutput.for_tool_call(
            SCRIPTED_MODEL, "remember", {"key": STORE_KEY, "value": LAYER1_CONTENT}
        )
    if not _resume_state.cancelled:
        return ModelOutput.for_tool_call(SCRIPTED_MODEL, "cancel", {})
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
            retention=Retention(after_eval="retain"),
        ),
    )


@skip_if_no_docker
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

    # resume restored the prior conversation, so only the final submit turn
    # ran (a fresh re-run would have taken three more generates).
    assert _resume_state.generates == 1

    # the restored + completed run scored correct
    assert sample.scores is not None
    assert sample.scores["includes"].value == CORRECT
    assert LAYER1_CONTENT in sample.output.completion
