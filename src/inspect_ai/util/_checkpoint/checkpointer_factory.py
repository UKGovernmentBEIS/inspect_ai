from inspect_ai.util._checkpoint.checkpointer import CheckpointerSetup, ResumeCheckpoint
from inspect_ai.util._checkpoint.checkpointer_impl import _CheckpointerSetup
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer
from inspect_ai.util._checkpoint.config import ResolvedCheckpointConfig


def create_checkpointer(
    *,
    config: ResolvedCheckpointConfig | None,
    log_location: str,
    sample_id: int | str,
    epoch: int,
    resume_checkpoint: ResumeCheckpoint | None = None,
) -> CheckpointerSetup:
    """Build the per-sample checkpointer setup.

    Returns a :class:`_NoopCheckpointer` when ``config`` is ``None``;
    otherwise returns a :class:`_CheckpointerSetup` whose ``__aenter__``
    performs the on-disk + sandbox setup and yields the agent-facing
    :class:`Checkpointer`.
    """
    # TODO(checkpointing): capture the sample-level retry / attempt
    # index. `ActiveSample` does not currently carry it; the value is
    # published via the `on_sample_attempt_start` hook with
    # `attempt: int` (1-based). Likely we add an `attempt` field to
    # `ActiveSample` so it's symmetric with `epoch`.
    if config is None:
        return _NoopCheckpointer()

    return _CheckpointerSetup(
        config=config,
        log_location=log_location,
        sample_id=sample_id,
        epoch=epoch,
        resume_checkpoint=resume_checkpoint,
    )
