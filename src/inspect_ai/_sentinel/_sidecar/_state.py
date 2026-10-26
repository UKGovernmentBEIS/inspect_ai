"""Monitor state a sidecar keeps, copied into the sample store before Inspect's scorers read it."""

from typing import TYPE_CHECKING

from ._task import MONITOR_STATE_COPY, task_sidecars

if TYPE_CHECKING:
    from inspect_ai.solver._task_state import TaskState


async def copy_sidecar_monitor_state(
    state: "TaskState", eval_id: str | None = None
) -> None:
    """Copy the monitor state of the sidecars a sample's calls went through into its sample store, before it is scored.

    Args:
        state: The sample's state.
        eval_id: The eval whose task the sample is of, where the task's context isn't the caller's, as for interim scoring.
    """
    sidecars = task_sidecars(eval_id)
    if sidecars is not None:
        await sidecars.copy_monitor_state(state.uuid, state.store)


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
