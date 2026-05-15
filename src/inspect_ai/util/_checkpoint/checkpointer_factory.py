import os
from contextlib import AbstractAsyncContextManager

from inspect_ai._util.logger import warn_once
from inspect_ai.util._checkpoint.checkpointer import Checkpointer, ResumeCheckpoint
from inspect_ai.util._checkpoint.checkpointer_impl import _CheckpointerSetup, logger
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer
from inspect_ai.util._checkpoint.config import CheckpointConfig


def create_checkpointer(
    *,
    config: CheckpointConfig | None,
    log_location: str,
    sample_id: int | str,
    epoch: int,
    eval_id: str,
    resume_checkpoint: ResumeCheckpoint | None = None,
) -> AbstractAsyncContextManager[Checkpointer]:
    """Build the per-sample checkpointer setup.

    Returns a :class:`_NoopSetup` when ``config`` is ``None`` or the
    development gate is off; otherwise returns a
    :class:`_CheckpointerSetup` whose ``__aenter__`` performs the
    on-disk + sandbox setup and yields the agent-facing
    :class:`Checkpointer`.

    Checkpointing is gated off by default while still under
    development — the function returns a no-op setup unless the
    ``INSPECT_CHECKPOINTING`` env var is set to ``"1"``.
    """
    if os.environ.get("INSPECT_CHECKPOINTING") != "1":
        warn_once(logger, "Checkpointing is still not yet fully implemented")
        return _NoopCheckpointer()

    # TODO(checkpointing-phase-3): capture the sample-level retry /
    # attempt index. `ActiveSample` does not currently carry it; the
    # value is published via the `on_sample_attempt_start` hook with
    # `attempt: int` (1-based).  Resolution options are listed in
    # `design/plans/checkpointing-working.md` §1 (re: sample-level
    # retries) — likely we add an `attempt` field to `ActiveSample`
    # so it's symmetric with `epoch`.
    if config is None:
        return _NoopCheckpointer()

    return _CheckpointerSetup(
        config=config,
        log_location=log_location,
        sample_id=sample_id,
        epoch=epoch,
        eval_id=eval_id,
        resume_checkpoint=resume_checkpoint,
    )
