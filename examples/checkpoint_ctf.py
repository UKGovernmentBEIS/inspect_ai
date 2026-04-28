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
from inspect_ai.tool import bash

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
    there's an audit trail of progress.  Continue until you reach a layer
    whose decoded content is a string of the form `FLAG{...}`.  Submit
    that flag as your final answer.

    Process one layer at a time: read the hint, reason about which encoding
    it describes, decode, save, then move on to the next layer in your
    next turn.  Do not try to chain multiple layers in a single command.
    """
)


@task
def checkpoint_ctf() -> Task:
    return Task(
        dataset=[
            Sample(
                input=PROMPT,
                target=FLAG,
                setup=SETUP,
            )
        ],
        solver=react(tools=[bash(timeout=60)]),
        scorer=includes(),
        sandbox="docker",
    )
