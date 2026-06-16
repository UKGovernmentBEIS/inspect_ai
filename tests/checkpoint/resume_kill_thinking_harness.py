"""Harness for the real-model assistant-internal checkpoint e2e test.

Companion to ``resume_kill_harness.py``. Instead of a scripted ``MockLLM``,
this drives a **real Anthropic model with extended thinking** so the
provider populates its per-sample assistant-internal state (thinking
blocks, keyed by signature). The e2e test asserts that state is dumped
into the checkpoint host context at fire time and restored on resume.

Run as a script for the hard-killed attempt::

    python resume_kill_thinking_harness.py <log_dir> [<retry_from>]

The ``crash`` tool drives a small state machine (a real kill must run in a
child process — see ``resume_kill_harness`` for why):

- before any checkpoint has committed, it tells the model to do more work,
  so the kill can't pre-empt the first checkpoint (the model may emit the
  work + crash calls in the *same* turn, but checkpoints fire only at turn
  boundaries);
- once a checkpoint carrying a thinking block has committed, it records the
  one-shot kill marker and ``SIGKILL``s the child;
- after a prior crash (i.e. on resume) it tells the model to submit, so the
  resumed model — which can't otherwise tell it was resumed — terminates
  cleanly instead of looping.

The model uses adaptive thinking (Claude 4.6+), which engages only when the
task warrants reasoning — so the prompt poses a genuine computation and the
``crash`` tool's "keep working" reply re-asks for step-by-step reasoning,
making a recorded thinking block reliable. The kill is gated on a *committed*
thinking block, so a turn that happens not to think can't pre-empt it.

Requires Docker (sandbox restic injection) and an Anthropic API key.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

import anyio

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai._util.file import local_path
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.scorer import includes
from inspect_ai.tool import Tool, bash, tool
from inspect_ai.util import CheckpointConfig, TurnInterval

ANSWER = "checkpoint-thinking-ok"

# A thinking-capable Anthropic model, pinned explicitly (not env-driven).
# Claude 4.6+ uses adaptive thinking driven by `reasoning_effort` (it rejects
# an explicit `reasoning_tokens` budget); the reasoning-heavy prompt below is
# what makes it actually emit a thinking block to record + checkpoint.
THINKING_MODEL = "anthropic/claude-opus-4-6"

# Host file marking that the one-and-only kill already happened. Lives in an
# env-named file (not module state) because the killed attempt and the resume
# run in separate processes. Set the env var to a writable path before running.
CRASH_FILE_ENV = "INSPECT_TEST_THINKING_CRASH_FILE"

# The eval's log dir, so the ``crash`` tool can check whether a checkpoint
# carrying a thinking block has committed before it kills the process.
LOG_DIR_ENV = "INSPECT_TEST_THINKING_LOG_DIR"


def _crashed_once() -> bool:
    f = os.environ.get(CRASH_FILE_ENV)
    return bool(f and Path(f).exists())


def committed_thinking_signatures(root: str) -> set[str]:
    """Anthropic thinking-block signatures in any checkpoint dump under ``root``.

    ``root`` may be a ``file://`` URI (e.g. derived from an eval log location),
    so resolve it to a local path before walking.
    """
    sigs: set[str] = set()
    if not root:
        return sigs
    for path in Path(local_path(root)).rglob("assistant_internal.json"):
        try:
            blocks = (
                json.loads(path.read_text())
                .get("anthropic", {})
                .get("thinking_blocks", {})
            )
        except (OSError, json.JSONDecodeError):
            continue
        sigs.update(
            b["signature"]
            for b in blocks.values()
            if isinstance(b, dict) and b.get("signature")
        )
    return sigs


@tool
def crash() -> Tool:
    async def execute() -> str:
        """Drive the kill/resume sequence (see module docstring).

        Returns guidance the model is told to follow, or — once a thinking
        checkpoint has committed — ``SIGKILL``s the child process.
        """
        if _crashed_once():
            return f"You were resumed after a crash. Submit the answer '{ANSWER}' now."
        if not committed_thinking_signatures(os.environ.get(LOG_DIR_ENV, "")):
            return (
                "No checkpoint has committed yet. Think step by step about the "
                "problem, run another bash command, then call crash again."
            )
        f = os.environ.get(CRASH_FILE_ENV)
        if f:
            Path(f).write_text("1")
        # SIGKILL our own (child) process: abrupt death, no unwind, no log
        # finalize — the unanticipated-death scenario checkpointing recovers.
        os.kill(os.getpid(), signal.SIGKILL)
        await anyio.sleep_forever()  # unreachable; SIGKILL is immediate
        return "crashed"

    return execute


@task
def resume_thinking_task() -> Task:
    return Task(
        dataset=[
            Sample(
                id="resume-thinking",
                input=(
                    "Think step by step. First, using the bash tool, compute "
                    "how many integers from 1 to 200 are divisible by both 3 "
                    "and 7. Once you have the result, call the crash tool. Then "
                    "do exactly what the crash tool's response tells you to do "
                    "next — keep working if it says to, or submit exactly the "
                    "answer it gives you if it says to submit."
                ),
                target=ANSWER,
            )
        ],
        solver=react(tools=[bash(timeout=60), crash()]),
        scorer=includes(),
        sandbox="docker",
        checkpoint=CheckpointConfig(
            trigger=TurnInterval(every=1),
            retention="retain",
        ),
        message_limit=20,
    )


def run_eval(log_dir: str, retry_from: str | None = None) -> None:
    """Run a fresh eval (with thinking enabled), or resume one from a log.

    Never returns on the killed attempt — ``crash`` ``SIGKILL``s the process
    once a thinking checkpoint commits. ``eval_retry`` rebuilds the model + its
    reasoning config from the prior log, so the resume keeps thinking on.
    """
    os.environ[LOG_DIR_ENV] = log_dir
    if retry_from is None:
        eval(
            resume_thinking_task(),
            model=get_model(
                THINKING_MODEL,
                config=GenerateConfig(reasoning_effort="high"),
            ),
            log_dir=log_dir,
            display="plain",
        )
    else:
        eval_retry(read_eval_log(retry_from), log_dir=log_dir, display="plain")


def main() -> None:
    log_dir = sys.argv[1]
    retry_from = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    run_eval(log_dir, retry_from)


if __name__ == "__main__":
    main()
