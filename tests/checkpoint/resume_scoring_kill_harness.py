"""Harness for the scoring-phase checkpoint-resume e2e test.

Companion to ``resume_kill_harness.py``, but exercises the *other* resume
path. Here the agent loop runs to a **clean** completion, so the checkpointer
fires a final ``agent_complete`` checkpoint. The **scorer** then ``SIGKILL``s
its own process on its first attempt — an abrupt death *after* the solver
finished but *before* scoring committed.

On retry, inspect reads the latest ``agent_complete`` checkpoint, tags the sample
``Attempt.RESUME_FOR_SCORING``, and the ``react`` agent fast-path-returns its
restored state without a single model call; scoring then re-runs to success.

Two roles, like the sibling harness:

1. **Importable** by the test (registers the ``@task`` / ``@modelapi`` /
   ``@scorer`` and exposes shared constants + the in-process generate counter).
2. **Runnable as a script** for the killed attempt::

       python resume_scoring_kill_harness.py <log_dir> [<retry_from>]

Requires Docker (the sandbox backup path injects a Linux restic binary).
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from typing import Any

import anyio

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.model import (
    ChatMessage,
    ChatMessageTool,
    GenerateConfig,
    ModelOutput,
    modelapi,
)
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    scorer,
)
from inspect_ai.solver import TaskState
from inspect_ai.tool import Tool, ToolChoice, ToolInfo, bash, tool
from inspect_ai.util import CheckpointConfig, TurnInterval, store

ANSWER = "decoded-answer"
STORE_KEY = "answer"
SCRIPTED_MODEL = "scoringcrash/model"

# Write under $HOME so the default-user home-dir auto-backup captures it (the
# task declares no `sandbox_paths`), giving each fire a non-empty snapshot.
WRITE_CMD = (
    f'mkdir -p "$HOME/workspace" && printf \'{ANSWER}\' > "$HOME/workspace/answer.txt"'
)

# Scoring-crash count + target live in a host file named by an env var, not
# module state: the killed attempt is a fresh process, and the count must
# survive both the kill and the next process's startup. Read + bumped by the
# crashing scorer.
CANCEL_FILE_ENV = "INSPECT_TEST_SCORING_RESUME_CANCEL_FILE"
TARGET_ENV = "INSPECT_TEST_SCORING_RESUME_TARGET_CANCELS"


def cancels_done() -> int:
    f = os.environ.get(CANCEL_FILE_ENV)
    return int(Path(f).read_text() or "0") if f and Path(f).exists() else 0


def bump_cancels() -> int:
    n = cancels_done() + 1
    f = os.environ.get(CANCEL_FILE_ENV)
    if f:
        Path(f).write_text(str(n))
    return n


def target_cancels() -> int:
    return int(os.environ.get(TARGET_ENV, "1"))


class _ResumeState:
    """In-process model-call counter.

    Meaningful only for the resume that runs in the test process; the killed
    attempt runs in its own process. On a scoring-phase resume the agent is
    skipped entirely, so this must stay at 0 — that's the headline assertion.
    """

    generates: int = 0


_resume_state = _ResumeState()


def generates() -> int:
    return _resume_state.generates


def reset_generates() -> None:
    _resume_state.generates = 0


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


# A short, always-clean agent script keyed off the number of completed tool
# turns in the conversation:
#
#   turn 0: bash (write a sandbox file)   -> ckpt-1 fires next turn
#   turn 1: submit                        -> clean exit: agent_complete checkpoint
#
# No crash tool: the agent always finishes. The crash is injected by the
# scorer instead (see `crashing_includes`).


def _scripted_outputs(
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
) -> ModelOutput:
    _resume_state.generates += 1
    n = sum(1 for m in input if isinstance(m, ChatMessageTool))
    if n == 0:
        return ModelOutput.for_tool_call(SCRIPTED_MODEL, "bash", {"command": WRITE_CMD})
    return ModelOutput.for_tool_call(SCRIPTED_MODEL, "submit", {"answer": ANSWER})


@modelapi(name="scoringcrash")
def _scoringcrash_provider() -> type[MockLLM]:
    class ScoringCrash(MockLLM):
        def __init__(self, model_name: str, **kwargs: Any) -> None:
            kwargs.pop("custom_outputs", None)
            super().__init__(model_name, custom_outputs=_scripted_outputs, **kwargs)

    return ScoringCrash


@scorer(metrics=[accuracy()])
def crashing_includes() -> Scorer:
    """Score `ANSWER in completion`, but SIGKILL the first ``target`` runs.

    The kill lands *after* the solver completed (so the final
    ``agent_complete`` checkpoint is already durable) but *before* scoring
    commits — exactly the failure the scoring-phase resume recovers from.
    """

    async def score(state: TaskState, target: Target) -> Score:
        if cancels_done() < target_cancels():
            bump_cancels()
            os.kill(os.getpid(), signal.SIGKILL)
            await anyio.sleep_forever()  # unreachable; SIGKILL is immediate
        value = CORRECT if ANSWER in state.output.completion else INCORRECT
        return Score(value=value, answer=state.output.completion)

    return score


@task
def resume_scoring_task() -> Task:
    return Task(
        dataset=[
            Sample(id="resume-scoring", input="produce the answer", target=ANSWER)
        ],
        solver=react(tools=[bash(timeout=60), remember()]),
        scorer=crashing_includes(),
        sandbox="docker",
        checkpoint=CheckpointConfig(
            trigger=TurnInterval(every=1),
            retention="retain",
        ),
    )


def run_eval(log_dir: str, retry_from: str | None = None) -> None:
    """Run a fresh eval, or resume one from a prior log.

    Never returns on the attempt whose scorer is due to crash — the scorer
    ``SIGKILL``s the process.
    """
    if retry_from is None:
        eval(resume_scoring_task(), model=SCRIPTED_MODEL, log_dir=log_dir)
    else:
        eval_retry(read_eval_log(retry_from), log_dir=log_dir)


def main() -> None:
    log_dir = sys.argv[1]
    retry_from = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    run_eval(log_dir, retry_from)


if __name__ == "__main__":
    main()
