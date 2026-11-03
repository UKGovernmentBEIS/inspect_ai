"""Monitor state a sidecar keeps, copied into the sample store before Inspect's scorers read it."""

from typing import TYPE_CHECKING

from ._endpoint import SentinelProxyError
from ._task import MONITOR_STATE_COPY, attempt_number, task_sidecars

if TYPE_CHECKING:
    from inspect_ai.log._samples import ActiveSample
    from inspect_ai.solver._task_state import TaskState


async def copy_sidecar_monitor_state(
    state: "TaskState", active: "ActiveSample | None" = None
) -> None:
    """Copy the monitor state of the sidecars the running attempt's calls went through into its sample store, before it is scored.

    Args:
        state: The sample's state.
        active: The running sample, where it isn't the caller's own, as for interim scoring.
    """
    from inspect_ai.log._samples import sample_active

    sidecars = task_sidecars(active.eval_id if active is not None else None)
    sample = active or sample_active()
    if sidecars is not None and sample is not None:
        await sidecars.copy_monitor_state(
            state.uuid, attempt_number(sample), state.store
        )


async def save_sidecar_monitor_state(state: "TaskState") -> None:
    """Copy the monitor state into the store of a sample saved without being scored, as a failed sample is.

    Inside Inspect, the sample store holds the monitor state when the sample is saved, so a later `inspect score` reads it. The sample has already failed, so a copy that fails doesn't fail it again: the marker in the sample store says why there is no state.
    """
    try:
        await copy_sidecar_monitor_state(state)
    except SentinelProxyError:
        pass


def require_monitor_state() -> None:
    """Check that the monitor state a scorer is about to read was copied from the sidecars, when the sample's calls went through any.

    A scorer that reads monitor state calls this first: a failed copy leaves the state's default values in the sample store, which would read as a sample in which nothing was flagged.

    Raises:
        RuntimeError: If the copy failed.
    """
    from inspect_ai.util._store import store

    copy = store().get(MONITOR_STATE_COPY)
    if isinstance(copy, dict) and not copy.get("copied"):
        raise RuntimeError(
            f"The monitor state wasn't copied from the sentinel sidecar: {copy.get('reason')}."
        )
