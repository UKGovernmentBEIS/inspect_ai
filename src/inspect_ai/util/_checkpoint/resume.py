"""Resume detection: does a sample's own checkpoints dir hold a committed checkpoint?

Shared by ``run_sample`` (task retries and in-eval requeues) and the
control channel's requeue advisory, so all three answer the question
the same way. Detection consults only this attempt's *own* eval
checkpoints dir — the retry startup copy replicated every sample dir
the retried attempt had (see ``_resume_copy``), so a sample either has
a committed checkpoint here or it runs fresh.
"""

from __future__ import annotations

from typing import Literal

from ._layout.sample_checkpoints_dir import (
    sample_checkpoints_dir,
    scan_latest_committed_checkpoint,
)
from .checkpointer import ResumeCheckpoint


async def resolve_resume_checkpoint(
    eval_checkpoints_dir: str | None, sample_id: int | str, epoch: int
) -> ResumeCheckpoint | None:
    """The sample's checkpoint resume, or ``None`` when it has nothing committed."""
    if eval_checkpoints_dir is None:
        return None
    checkpoint = await scan_latest_committed_checkpoint(
        sample_checkpoints_dir(eval_checkpoints_dir, sample_id, epoch)
    )
    if checkpoint is None:
        return None
    # Latest parseable checkpoint with ``trigger == "agent_complete"`` =
    # agent finished cleanly, scoring is the next thing → the re-run can
    # skip the agent loop (the ``"resume_for_scoring"`` attempt).
    attempt: Literal["initial", "resume", "resume_for_scoring"] = (
        "resume_for_scoring" if checkpoint.trigger == "agent_complete" else "resume"
    )
    return ResumeCheckpoint(attempt=attempt)
