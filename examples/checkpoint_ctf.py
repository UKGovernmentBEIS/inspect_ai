"""Layered-decoder CTF — test harness for the checkpointing work stream.

Single sample, multi-turn, sandbox-state-heavy. The agent peels back five
encoding layers under ``/workspace/ctf/`` and submits the flag.

Why this shape, as a test harness for checkpoint+resume:

* Each turn writes a new file under ``/workspace/ctf/decoded/``, so the
  sandbox's filesystem state grows monotonically. A correct resume must
  preserve those files.
* "Where am I?" is observable from disk (which decoded files exist) and
  from the conversation history (the agent's prior reasoning), so a
  resume that restores only one of the two will visibly fail.
* Bounded (5 layers, ~10–15 turns) and verifiable (exact flag string).
* Self-contained: no network, only stdlib coreutils inside the sandbox.

Usage:

    inspect eval examples/checkpoint_ctf.py --model openai/gpt-4o

To exercise resume: kill the eval mid-way (Ctrl-C), then
``inspect eval retry <log-file>``.
"""

from textwrap import dedent

from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.tool import Tool, bash, tool
from inspect_ai.util import CheckpointConfig, store
from inspect_ai.util._checkpoint._triggers.types import TokenInterval

FLAG = "FLAG{checkpointing-actually-works}"

# Builds /workspace/ctf/layer1..layer5 at sample init time.  Each file is
# two lines:
#
#   hint: <description that the agent must reason about to identify the encoding>
#   payload: <encoded data>
#
# The hint is a riddle, not a literal label, so a single bash script can't
# dispatch to a known decoder; the agent must reason per layer.  Decoded
# payload is "next: layerK" for layers 1-4 and the flag for layer 5.
SETUP = dedent(
    f"""\
    set -eu
    mkdir -p /workspace/ctf/decoded
    cd /workspace/ctf

    # layer1 -> "next: layer2", base64
    cat > layer1 <<EOF
    hint: an encoding often seen ending in = or ==, using 64 distinct characters
    payload: $(printf 'next: layer2' | base64 -w0)
    EOF

    # layer2 -> "next: layer3", hex
    cat > layer2 <<EOF
    hint: each byte rendered as two characters drawn from 0-9 and a-f
    payload: $(printf 'next: layer3' | od -An -tx1 | tr -d ' \\n')
    EOF

    # layer3 -> "next: layer4", rot13
    cat > layer3 <<EOF
    hint: a simple Caesar cipher shifted by 13 - its own inverse
    payload: $(printf 'next: layer4' | tr 'A-Za-z' 'N-ZA-Mn-za-m')
    EOF

    # layer4 -> "next: layer5", reverse
    cat > layer4 <<EOF
    hint: read the string from the last character to the first
    payload: $(printf 'next: layer5' | rev)
    EOF

    # layer5 -> the flag, base32
    cat > layer5 <<EOF
    hint: an encoding using A-Z and digits 2-7, padded with =
    payload: $(printf '{FLAG}' | base32 -w0)
    EOF
    """
)

PROMPT = dedent(
    """\
    A trail of encoded files lives under /workspace/ctf/.  Start with
    layer1.

    Each file is two lines:

        hint: <description of how the payload is encoded>
        payload: <encoded data>

    The hint is a riddle — read it and figure out which encoding scheme
    it describes, then decode the payload.  The decoded plaintext tells
    you the next layer's filename (it will look like `next: layerN`).

    Save each decoded plaintext to /workspace/ctf/decoded/<filename>.txt so
    there's an audit trail of progress.  After saving, also call
    `remember(key="layer_<N>_plaintext", value=<decoded>)` so the
    structured progress is captured alongside the files.  Continue until
    you reach a layer whose decoded content is a string of the form
    `FLAG{...}`.  Submit that flag as your final answer.

    Process one layer at a time: read the hint, reason about which encoding
    it describes, decode, save, remember, then move on to the next layer
    in your next turn.  Do not try to chain multiple layers in a single
    command.
    """
)


@tool
def remember() -> Tool:
    async def execute(key: str, value: str) -> str:
        """Record a key/value note that persists across the sample.

        Used by the CTF agent to record decoded layer plaintexts so that
        the host-side `Store` accumulates structured per-checkpoint state
        (visible in the per-attempt `store.json` snapshots).

        Args:
            key: short label for the note (e.g. ``layer_1_plaintext``).
            value: the value to remember (the decoded plaintext).

        Returns:
            Confirmation string echoing the key.
        """
        store().set(key, value)
        return f"remembered: {key}={value!r}"

    return execute


@task
def cp_ctf() -> Task:
    return Task(
        dataset=[
            Sample(
                input=PROMPT,
                target=FLAG,
                setup=SETUP,
            )
        ],
        solver=react(tools=[bash(timeout=60), remember()]),
        scorer=includes(),
        sandbox="docker",
        checkpoint=CheckpointConfig(
            trigger=TokenInterval(5000),
            # trigger=TurnInterval(1),
            sandbox_paths={"default": ["/workspace"]},
        ),
    )


# ---------------------------------------------------------------------------
# Debug entry point: run this file as a script (under a debugger) to kick off
# a retry of the most recent `cp_ctf` log without going through the CLI. Drop
# breakpoints anywhere in the retry flow (e.g. `_CheckpointerSetup.__aenter__`,
# `eval_log_sample_source._resume_if_checkpointed`, `run_sample`'s
# `ResumeCheckpoint` branch) and step through.
#
#   python examples/checkpoint_ctf.py                 # newest log in ./logs/
#   python examples/checkpoint_ctf.py path/to/x.eval  # specific log
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import sys

    from inspect_ai import eval_retry

    # The env-var gate is still on — guarantee it's set so the checkpointer
    # actually engages rather than returning a no-op.
    os.environ.setdefault("INSPECT_CHECKPOINTING", "1")

    # Default log: a known-incomplete-with-sidecars cp_ctf run captured
    # for local debugging. Override by passing a log path as argv[1].
    DEFAULT_LOG = "logs/2026-05-19T18-27-48-00-00_cp-ctf_evrSez33AVsudxeecu9DtJ.eval"
    log_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG

    print(f"Retrying {log_path}")
    eval_retry(log_path)
