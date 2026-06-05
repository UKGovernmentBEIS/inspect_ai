"""Importable harness for the checkpoint resume-after-hard-kill e2e test.

Lives in ``test_helpers`` (not the test file) so it can be both imported by
the test — registering the ``@task`` / ``@modelapi`` so the final in-process
resume works, and exposing shared constants — and run as a **subprocess**::

    python -c "from test_helpers.checkpoint_resume_kill import main; main()" <log_dir> [<retry_from>]

Running the killed attempts in child processes is what lets the test issue a
*real* ``SIGKILL`` of the eval without taking down pytest. The ``crash`` tool
``os.kill``s its own (child) process at the same point the cooperative
``cancel`` tool used to ``interrupt`` — abruptly, with no graceful unwind, no
``finally``, no log finalize — exercising recovery from an unanticipated death
(power loss / OOM / preemption), which is the whole point of checkpointing.

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
from inspect_ai.scorer import includes
from inspect_ai.tool import Tool, ToolChoice, ToolInfo, bash, tool
from inspect_ai.util import CheckpointConfig, TurnInterval, store

LAYER1_CONTENT = "plain1"
STORE_KEY = "answer"
SCRIPTED_MODEL = "scripteddecode/model"

# Write under $HOME (not /workspace) so the default-user home-dir auto-backup
# captures it — the task declares no `sandbox_paths`, exercising
# `resolve_sandbox_backup_paths` / `_resolve_home_and_cache`. Also drop a file
# under the XDG cache dir ($HOME/.cache) to prove auto-home mode excludes it.
WRITE_CMD = (
    'mkdir -p "$HOME/workspace/decoded" "$HOME/.cache" && '
    f"printf '{LAYER1_CONTENT}' > \"$HOME/workspace/decoded/layer1.txt\" && "
    'printf cache > "$HOME/.cache/junk.txt"'
)
# Written on each post-resume turn so the new snapshot has a non-empty diff vs
# its parent — used to assert file listing records the *changed* file.
RESUME_WRITE_CMD = 'printf resumed > "$HOME/workspace/resumed.txt"'

# The crash count + target live in a host file named by an env var, not module
# state: each killed attempt is a fresh process, and the count must survive
# both the kill and the next process's startup. The file is read by the
# scripted model (to decide when to crash vs work vs submit) and bumped by the
# crash tool just before it kills the process.
CANCEL_FILE_ENV = "INSPECT_TEST_RESUME_CANCEL_FILE"
TARGET_ENV = "INSPECT_TEST_RESUME_TARGET_CANCELS"


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

    Meaningful only for the resume that runs in the test process; killed
    attempts run in their own process.
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


@tool
def crash() -> Tool:
    async def execute() -> str:
        """Kill the eval process immediately (uncatchable, no cleanup)."""
        # Record the crash before dying (flushed to disk), then SIGKILL our own
        # process. Running inside the child, this is the child's PID — an
        # abrupt death with no unwind, mimicking a power loss / OOM / preempt.
        bump_cancels()
        os.kill(os.getpid(), signal.SIGKILL)
        await anyio.sleep_forever()  # unreachable; SIGKILL is immediate
        return "crashed"

    return execute


# eval_retry reconstructs the task by registry name and rebuilds the model by
# name from the log — so the task must be a registered @task and the scripted
# behavior must live in a registered model provider. The provider drives a
# linear script keyed off the number of completed tool turns in the restored
# conversation, plus the host-file crash count:
#
#   turn 0: bash (write a sandbox file)        -> ckpt-1 fires next turn
#   turn 1: remember (write the store)         -> ckpt-2 fires next turn
#   turn 2: crash (1st kill) ..................... SIGKILL, then resume
#           bash (write a new sandbox file)    -> ckpt-3 fires next turn
#   turn 3: crash (2nd kill) ..................... SIGKILL, then resume
#           bash (write a new sandbox file)    -> ckpt-4 fires next turn
#   turn 4: submit
#
# Each resume cycle does one work turn (so a fresh checkpoint commits) before
# crashing, until `target` crashes are reached; the final resume submits.


def _scripted_outputs(
    input: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice,
    config: GenerateConfig,
) -> ModelOutput:
    _resume_state.generates += 1
    n = sum(1 for m in input if isinstance(m, ChatMessageTool))
    done = cancels_done()
    target = target_cancels()
    if n == 0:
        return ModelOutput.for_tool_call(SCRIPTED_MODEL, "bash", {"command": WRITE_CMD})
    if n == 1:
        return ModelOutput.for_tool_call(
            SCRIPTED_MODEL, "remember", {"key": STORE_KEY, "value": LAYER1_CONTENT}
        )
    # The k-th crash (k = done) lands at turn `2 + done`; cycles that don't
    # crash do a work turn that writes a new sandbox file (non-empty diff vs
    # parent), then the final resume submits.
    if done < target and n == 2 + done:
        return ModelOutput.for_tool_call(SCRIPTED_MODEL, "crash", {})
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
        solver=react(tools=[bash(timeout=60), remember(), crash()]),
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


def run_eval(log_dir: str, retry_from: str | None = None) -> None:
    """Run a fresh eval, or resume one from a prior log.

    Never returns when the scripted run is due to crash — the ``crash`` tool
    ``SIGKILL``s the process.
    """
    if retry_from is None:
        eval(resume_decode_task(), model=SCRIPTED_MODEL, log_dir=log_dir)
    else:
        eval_retry(read_eval_log(retry_from), log_dir=log_dir)


def main() -> None:
    log_dir = sys.argv[1]
    retry_from = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    run_eval(log_dir, retry_from)


if __name__ == "__main__":
    main()
