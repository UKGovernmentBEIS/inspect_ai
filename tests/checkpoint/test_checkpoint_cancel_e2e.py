"""End-to-end checkpoint test: cancel an initial attempt, inspect the dir.

Drives a ``react()`` agent with ``mockllm`` through three tool-calling
turns. ``TurnInterval(every=1)`` fires a checkpoint at the start of each
turn after the first, so by the time the agent calls the ``stop`` tool
(which interrupts the sample) two checkpoints have committed. We then
assert on the resulting checkpoint dir: sidecar structure/count, the
host-side ``store.json`` (restored from the ``host/`` restic repo), and
the sandbox files (restored from the ``sandboxes/default/`` repo).

Requires Docker: the sandbox backup path injects/execs a Linux restic
binary inside the sandbox, which only works with a Linux container
(``detect_sandbox_os`` rejects non-Linux hosts). See
``examples/checkpoint_ctf.py`` for the manual harness this replaces.
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.log._samples import sample_active
from inspect_ai.model import Model, ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.tool import Tool, bash, tool
from inspect_ai.util import CheckpointConfig, Retention, TurnInterval, store
from inspect_ai.util._checkpoint._layout.sidecar import (
    CheckpointDetails,
    CheckpointSample,
)
from inspect_ai.util._restic.ops import restore_repo
from inspect_ai.util._restic.resolver import resolve_restic

LAYER1_CONTENT = "plain1"
STORE_KEY = "answer"


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
def stop() -> Tool:
    async def execute() -> str:
        """Stop the run immediately (interrupts the sample)."""
        active = sample_active()
        assert active is not None, "expected an active sample"
        active.interrupt("score")
        # interrupt cancels the surrounding scope; never return normally.
        await anyio.sleep_forever()
        return "stopped"

    return execute


def _scripted_model() -> Model:
    # One tool call per react turn:
    #   turn 1: write a file into the sandbox
    #   turn 2: record a value in the store
    #   turn 3: stop -> interrupt
    # TurnInterval(every=1) fires at the start of turns 2 and 3, so two
    # checkpoints commit before the interrupt takes effect.
    return get_model(
        "mockllm/model",
        memoize=False,
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash",
                tool_arguments={
                    "command": (
                        "mkdir -p /workspace/decoded && "
                        f"printf '{LAYER1_CONTENT}' > /workspace/decoded/layer1.txt"
                    )
                },
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="remember",
                tool_arguments={"key": STORE_KEY, "value": LAYER1_CONTENT},
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="stop",
                tool_arguments={},
            ),
        ],
    )


def _sample_checkpoint_dir(log_location: str) -> Path:
    """Locate the single per-sample checkpoint dir for an eval log."""
    log_dir = Path(log_location).parent
    checkpoint_dirs = list(log_dir.glob("*.checkpoints"))
    assert len(checkpoint_dirs) == 1, (
        f"expected exactly one *.checkpoints dir, found {checkpoint_dirs}"
    )
    sample_dirs = [p for p in checkpoint_dirs[0].glob("*__*") if p.is_dir()]
    assert len(sample_dirs) == 1, (
        f"expected exactly one per-sample dir, found {sample_dirs}"
    )
    return sample_dirs[0]


def _restore(restic: Path, repo: Path, password: str, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    anyio.run(restore_repo, restic, str(repo), password, str(target))


@skip_if_no_docker
def test_checkpoint_cancel_inspect_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSPECT_CHECKPOINTING", "1")

    task = Task(
        dataset=[Sample(input="decode the layers", target=LAYER1_CONTENT)],
        solver=react(tools=[bash(timeout=60), remember(), stop()]),
        scorer=includes(),
        sandbox="docker",
        checkpoint=CheckpointConfig(
            trigger=TurnInterval(every=1),
            sandbox_paths={"default": ["/workspace"]},
            retention=Retention(after_eval="retain"),
        ),
    )

    log = eval(
        task,
        model=_scripted_model(),
        log_dir=str(tmp_path / "logs"),
    )[0]

    # --- locate the checkpoint dir -----------------------------------------
    ckpt_dir = _sample_checkpoint_dir(log.location)

    # --- 1. structure + sidecars -------------------------------------------
    sample_json = ckpt_dir / "sample.json"
    assert sample_json.exists()
    sample_meta = CheckpointSample.model_validate_json(sample_json.read_text())
    assert sample_meta.restic_password

    host_repo = ckpt_dir / "host"
    sandbox_repo = ckpt_dir / "sandboxes" / "default"
    assert (host_repo / "config").exists()
    assert (sandbox_repo / "config").exists()

    sidecars = sorted(ckpt_dir.glob("ckpt-*.json"))
    details = [CheckpointDetails.model_validate_json(p.read_text()) for p in sidecars]
    for i, detail in enumerate(details, start=1):
        assert detail.checkpoint_id == i
        assert detail.trigger == "turn"
        assert detail.host.snapshot_id
        assert detail.sandboxes["default"].snapshot_id

    # --- 2. sidecar count vs triggers --------------------------------------
    # 3 react turns, TurnInterval(every=1): fires at the start of turns 2 & 3.
    assert len(sidecars) == 2

    # --- restore repos for content assertions ------------------------------
    restic = anyio.run(resolve_restic)
    password = sample_meta.restic_password

    # --- 3. host-context content (store.json) ------------------------------
    host_target = tmp_path / "restore_host"
    _restore(restic, host_repo, password, host_target)
    store_data = json.loads((host_target / "store.json").read_text())
    assert store_data.get(STORE_KEY) == LAYER1_CONTENT
    # events.json present and valid JSON
    json.loads((host_target / "events.json").read_text())

    # --- 4. sandbox file capture -------------------------------------------
    sandbox_target = tmp_path / "restore_sandbox"
    _restore(restic, sandbox_repo, password, sandbox_target)
    captured = sandbox_target / "decoded" / "layer1.txt"
    assert captured.exists()
    assert captured.read_text() == LAYER1_CONTENT
